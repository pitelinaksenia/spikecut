from datetime import UTC, datetime
from pathlib import Path

SEGMENT_SUFFIX = ".ts"


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_segment_name(ts: datetime) -> str:
    return f"{int(ts.timestamp())}{SEGMENT_SUFFIX}"


def from_segment_name(name: str) -> datetime:
    stem = Path(name).stem
    return datetime.fromtimestamp(int(stem), tz=UTC)
