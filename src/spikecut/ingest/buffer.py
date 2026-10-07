import contextlib
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from spikecut.domain.models import Segment

SEGMENT_LIST = "segments.csv"


def session_dir(buffer_dir: Path, channel_id: UUID, session_id: UUID) -> Path:
    return buffer_dir / str(channel_id) / str(session_id)


def run_dir(session_dir: Path, anchor: datetime) -> Path:
    return session_dir / str(int(anchor.timestamp() * 1000))


def anchor_from_run_dir(path: Path) -> datetime:
    return datetime.fromtimestamp(int(path.name) / 1000, tz=UTC)


@dataclass(frozen=True)
class SegmentEntry:
    name: str
    start: float
    end: float


def parse_segment_list(text: str) -> list[SegmentEntry]:
    """Parse ffmpeg csv segment list (name,start,end).

    A trailing line without a newline may be half-written by ffmpeg and is skipped.
    """
    entries: list[SegmentEntry] = []
    for line in text.split("\n")[:-1]:
        line = line.strip()
        if not line:
            continue
        name, start, end = line.rsplit(",", 2)
        entries.append(SegmentEntry(name=name, start=float(start), end=float(end)))
    return entries


def to_segments(entries: list[SegmentEntry], directory: Path, anchor: datetime) -> list[Segment]:
    return [
        Segment(
            path=directory / Path(e.name).name,
            start=anchor + timedelta(seconds=e.start),
            duration=e.end - e.start,
        )
        for e in entries
    ]


def list_run_dirs(session_dir: Path) -> list[Path]:
    if not session_dir.is_dir():
        return []

    dirs = [p for p in session_dir.iterdir() if p.is_dir() and p.name.isdigit()]
    return sorted(dirs, key=lambda p: int(p.name))


def read_run(directory: Path) -> list[Segment]:
    try:
        text = (directory / SEGMENT_LIST).read_text()
    except FileNotFoundError:
        return []

    anchor = anchor_from_run_dir(directory)
    entries = parse_segment_list(text)
    return [s for s in to_segments(entries, directory, anchor) if s.path.exists()]


def list_segments(session_dir: Path) -> list[Segment]:
    segments = [s for directory in list_run_dirs(session_dir) for s in read_run(directory)]
    return sorted(segments, key=lambda s: s.start)


def buffer_seconds(segments: list[Segment]) -> float:
    return sum(s.duration for s in segments)


def cleanup(root: Path, older_than: datetime) -> int:
    if not root.is_dir():
        return 0
    removed = 0
    for channel in _subdirs(root):
        for session in _subdirs(channel):
            for directory in list_run_dirs(session):
                removed += _cleanup_run(directory, older_than)
            _remove_if_empty(session)
    return removed


def _cleanup_run(directory: Path, older_than: datetime) -> int:
    """Удалить старые сегменты одного запуска, а если запуск давно закончен — всю папку."""
    csv_path = directory / SEGMENT_LIST
    try:
        text = csv_path.read_text()
    except FileNotFoundError:
        text = ""  # ffmpeg так и не закрыл ни одного сегмента

    segments = to_segments(parse_segment_list(text), directory, anchor_from_run_dir(directory))
    removed = sum(1 for s in segments if s.end < older_than and _unlink(s.path))

    # Последняя запись давно → ffmpeg в эту папку больше не пишет, её можно снести целиком.
    last_write = _mtime(csv_path) or _mtime(directory)
    if last_write is not None and last_write < older_than:
        shutil.rmtree(directory, ignore_errors=True)
    return removed


def _subdirs(path: Path) -> list[Path]:
    return [p for p in path.iterdir() if p.is_dir()]


def _mtime(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except FileNotFoundError:
        return None


def _unlink(path: Path) -> bool:
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except PermissionError:
        return False
    return True


def _remove_if_empty(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.rmdir()
