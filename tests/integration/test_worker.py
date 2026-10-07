import asyncio
import shutil
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest

from spikecut.infra import ffmpeg
from spikecut.ingest.buffer import list_run_dirs, list_segments, session_dir
from spikecut.ingest.worker import ChannelIngest
from spikecut.sources.static_video import StaticVideoSource

pytestmark = [
    pytest.mark.skipif(shutil.which(ffmpeg.FFMPEG_BIN) is None, reason="ffmpeg not installed"),
    pytest.mark.usefixtures("no_orphans"),
]


def recording_backoff() -> tuple[list[int], Callable[[int], float]]:
    attempts: list[int] = []

    def backoff(attempt: int) -> float:
        attempts.append(attempt)
        return 0.0

    return attempts, backoff


async def run_until(
    ingest: ChannelIngest, condition: Callable[[], bool], timeout: float = 30
) -> None:
    task = asyncio.create_task(ingest.run())
    try:
        async with asyncio.timeout(timeout):
            while not condition():
                await asyncio.sleep(0.05)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_reconnects_after_stream_ends(source_video: Path, tmp_path: Path) -> None:
    attempts, backoff = recording_backoff()
    channel_id, session_id = uuid4(), uuid4()
    ingest = ChannelIngest(
        channel_id,
        "demo",
        session_id,
        StaticVideoSource(str(source_video)),
        tmp_path,
        backoff=backoff,
    )
    session = session_dir(tmp_path, channel_id, session_id)

    await run_until(ingest, lambda: len(attempts) >= 2)

    # Every run wrote segments, so attempts reset and reconnection is immediate.
    assert attempts[:2] == [0, 0]
    assert len(list_run_dirs(session)) >= 2
    assert len(list_segments(session)) >= 4


async def test_failing_input_backs_off(tmp_path: Path) -> None:
    attempts, backoff = recording_backoff()
    source = StaticVideoSource(str(tmp_path / "missing.mp4"))
    ingest = ChannelIngest(uuid4(), "demo", uuid4(), source, tmp_path / "buffer", backoff=backoff)

    await run_until(ingest, lambda: len(attempts) >= 3)

    assert attempts[:3] == [1, 2, 3]


@pytest.mark.usefixtures("endless_input")
async def test_cancel_stops_ffmpeg(source_video: Path, tmp_path: Path) -> None:
    channel_id, session_id = uuid4(), uuid4()
    ingest = ChannelIngest(
        channel_id, "demo", session_id, StaticVideoSource(str(source_video)), tmp_path
    )

    await run_until(
        ingest, lambda: ingest.recorder is not None and ingest.recorder.segments_written >= 1
    )

    assert ingest.recorder is not None
    assert ingest.recorder._proc is not None
    assert ingest.recorder._proc.returncode is not None
    assert list_segments(session_dir(tmp_path, channel_id, session_id))
