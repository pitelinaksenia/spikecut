from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID


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
