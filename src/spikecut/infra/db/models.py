from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from spikecut.domain.models import ClipSource, ClipStatus, SessionStatus


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class ChannelRow(Base):
    __tablename__ = "channels"
    __table_args__ = (UniqueConstraint("platform", "login"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    platform: Mapped[str] = mapped_column(String(32))
    login: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str | None] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(default=True)
    detector_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def _str_enum(enum_cls: type[StrEnum]) -> Enum:
    return Enum(
        enum_cls,
        native_enum=False,
        create_constraint=True,
        length=16,
        values_callable=lambda e: [m.value for m in e],
    )


class StreamSessionRow(Base):
    __tablename__ = "stream_sessions"
    __table_args__ = (
        Index(
            "uq_stream_sessions_one_live",
            "channel_id",
            unique=True,
            postgresql_where=text("status = 'live'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    channel_id: Mapped[UUID] = mapped_column(ForeignKey("channels.id", ondelete="RESTRICT"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[SessionStatus] = mapped_column(
        _str_enum(SessionStatus), default=SessionStatus.LIVE
    )


class HighlightRow(Base):
    __tablename__ = "highlights"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("stream_sessions.id", ondelete="CASCADE"), index=True
    )
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    peak_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    score: Mapped[float]
    signals: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClipRow(Base):
    __tablename__ = "clips"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    channel_id: Mapped[UUID] = mapped_column(ForeignKey("channels.id", ondelete="RESTRICT"))
    session_id: Mapped[UUID] = mapped_column(ForeignKey("stream_sessions.id", ondelete="RESTRICT"))
    highlight_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("highlights.id", ondelete="SET NULL"), unique=True
    )
    source: Mapped[ClipSource] = mapped_column(_str_enum(ClipSource))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[ClipStatus] = mapped_column(_str_enum(ClipStatus), default=ClipStatus.PENDING)
    storage_key: Mapped[str | None] = mapped_column(String(256))
    thumbnail_key: Mapped[str | None] = mapped_column(String(256))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    has_gap: Mapped[bool] = mapped_column(default=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
