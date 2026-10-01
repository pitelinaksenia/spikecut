from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from spikecut.domain.errors import ClipNotFoundError
from spikecut.domain.models import Channel, ClipSource, ClipStatus, SessionStatus
from spikecut.infra.db.models import ChannelRow, ClipRow, StreamSessionRow
from spikecut.infra.db.repositories import ChannelRepository, ClipRepository

MSK = timezone(timedelta(hours=3))


@pytest.fixture
def make_clip(clips: ClipRepository, channel: Channel, stream_session: StreamSessionRow):
    async def make(*, channel_id: UUID | None = None, highlight_id: UUID | None = None):
        start = datetime(2026, 1, 1, 15, tzinfo=MSK)
        return await clips.create(
            channel_id=channel_id or channel.id,
            session_id=stream_session.id,
            source=ClipSource.AUTO,
            start_at=start,
            end_at=start + timedelta(seconds=30),
            highlight_id=highlight_id,
        )

    return make


async def set_created_at(session: AsyncSession, model, id_: UUID, value: datetime) -> None:
    await session.execute(update(model).where(model.id == id_).values(created_at=value))


# --- channels ---


async def test_channel_roundtrip(session: AsyncSession, channels: ChannelRepository):
    created = await channels.create("twitch", "foo", "Foo")
    session.expunge_all()

    got = await channels.get(created.id)

    assert got == created
    assert got.enabled is True
    assert got.detector_config == {}
    assert got.created_at.tzinfo is not None


async def test_channel_get_missing(channels: ChannelRepository):
    assert await channels.get(uuid4()) is None


async def test_channel_duplicate_platform_login(channels: ChannelRepository):
    await channels.create("twitch", "foo")
    await channels.create("youtube", "foo")

    with pytest.raises(IntegrityError):
        await channels.create("twitch", "foo")


async def test_channel_list_all_order(session: AsyncSession, channels: ChannelRepository):
    t = datetime(2026, 1, 1, tzinfo=UTC)
    a = await channels.create("twitch", "a")
    b = await channels.create("twitch", "b")
    c = await channels.create("twitch", "c")
    await set_created_at(session, ChannelRow, a.id, t + timedelta(seconds=2))
    await set_created_at(session, ChannelRow, b.id, t)
    await set_created_at(session, ChannelRow, c.id, t + timedelta(seconds=1))
    session.expunge_all()

    assert [ch.id for ch in await channels.list_all()] == [b.id, c.id, a.id]


# --- clips ---


async def test_clip_roundtrip(
    session: AsyncSession, clips: ClipRepository, make_clip, make_highlight
):
    highlight = await make_highlight()
    created = await make_clip(highlight_id=highlight.id)
    session.expunge_all()

    got = await clips.get(created.id)

    assert got == created
    assert type(got.source) is ClipSource
    assert type(got.status) is ClipStatus
    assert got.status == ClipStatus.PENDING
    assert got.start_at == datetime(2026, 1, 1, 15, tzinfo=MSK)
    assert got.start_at.tzinfo is not None
    assert got.highlight_id == highlight.id
    assert (got.storage_key, got.thumbnail_key, got.size_bytes, got.error) == (None,) * 4


async def test_clip_list_all_filters(
    session: AsyncSession, channels: ChannelRepository, clips: ClipRepository, make_clip, channel
):
    other = await channels.create("twitch", "other")
    mine_pending = await make_clip()
    mine_failed = await make_clip()
    other_failed = await make_clip(channel_id=other.id)
    await clips.set_status(mine_failed.id, ClipStatus.FAILED)
    await clips.set_status(other_failed.id, ClipStatus.FAILED)

    def ids(result):
        return {c.id for c in result}

    assert ids(await clips.list_all(channel_id=channel.id)) == {mine_pending.id, mine_failed.id}
    assert ids(await clips.list_all(status=ClipStatus.FAILED)) == {mine_failed.id, other_failed.id}
    assert ids(await clips.list_all(channel_id=channel.id, status=ClipStatus.FAILED)) == {
        mine_failed.id
    }


