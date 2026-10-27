import asyncio
import contextlib
import signal
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from spikecut.config import Settings, get_settings
from spikecut.domain.models import Channel
from spikecut.infra.db.repositories import ChannelRepository, SessionRepository
from spikecut.infra.db.session import create_engine, create_sessionmaker
from spikecut.ingest.worker import ChannelIngest, run_cleanup_loop
from spikecut.logging import configure_logging
from spikecut.sources.base import VideoSource
from spikecut.sources.static_video import StaticVideoSource
from spikecut.sources.twitch_video import TwitchVideoSource
from spikecut.time import utc_now

log = structlog.get_logger(__name__)

PLATFORM = "twitch"


def make_video_source(settings: Settings) -> VideoSource:
    if settings.demo_stream_url:
        return StaticVideoSource(settings.demo_stream_url)
    return TwitchVideoSource(settings.video_quality)


async def open_session(
    sessionmaker: async_sessionmaker[AsyncSession], login: str
) -> tuple[Channel, UUID]:
    async with sessionmaker() as db, db.begin():
        channels = ChannelRepository(db)
        channel = await channels.get_by_login(PLATFORM, login)
        if channel is None:
            channel = await channels.create(PLATFORM, login)
            log.info("channel_created", channel_id=str(channel.id), login=login)
        session_id = await SessionRepository(db).start(channel.id, utc_now())

    log.info("session_started", channel_id=str(channel.id), session_id=str(session_id))
    return channel, session_id


async def run_ingest(
    settings: Settings, channel: Channel, session_id: UUID, source: VideoSource
) -> None:
    ingest = ChannelIngest(
        channel.id,
        channel.login,
        session_id,
        source,
        settings.buffer_dir,
        settings.segment_duration_s,
    )
    async with asyncio.TaskGroup() as tg:
        tg.create_task(ingest.run(), name=f"ingest:{channel.login}")
        tg.create_task(
            run_cleanup_loop(settings.buffer_dir, settings.buffer_retention_s),
            name="buffer-cleanup",
        )


async def close_session(sessionmaker: async_sessionmaker[AsyncSession], session_id: UUID) -> None:
    try:
        async with sessionmaker() as db, db.begin():
            await SessionRepository(db).end(session_id, utc_now())
    except Exception:
        log.exception("session_close_failed", session_id=str(session_id))
    else:
        log.info("session_ended", session_id=str(session_id))


def install_shutdown_handler() -> None:
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    assert task is not None

    def shutdown() -> None:
        log.info("shutdown_requested", signal="SIGTERM")
        loop.remove_signal_handler(signal.SIGTERM)
        task.cancel()

    with contextlib.suppress(NotImplementedError):
        loop.add_signal_handler(signal.SIGTERM, shutdown)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    install_shutdown_handler()
    engine = create_engine(str(settings.database_url))
    sessionmaker = create_sessionmaker(engine)
    try:
        channel, session_id = await open_session(sessionmaker, settings.ingest_channel)
        try:
            await run_ingest(settings, channel, session_id, make_video_source(settings))
        finally:
            await close_session(sessionmaker, session_id)
    finally:
        await engine.dispose()


def run() -> None:
    with contextlib.suppress(asyncio.CancelledError, KeyboardInterrupt):
        asyncio.run(main())


if __name__ == "__main__":
    run()
