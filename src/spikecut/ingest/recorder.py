import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Self

import structlog

from spikecut.infra import ffmpeg
from spikecut.ingest.buffer import SEGMENT_LIST, SegmentEntry, parse_segment_list, run_dir
from spikecut.time import utc_now

log = structlog.get_logger(__name__)

SEGMENT_PATTERN = "%06d.ts"
RW_TIMEOUT_US = 10_000_000
POLL_INTERVAL_S = 0.5


def segment_args(input_url: str, run_dir: Path, segment_time: int = 2) -> list[str]:
    return [
        "-rw_timeout",
        str(RW_TIMEOUT_US),
        "-i",
        input_url,
        "-map",
        "0:v",
        "-map",
        "0:a?",
        "-c",
        "copy",
        "-f",
        "segment",
        "-segment_time",
        str(segment_time),
        "-reset_timestamps",
        "1",
        "-segment_format",
        "mpegts",
        "-segment_list",
        str(run_dir / SEGMENT_LIST),
        "-segment_list_type",
        "csv",
        str(run_dir / SEGMENT_PATTERN),
    ]


@dataclass(frozen=True)
class RecorderResult:
    rc: int
    segments_written: int
    stderr_tail: str


class Recorder:
    def __init__(self, input_url: str, session_dir: Path, segment_time: int = 2) -> None:
        self._input_url = input_url
        self._session_dir = session_dir
        self._segment_time = segment_time
        self.anchor: datetime | None = None
        self.run_dir: Path | None = None
        self.segments_written = 0
        self.last_segment_at: datetime | None = None
        self._proc: ffmpeg.FfmpegProcess | None = None
        self._watch_task: asyncio.Task[None] | None = None
        self._offset = 0

    async def start(self) -> None:
        if self._proc is not None:
            raise RuntimeError("Recorder is single-use, create a new one")
        anchor = utc_now()
        directory = run_dir(self._session_dir, anchor)
        directory.mkdir(parents=True)
        self.anchor = anchor
        self.run_dir = directory
        self._proc = await ffmpeg.spawn(
            segment_args(self._input_url, directory, self._segment_time)
        )
        self._watch_task = asyncio.create_task(self._watch_segment_list())
        log.info("recorder_started", run_dir=str(directory), pid=self._proc.pid)

    async def wait(self) -> RecorderResult:
        """Wait until ffmpeg exits on its own (stream ended, network timeout)."""
        rc = await self._require_proc().wait()
        return await self._finish(rc)

    async def stop(self, timeout: float = 5) -> RecorderResult:
        """Gracefully stop ffmpeg so the last segment is finalized."""
        rc = await self._require_proc().stop(timeout)
        return await self._finish(rc)

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._proc is not None and self._proc.returncode is None:
            await self.stop()

    def _require_proc(self) -> ffmpeg.FfmpegProcess:
        if self._proc is None:
            raise RuntimeError("Recorder is not started")
        return self._proc

    async def _finish(self, rc: int) -> RecorderResult:
        task, self._watch_task = self._watch_task, None
        if task is not None:
            task.cancel()
            await asyncio.wait({task})
            if not task.cancelled() and (err := task.exception()) is not None:
                log.error("recorder_watch_failed", error=repr(err))
        # Segments closed right before exit may not have been picked up by the poll yet.
        self._read_new_entries()

        result = RecorderResult(
            rc=rc,
            segments_written=self.segments_written,
            stderr_tail=self._require_proc().stderr_tail(),
        )
        log.info("recorder_finished", rc=rc, segments_written=self.segments_written)
        return result

    async def _watch_segment_list(self) -> None:
        while True:
            self._read_new_entries()
            await asyncio.sleep(POLL_INTERVAL_S)

    def _read_new_entries(self) -> None:
        """Read only complete lines appended to the csv since the last call."""
        if self.run_dir is None:
            return
        try:
            with (self.run_dir / SEGMENT_LIST).open("rb") as f:
                f.seek(self._offset)
                chunk = f.read()
        except FileNotFoundError:
            return  # first segment is not closed yet

        complete = chunk[: chunk.rfind(b"\n") + 1]
        self._offset += len(complete)
        for entry in parse_segment_list(complete.decode(errors="replace")):
            self._on_segment(entry)

    def _on_segment(self, entry: SegmentEntry) -> None:
        now = utc_now()
        if self.segments_written == 0 and self.anchor is not None:
            expected_end = self.anchor + timedelta(seconds=entry.end)
            delay = (now - expected_end).total_seconds()
            log.info("recorder_first_segment", startup_delay_s=round(delay, 2))
        self.segments_written += 1
        self.last_segment_at = now
