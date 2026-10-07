import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from spikecut.domain.models import Segment
from spikecut.ingest.buffer import (
    SEGMENT_LIST,
    SegmentEntry,
    anchor_from_run_dir,
    buffer_seconds,
    cleanup,
    list_segments,
    parse_segment_list,
    run_dir,
    session_dir,
    to_segments,
)

T0 = datetime(2026, 9, 25, 18, 0, 0, tzinfo=UTC)


def at(s: float) -> datetime:
    return T0 + timedelta(seconds=s)


def set_mtime(path: Path, when: datetime) -> None:
    ts = when.timestamp()
    os.utime(path, (ts, ts))


def make_run(
    session: Path,
    anchor: datetime,
    spans: list[tuple[float, float]],
    *,
    last_write: datetime | None = None,
) -> Path:
    directory = run_dir(session, anchor)
    directory.mkdir(parents=True)
    lines = []
    for i, (start, end) in enumerate(spans):
        name = f"{i:06d}.ts"
        (directory / name).write_bytes(b"ts")
        lines.append(f"{name},{start:.6f},{end:.6f}\n")
    if spans:
        (directory / SEGMENT_LIST).write_text("".join(lines))
    if last_write is not None:
        set_mtime(directory / SEGMENT_LIST if spans else directory, last_write)
    return directory


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "buffer"


@pytest.fixture
def session(root: Path) -> Path:
    return session_dir(root, uuid4(), uuid4())


def test_session_dir_layout() -> None:
    channel_id, session_id = uuid4(), uuid4()

    path = session_dir(Path("/buffer"), channel_id, session_id)

    assert path == Path("/buffer") / str(channel_id) / str(session_id)


def test_run_dir_roundtrip_keeps_milliseconds() -> None:
    anchor = T0 + timedelta(milliseconds=123)

    path = run_dir(Path("/buffer/s"), anchor)

    assert path.parent == Path("/buffer/s")
    assert anchor_from_run_dir(path) == anchor


def test_parse_complete_lines() -> None:
    text = "000000.ts,0.000000,2.000000\n000001.ts,2.000000,4.040000\n"

    entries = parse_segment_list(text)

    assert entries == [
        SegmentEntry(name="000000.ts", start=0.0, end=2.0),
        SegmentEntry(name="000001.ts", start=2.0, end=4.04),
    ]


def test_parse_skips_incomplete_last_line() -> None:
    text = "000000.ts,0.000000,2.000000\n000001.ts,2.00"

    entries = parse_segment_list(text)

    assert [e.name for e in entries] == ["000000.ts"]


def test_parse_empty_text() -> None:
    assert parse_segment_list("") == []


def test_parse_only_incomplete_line() -> None:
    assert parse_segment_list("000000.ts,0.000000,2.0") == []


def test_parse_skips_blank_lines_and_crlf() -> None:
    text = "\n000000.ts,0.000000,2.000000\r\n\n"

    entries = parse_segment_list(text)

    assert entries == [SegmentEntry(name="000000.ts", start=0.0, end=2.0)]


def test_to_segments_uses_anchor_and_run_dir() -> None:
    entries = [
        SegmentEntry(name="000000.ts", start=0.0, end=2.0),
        SegmentEntry(name="000001.ts", start=2.0, end=3.5),
    ]
    directory = Path("/buffer/s/1790000000000")

    segments = to_segments(entries, directory, T0)

    assert [s.path for s in segments] == [directory / "000000.ts", directory / "000001.ts"]
    assert [s.start for s in segments] == [T0, T0 + timedelta(seconds=2)]
    assert [s.duration for s in segments] == [2.0, 1.5]


def test_to_segments_drops_directory_from_csv_name() -> None:
    entries = [SegmentEntry(name="some/other/dir/000000.ts", start=0.0, end=2.0)]
    directory = Path("/buffer/s/1")

    [segment] = to_segments(entries, directory, T0)

    assert segment.path == directory / "000000.ts"


