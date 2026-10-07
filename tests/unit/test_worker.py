import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from spikecut.ingest import worker as worker_module
from spikecut.ingest.buffer import list_run_dirs, session_dir
from spikecut.ingest.worker import (
    CLEANUP_GRACE_S,
    ChannelIngest,
    backoff_delay,
    run_cleanup_loop,
)
from spikecut.sources.base import VideoSource
from spikecut.time import utc_now


def test_backoff_doubles_each_attempt() -> None:
    delays = [backoff_delay(a, rand=lambda: 1.0) for a in range(4)]

    assert delays == [1.0, 2.0, 4.0, 8.0]


def test_backoff_is_capped() -> None:
    assert backoff_delay(10, cap=60.0, rand=lambda: 1.0) == 60.0


def test_backoff_survives_huge_attempt() -> None:
    assert backoff_delay(5000, cap=60.0, rand=lambda: 1.0) == 60.0


def test_backoff_applies_jitter() -> None:
    assert backoff_delay(2, rand=lambda: 0.0) == 0.0
    assert backoff_delay(2, rand=lambda: 0.5) == 2.0


async def wait_until(condition: Callable[[], bool], timeout: float = 5) -> None:
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.01)


async def run_until(coro: Awaitable[None], condition: Callable[[], bool]) -> None:
    """Run a never-ending loop until condition holds, then cancel it."""
    task = asyncio.ensure_future(coro)
    try:
        await wait_until(condition)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


class OfflineSource(VideoSource):
    def __init__(self) -> None:
        self.calls = 0

    async def stream_url(self, login: str) -> str | None:
        self.calls += 1
        return None


class BrokenSource(VideoSource):
    async def stream_url(self, login: str) -> str | None:
        raise RuntimeError("source is broken")


def recording_backoff() -> tuple[list[int], Callable[[int], float]]:
    attempts: list[int] = []

    def backoff(attempt: int) -> float:
        attempts.append(attempt)
        return 0.0

    return attempts, backoff


async def test_offline_channel_backs_off_without_recording(tmp_path: Path) -> None:
    source = OfflineSource()
    attempts, backoff = recording_backoff()
    channel_id, session_id = uuid4(), uuid4()
    ingest = ChannelIngest(channel_id, "streamer", session_id, source, tmp_path, backoff=backoff)

    await run_until(ingest.run(), lambda: len(attempts) >= 3)

    assert attempts[:3] == [1, 2, 3]
    assert source.calls >= 3
    assert ingest.recorder is None
    assert list_run_dirs(session_dir(tmp_path, channel_id, session_id)) == []


async def test_unexpected_error_does_not_stop_the_loop(tmp_path: Path) -> None:
    attempts, backoff = recording_backoff()
    ingest = ChannelIngest(uuid4(), "streamer", uuid4(), BrokenSource(), tmp_path, backoff=backoff)

    await run_until(ingest.run(), lambda: len(attempts) >= 3)

    assert attempts[:3] == [1, 2, 3]


async def test_cleanup_loop_uses_retention_with_grace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[Path, datetime]] = []

    def fake_cleanup(root: Path, older_than: datetime) -> int:
        calls.append((root, older_than))
        return 0

    monkeypatch.setattr(worker_module, "cleanup", fake_cleanup)
    before = utc_now()

    await run_until(
        run_cleanup_loop(tmp_path, retention_s=300, interval_s=0.01), lambda: len(calls) >= 2
    )

    root, older_than = calls[0]
    expected = before - timedelta(seconds=300 + CLEANUP_GRACE_S)
    assert root == tmp_path
    assert abs((older_than - expected).total_seconds()) < 1


async def test_cleanup_loop_survives_disk_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = 0

    def failing_cleanup(*args: Any) -> int:
        nonlocal calls
        calls += 1
        raise PermissionError("busy")

    monkeypatch.setattr(worker_module, "cleanup", failing_cleanup)

    await run_until(
        run_cleanup_loop(tmp_path, retention_s=300, interval_s=0.01), lambda: calls >= 3
    )
