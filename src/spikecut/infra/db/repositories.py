from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from spikecut.domain.errors import ClipNotFoundError
from spikecut.domain.models import Channel, Clip, ClipSource, ClipStatus, SessionStatus
from spikecut.infra.db.models import ChannelRow, ClipRow, StreamSessionRow


def _to_channel(row: ChannelRow) -> Channel:
    return Channel(
        id=row.id,
        platform=row.platform,
        login=row.login,
        display_name=row.display_name,
        enabled=row.enabled,
        detector_config=row.detector_config,
        created_at=row.created_at,
    )


def _to_clip(row: ClipRow) -> Clip:
    return Clip(
        id=row.id,
        channel_id=row.channel_id,
        session_id=row.session_id,
        highlight_id=row.highlight_id,
        source=row.source,
        start_at=row.start_at,
        end_at=row.end_at,
        status=row.status,
        storage_key=row.storage_key,
        thumbnail_key=row.thumbnail_key,
        size_bytes=row.size_bytes,
        has_gap=row.has_gap,
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class ChannelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, platform: str, login: str, display_name: str | None = None) -> Channel:
        row = ChannelRow(platform=platform, login=login, display_name=display_name)
        self._session.add(row)
        await self._session.flush()
        return _to_channel(row)

    async def get(self, channel_id: UUID) -> Channel | None:
        row = await self._session.get(ChannelRow, channel_id)
        return _to_channel(row) if row else None

    async def list_all(self) -> list[Channel]:
        rows = await self._session.scalars(
            select(ChannelRow).order_by(ChannelRow.created_at, ChannelRow.id)
        )
        return [_to_channel(r) for r in rows]

    async def get_by_login(self, platform: str, login: str) -> Channel | None:
        row = await self._session.scalar(
            select(ChannelRow).where(ChannelRow.platform == platform, ChannelRow.login == login)
        )
        return _to_channel(row) if row else None


class ClipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        channel_id: UUID,
        session_id: UUID,
        source: ClipSource,
        start_at: datetime,
        end_at: datetime,
        has_gap: bool = False,
        highlight_id: UUID | None = None,
    ) -> Clip:
        row = ClipRow(
            channel_id=channel_id,
            session_id=session_id,
            source=source,
            start_at=start_at,
            end_at=end_at,
            has_gap=has_gap,
            highlight_id=highlight_id,
        )
        self._session.add(row)
        await self._session.flush()
        return _to_clip(row)

    async def get(self, clip_id: UUID) -> Clip | None:
        row = await self._session.get(ClipRow, clip_id)
        return _to_clip(row) if row else None

    async def list_all(
        self,
        channel_id: UUID | None = None,
        status: ClipStatus | None = None,
        limit: int = 50,
    ) -> list[Clip]:
        stmt = select(ClipRow)

        if channel_id is not None:
            stmt = stmt.where(ClipRow.channel_id == channel_id)
        if status is not None:
            stmt = stmt.where(ClipRow.status == status)

        stmt = stmt.order_by(ClipRow.created_at.desc(), ClipRow.id.desc()).limit(limit)

        rows = await self._session.scalars(stmt)
        return [_to_clip(r) for r in rows]

    async def set_status(self, clip_id: UUID, status: ClipStatus, error: str | None = None) -> None:
        row = await self._session.get(ClipRow, clip_id)
        if row is None:
            raise ClipNotFoundError(clip_id)
        row.status = status
        row.error = error
        await self._session.flush()

    async def mark_ready(
        self,
        clip_id: UUID,
        *,
        storage_key: str,
        thumbnail_key: str,
        size_bytes: int,
    ) -> None:
        row = await self._session.get(ClipRow, clip_id)
        if row is None:
            raise ClipNotFoundError(clip_id)
        row.status = ClipStatus.READY
        row.storage_key = storage_key
        row.thumbnail_key = thumbnail_key
        row.size_bytes = size_bytes
        row.error = None
        await self._session.flush()


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def start(self, channel_id: UUID, started_at: datetime) -> UUID:
        await self._session.execute(
            update(StreamSessionRow)
            .where(
                StreamSessionRow.channel_id == channel_id,
                StreamSessionRow.status == SessionStatus.LIVE,
            )
            .values(status=SessionStatus.INTERRUPTED, ended_at=started_at)
        )
        row = StreamSessionRow(
            channel_id=channel_id, started_at=started_at, status=SessionStatus.LIVE
        )
        self._session.add(row)
        await self._session.flush()
        return row.id

    async def end(
        self, session_id: UUID, ended_at: datetime, status: SessionStatus = SessionStatus.ENDED
    ) -> None:
        await self._session.execute(
            update(StreamSessionRow)
            .where(
                StreamSessionRow.id == session_id,
                StreamSessionRow.status == SessionStatus.LIVE,
            )
            .values(status=status, ended_at=ended_at)
        )

    async def get_live(self, channel_id: UUID) -> UUID | None:
        session_id: UUID | None = await self._session.scalar(
            select(StreamSessionRow.id).where(
                StreamSessionRow.channel_id == channel_id,
                StreamSessionRow.status == SessionStatus.LIVE,
            )
        )
        return session_id