def test_list_segments_merges_runs_in_time_order(session: Path) -> None:
    make_run(session, at(10), [(0, 2)])
    make_run(session, T0, [(0, 2), (2, 4)])

    segments = list_segments(session)

    assert [s.start for s in segments] == [at(0), at(2), at(10)]


def test_list_segments_skips_deleted_files(session: Path) -> None:
    directory = make_run(session, T0, [(0, 2), (2, 4), (4, 6)])
    (directory / "000001.ts").unlink()

    segments = list_segments(session)

    assert [s.start for s in segments] == [at(0), at(4)]


def test_list_segments_ignores_foreign_entries(session: Path) -> None:
    make_run(session, T0, [(0, 2)])
    make_run(session, at(60), [])  # ffmpeg did not close any segment yet
    (session / "not-a-run").mkdir()
    (session / "stray.txt").write_text("x")

    segments = list_segments(session)

    assert [s.start for s in segments] == [at(0)]


def test_list_segments_missing_session(session: Path) -> None:
    assert list_segments(session) == []


def test_buffer_seconds_ignores_gaps() -> None:
    segments = [
        Segment(path=Path("a.ts"), start=at(0), duration=2.0),
        Segment(path=Path("b.ts"), start=at(30), duration=1.5),
    ]

    assert buffer_seconds(segments) == 3.5
    assert buffer_seconds([]) == 0


def test_cleanup_removes_only_segments_ended_before_cutoff(root: Path, session: Path) -> None:
    older_than = at(4)
    directory = make_run(
        session, T0, [(0, 2), (2, 4), (4, 6)], last_write=older_than + timedelta(minutes=1)
    )

    removed = cleanup(root, older_than)

    assert removed == 1
    assert sorted(p.name for p in directory.glob("*.ts")) == ["000001.ts", "000002.ts"]


def test_cleanup_keeps_active_run_directory(root: Path, session: Path) -> None:
    older_than = at(100)
    directory = make_run(
        session, T0, [(0, 2), (2, 4)], last_write=older_than + timedelta(seconds=1)
    )

    removed = cleanup(root, older_than)

    assert removed == 2
    assert directory.is_dir()
    assert (directory / SEGMENT_LIST).exists()


def test_cleanup_removes_finished_run_and_empty_session(root: Path, session: Path) -> None:
    older_than = at(100)
    make_run(session, T0, [(0, 2), (2, 4)], last_write=older_than - timedelta(seconds=1))

    removed = cleanup(root, older_than)

    assert removed == 2
    assert not session.exists()


def test_cleanup_keeps_session_with_fresh_run(root: Path, session: Path) -> None:
    older_than = at(100)
    old = make_run(session, T0, [(0, 2)], last_write=older_than - timedelta(seconds=1))
    fresh = make_run(session, at(90), [(0, 20)], last_write=older_than + timedelta(seconds=1))

    cleanup(root, older_than)

    assert not old.exists()
    assert fresh.is_dir()
    assert session.is_dir()


def test_cleanup_run_without_csv(root: Path, session: Path) -> None:
    older_than = at(100)
    stale = make_run(session, T0, [], last_write=older_than - timedelta(seconds=1))
    starting = make_run(session, at(99), [], last_write=older_than + timedelta(seconds=1))

    removed = cleanup(root, older_than)

    assert removed == 0
    assert not stale.exists()
    assert starting.is_dir()


def test_cleanup_is_idempotent(root: Path, session: Path) -> None:
    older_than = at(4)
    make_run(session, T0, [(0, 2), (2, 4), (4, 6)], last_write=older_than + timedelta(minutes=1))

    first = cleanup(root, older_than)
    second = cleanup(root, older_than)

    assert (first, second) == (1, 0)


def test_cleanup_missing_root(root: Path) -> None:
    assert cleanup(root, T0) == 0