async def test_clip_list_all_order_and_limit(
    session: AsyncSession, clips: ClipRepository, make_clip
):
    t = datetime(2026, 1, 1, tzinfo=UTC)
    old = await make_clip()
    tie_a = await make_clip()
    tie_b = await make_clip()
    await set_created_at(session, ClipRow, old.id, t)
    await set_created_at(session, ClipRow, tie_a.id, t + timedelta(seconds=1))
    await set_created_at(session, ClipRow, tie_b.id, t + timedelta(seconds=1))
    session.expunge_all()

    newest_first = sorted([tie_a.id, tie_b.id], reverse=True)  # tie broken by id desc

    assert [c.id for c in await clips.list_all()] == [*newest_first, old.id]
    assert [c.id for c in await clips.list_all(limit=2)] == newest_first


async def test_set_status(session: AsyncSession, clips: ClipRepository, make_clip):
    clip = await make_clip()

    await clips.set_status(clip.id, ClipStatus.FAILED, error="boom")
    session.expunge_all()
    got = await clips.get(clip.id)
    assert (got.status, got.error) == (ClipStatus.FAILED, "boom")

    await clips.set_status(clip.id, ClipStatus.PROCESSING)
    session.expunge_all()
    got = await clips.get(clip.id)
    assert (got.status, got.error) == (ClipStatus.PROCESSING, None)


async def test_get_after_update_in_same_session(clips: ClipRepository, make_clip):
    clip = await make_clip()
    await clips.get(clip.id)

    await clips.set_status(clip.id, ClipStatus.PROCESSING)
    got = await clips.get(clip.id)

    assert got.status == ClipStatus.PROCESSING
    assert got.updated_at is not None


async def test_mark_ready(session: AsyncSession, clips: ClipRepository, make_clip):
    clip = await make_clip()
    await clips.set_status(clip.id, ClipStatus.FAILED, error="boom")
    five_gb = 5 * 1024**3

    await clips.mark_ready(clip.id, storage_key="c.mp4", thumbnail_key="c.jpg", size_bytes=five_gb)
    session.expunge_all()
    got = await clips.get(clip.id)

    assert got.status == ClipStatus.READY
    assert (got.storage_key, got.thumbnail_key, got.size_bytes) == ("c.mp4", "c.jpg", five_gb)
    assert got.error is None


async def test_update_missing_clip_raises(clips: ClipRepository):
    missing = uuid4()

    with pytest.raises(ClipNotFoundError) as exc:
        await clips.set_status(missing, ClipStatus.FAILED)
    assert exc.value.clip_id == missing

    with pytest.raises(ClipNotFoundError) as exc:
        await clips.mark_ready(missing, storage_key="k", thumbnail_key="t", size_bytes=1)
    assert exc.value.clip_id == missing


# --- constraints ---


async def test_duplicate_highlight_id(make_clip, make_highlight):
    await make_clip()
    await make_clip()

    highlight = await make_highlight()
    await make_clip(highlight_id=highlight.id)
    with pytest.raises(IntegrityError):
        await make_clip(highlight_id=highlight.id)


async def test_one_live_session_per_channel(
    session: AsyncSession, channels: ChannelRepository, channel: Channel
):
    other = await channels.create("twitch", "other")
    t = datetime(2026, 1, 1, tzinfo=UTC)

    def live(channel_id: UUID) -> StreamSessionRow:
        return StreamSessionRow(channel_id=channel_id, started_at=t, status=SessionStatus.LIVE)

    session.add_all(
        [
            live(channel.id),
            live(other.id),
            StreamSessionRow(channel_id=channel.id, started_at=t, status=SessionStatus.ENDED),
        ]
    )
    await session.flush()

    session.add(live(channel.id))
    with pytest.raises(IntegrityError):
        await session.flush()
