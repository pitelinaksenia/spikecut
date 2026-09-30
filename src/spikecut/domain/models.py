from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID


class ClipStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ClipSource(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"


class SessionStatus(StrEnum):
    LIVE = "live"
    ENDED = "ended"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class Segment:
    path: Path
    start: datetime
    duration: float

    @property
    def end(self) -> datetime:
        return self.start + timedelta(seconds=self.duration)


@dataclass(frozen=True)
class ClipRequest:
    channel_id: UUID
    start: datetime
    end: datetime

    @property
    def duration(self) -> float:
        return (self.end - self.start).total_seconds()


@dataclass(frozen=True)
class ClipPlan:
    segments: list[Segment]
    offset: float
    duration: float
    has_gap: bool


@dataclass(frozen=True)
class Channel:
    id: UUID
    platform: str
    login: str
    display_name: str | None
    enabled: bool
    detector_config: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class Clip:
    id: UUID
    channel_id: UUID
    session_id: UUID
    highlight_id: UUID | None
    source: ClipSource
    start_at: datetime
    end_at: datetime
    status: ClipStatus
    storage_key: str | None
    thumbnail_key: str | None
    size_bytes: int | None
    has_gap: bool
    error: str | None
    created_at: datetime
    updated_at: datetime
