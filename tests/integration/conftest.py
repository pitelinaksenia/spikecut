import asyncio
import os
import subprocess
from asyncio.subprocess import Process
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer

from spikecut.config import get_settings
from spikecut.domain.models import Channel, SessionStatus
from spikecut.infra import ffmpeg
from spikecut.infra.db.models import HighlightRow, StreamSessionRow
from spikecut.infra.db.repositories import ChannelRepository, ClipRepository
from spikecut.ingest import recorder as recorder_module

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def no_orphans(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Process]]:
    """Record every spawned process and check none is left running after the test."""
    procs: list[Process] = []
    original = asyncio.create_subprocess_exec

    async def tracking(*args: Any, **kwargs: Any) -> Process:
        proc = await original(*args, **kwargs)
        procs.append(proc)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", tracking)
    yield procs
    assert all(p.returncode is not None for p in procs), "ffmpeg process left running"


@pytest.fixture(scope="session")
def source_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """5 s test video with a keyframe every second, so segments can be cut every 2 s."""
    path = tmp_path_factory.mktemp("src") / "source.mp4"
    subprocess.run(
        [
            ffmpeg.FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=5:size=320x240:rate=25",
            "-c:v", "libx264", "-preset", "ultrafast", "-g", "25",
            str(path),
        ],
        check=True,
    )  # fmt: skip
    return path


@pytest.fixture
def endless_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ffmpeg loop the source in real time, like a live stream that never ends."""
    original = recorder_module.segment_args

    def looping(input_url: str, run_dir: Path, segment_time: int = 2) -> list[str]:
        return ["-re", "-stream_loop", "-1", *original(input_url, run_dir, segment_time)]

    monkeypatch.setattr(recorder_module, "segment_args", looping)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer("postgres:16", driver="asyncpg") as pg:
        url = pg.get_connection_url()

        os.environ["DATABASE_URL"] = url
        os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
        os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost:9000")
        os.environ.setdefault("S3_ACCESS_KEY", "test")
        os.environ.setdefault("S3_SECRET_KEY", "test")
        get_settings.cache_clear()

        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        yield url


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Each test runs inside a transaction that is rolled back afterwards."""
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


@pytest.fixture
def channels(session: AsyncSession) -> ChannelRepository:
    return ChannelRepository(session)


@pytest.fixture
def clips(session: AsyncSession) -> ClipRepository:
    return ClipRepository(session)


@pytest.fixture
async def channel(channels: ChannelRepository) -> Channel:
    return await channels.create("twitch", "streamer", "Streamer")


@pytest.fixture
async def stream_session(session: AsyncSession, channel: Channel) -> StreamSessionRow:
    row = StreamSessionRow(
        channel_id=channel.id,
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        status=SessionStatus.ENDED,
    )
    session.add(row)
    await session.flush()
    return row


@pytest.fixture
def make_highlight(session: AsyncSession, stream_session: StreamSessionRow):
    async def make() -> HighlightRow:
        t = datetime(2026, 1, 1, 12, tzinfo=UTC)
        row = HighlightRow(
            session_id=stream_session.id,
            window_start=t,
            peak_at=t,
            window_end=t,
            score=1.0,
            signals={},
        )
        session.add(row)
        await session.flush()
        return row

    return make
