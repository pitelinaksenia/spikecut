import asyncio
import random
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import structlog

from spikecut.ingest.buffer import cleanup, session_dir
from spikecut.ingest.recorder import Recorder
from spikecut.sources.base import VideoSource
from spikecut.time import utc_now

log = structlog.get_logger(__name__)

CLEANUP_INTERVAL_S = 10.0
CLEANUP_GRACE_S = 30
MAX_BACKOFF_EXPONENT = 30


def backoff_delay(
    attempt: int, base: float = 1.0, cap: float = 60.0, rand: Callable[[], float] = random.random
) -> float:
    return rand() * min(cap, base * 2.0 ** min(attempt, MAX_BACKOFF_EXPONENT))


class ChannelIngest:
    def __init__(
        self,
        channel_id: UUID,
        login: str,
        session_id: UUID,
        source: VideoSource,
        buffer_dir: Path,
        segment_time: int = 2,
        backoff: Callable[[int], float] = backoff_delay,
    ) -> None:
        self.channel_id = channel_id
        self.login = login
        self.session_id = session_id
        self.recorder: Recorder | None = None
        self._source = source
        self._session_dir = session_dir(buffer_dir, channel_id, session_id)
        self._segment_time = segment_time
        self._backoff = backoff
        self._log = log.bind(channel_id=str(channel_id), session_id=str(session_id))

    async def run(self) -> None:
        attempt = 0
        while True:
            try:
                recorded = await self._record_once()
            except Exception:
                self._log.exception("ingest_attempt_failed")
                recorded = False

            attempt = 0 if recorded else attempt + 1
            delay = self._backoff(attempt)
            self._log.info("ingest_reconnect_scheduled", attempt=attempt, delay_s=round(delay, 2))
            await asyncio.sleep(delay)

    async def _record_once(self) -> bool:
        url = await self._source.stream_url(self.login)
        if url is None:
            self._log.info("ingest_stream_unavailable", login=self.login)
            return False

        recorder = Recorder(url, self._session_dir, self._segment_time)
        self.recorder = recorder
        async with recorder:
            result = await recorder.wait()

        log_method = self._log.info if result.rc == 0 else self._log.warning
        log_method(
            "ingest_recorder_exited",
            rc=result.rc,
            segments_written=result.segments_written,
            stderr_tail=result.stderr_tail,
        )
        return result.segments_written > 0


async def run_cleanup_loop(
    buffer_dir: Path, retention_s: int, interval_s: float = CLEANUP_INTERVAL_S
) -> None:
    while True:
        older_than = utc_now() - timedelta(seconds=retention_s + CLEANUP_GRACE_S)
        try:
            removed = await asyncio.to_thread(cleanup, buffer_dir, older_than)
        except OSError:
            log.exception("buffer_cleanup_failed")
        else:
            if removed:
                log.debug("buffer_cleanup", removed=removed)
        await asyncio.sleep(interval_s)
