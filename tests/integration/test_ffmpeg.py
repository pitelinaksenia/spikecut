import asyncio
import shutil
from asyncio.subprocess import Process
from pathlib import Path

import pytest

from spikecut.infra import ffmpeg

pytestmark = [
    pytest.mark.skipif(shutil.which(ffmpeg.FFMPEG_BIN) is None, reason="ffmpeg not installed"),
    pytest.mark.usefixtures("no_orphans"),
]

FINITE_INPUT = ["-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=25"]
ENDLESS_INPUT = ["-re", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25"]
NULL_OUTPUT = ["-f", "null", "-"]


def segment_args(out_dir: Path) -> list[str]:
    return [
        *ENDLESS_INPUT,
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-g",
        "25",
        "-f",
        "segment",
        "-segment_time",
        "1",
        str(out_dir / "%03d.ts"),
    ]


async def test_run_success() -> None:
    rc, _ = await ffmpeg.run([*FINITE_INPUT, *NULL_OUTPUT], timeout=10)

    assert rc == 0


async def test_run_checked_raises_on_bad_input(tmp_path: Path) -> None:
    missing = tmp_path / "missing.mp4"

    with pytest.raises(ffmpeg.FfmpegError) as exc_info:
        await ffmpeg.run_checked(["-i", str(missing), *NULL_OUTPUT], timeout=10)

    assert exc_info.value.rc != 0
    assert "missing.mp4" in exc_info.value.stderr


async def test_run_timeout_kills_process(no_orphans: list[Process]) -> None:
    with pytest.raises(ffmpeg.FfmpegTimeoutError) as exc_info:
        await ffmpeg.run([*ENDLESS_INPUT, *NULL_OUTPUT], timeout=0.5)

    assert exc_info.value.rc is None
    assert len(no_orphans) == 1


async def test_run_cancel_propagates_and_kills(no_orphans: list[Process]) -> None:
    task = asyncio.create_task(ffmpeg.run([*ENDLESS_INPUT, *NULL_OUTPUT], timeout=10))
    await asyncio.sleep(0.5)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(no_orphans) == 1


async def test_spawn_wait_returns_when_process_exits() -> None:
    proc = await ffmpeg.spawn([*FINITE_INPUT, *NULL_OUTPUT])

    rc = await asyncio.wait_for(proc.wait(), timeout=10)

    assert rc == 0
    assert proc.returncode == 0


async def test_spawn_collects_stderr_tail(tmp_path: Path) -> None:
    proc = await ffmpeg.spawn(["-i", str(tmp_path / "missing.mp4"), *NULL_OUTPUT])

    rc = await asyncio.wait_for(proc.wait(), timeout=10)

    assert rc != 0
    assert "missing.mp4" in proc.stderr_tail()


async def test_stop_finalizes_segments(tmp_path: Path) -> None:
    proc = await ffmpeg.spawn(segment_args(tmp_path))
    await asyncio.sleep(3)

    rc = await proc.stop()

    # 0 when stopped via "q" (Windows), 255 when stopped via SIGINT (POSIX).
    assert rc in (0, 255)
    segments = sorted(tmp_path.glob("*.ts"))
    assert len(segments) >= 2
    # The last segment was being written at stop time: it must still be readable.
    await ffmpeg.run_checked(["-i", str(segments[-1]), *NULL_OUTPUT], timeout=10)


async def test_stop_is_idempotent() -> None:
    proc = await ffmpeg.spawn([*ENDLESS_INPUT, *NULL_OUTPUT])
    await asyncio.sleep(0.5)

    first = await proc.stop()
    second = await proc.stop()

    assert first == second


async def test_stop_kills_when_interrupt_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = await ffmpeg.spawn([*ENDLESS_INPUT, *NULL_OUTPUT])
    monkeypatch.setattr(proc, "_interrupt", lambda: None)

    rc = await asyncio.wait_for(proc.stop(timeout=0.5), timeout=5)

    assert rc not in (0, 255)
    assert proc.returncode is not None
