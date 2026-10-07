import asyncio
import shutil
from pathlib import Path

import pytest

from spikecut.infra import ffmpeg
from spikecut.ingest.buffer import SEGMENT_LIST, parse_segment_list, to_segments
from spikecut.ingest.recorder import Recorder
from spikecut.time import utc_now

pytestmark = [
    pytest.mark.skipif(shutil.which(ffmpeg.FFMPEG_BIN) is None, reason="ffmpeg not installed"),
    pytest.mark.usefixtures("no_orphans"),
]


async def test_records_finite_input(source_video: Path, tmp_path: Path) -> None:
    rec = Recorder(str(source_video), tmp_path)

    async with rec:
        result = await asyncio.wait_for(rec.wait(), timeout=30)

    assert result.rc == 0
    assert result.segments_written >= 2
    assert rec.run_dir is not None
    assert rec.anchor is not None
    assert abs((utc_now() - rec.anchor).total_seconds()) < 30

    entries = parse_segment_list((rec.run_dir / SEGMENT_LIST).read_text())
    segments = to_segments(entries, rec.run_dir, rec.anchor)
    assert len(segments) == result.segments_written
    assert all(s.path.exists() for s in segments)
    assert segments[0].start == rec.anchor


async def test_bad_input_writes_no_segments(tmp_path: Path) -> None:
    rec = Recorder(str(tmp_path / "missing.mp4"), tmp_path / "session")

    async with rec:
        result = await asyncio.wait_for(rec.wait(), timeout=30)

    assert result.rc != 0
    assert result.segments_written == 0
    assert "missing.mp4" in result.stderr_tail


@pytest.mark.usefixtures("endless_input")
async def test_context_exit_stops_ffmpeg_and_finalizes_segments(
    source_video: Path, tmp_path: Path
) -> None:
    rec = Recorder(str(source_video), tmp_path)

    async with rec:
        await asyncio.sleep(5)

    assert rec._proc is not None
    assert rec._proc.returncode is not None
    assert rec.segments_written >= 1
    assert rec.run_dir is not None
    [*_, last] = sorted(rec.run_dir.glob("*.ts"))
    await ffmpeg.run_checked(["-i", str(last), "-f", "null", "-"], timeout=10)


@pytest.mark.usefixtures("endless_input")
async def test_cancel_stops_ffmpeg(source_video: Path, tmp_path: Path) -> None:
    async def record() -> None:
        async with Recorder(str(source_video), tmp_path) as rec:
            await rec.wait()

    task = asyncio.create_task(record())
    await asyncio.sleep(2)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    # no_orphans checks the ffmpeg process is dead after the test


async def test_recorder_is_single_use(source_video: Path, tmp_path: Path) -> None:
    rec = Recorder(str(source_video), tmp_path)
    async with rec:
        await asyncio.wait_for(rec.wait(), timeout=30)

    with pytest.raises(RuntimeError):
        await rec.start()
