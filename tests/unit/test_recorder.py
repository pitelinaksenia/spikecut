from datetime import UTC, datetime
from pathlib import Path

import pytest

from spikecut.ingest.buffer import SEGMENT_LIST
from spikecut.ingest.recorder import SEGMENT_PATTERN, Recorder, segment_args

T0 = datetime(2026, 9, 25, 18, 0, 0, tzinfo=UTC)


def test_segment_args_input_options_before_input() -> None:
    args = segment_args("http://host/stream.m3u8", Path("/run"))

    assert args.index("-rw_timeout") < args.index("-i")
    assert args[args.index("-i") + 1] == "http://host/stream.m3u8"


def test_segment_args_copy_without_reencoding() -> None:
    args = segment_args("url", Path("/run"))

    assert args[args.index("-c") + 1] == "copy"
    assert args[args.index("-f") + 1] == "segment"


def test_segment_args_outputs_inside_run_dir() -> None:
    run = Path("/buffer/s/1790000000000")

    args = segment_args("url", run)

    assert args[args.index("-segment_list") + 1] == str(run / SEGMENT_LIST)
    assert args[args.index("-segment_list_type") + 1] == "csv"
    assert args[-1] == str(run / SEGMENT_PATTERN)


def test_segment_args_segment_time() -> None:
    args = segment_args("url", Path("/run"), segment_time=4)

    assert args[args.index("-segment_time") + 1] == "4"


@pytest.fixture
def recorder(tmp_path: Path) -> Recorder:
    rec = Recorder("url", tmp_path)
    rec.run_dir = tmp_path
    rec.anchor = T0
    return rec


def append(path: Path, text: str) -> None:
    with path.open("a", newline="") as f:
        f.write(text)


def test_read_new_entries_without_csv(recorder: Recorder) -> None:
    recorder._read_new_entries()

    assert recorder.segments_written == 0
    assert recorder.last_segment_at is None


def test_read_new_entries_waits_for_complete_line(recorder: Recorder, tmp_path: Path) -> None:
    csv = tmp_path / SEGMENT_LIST

    append(csv, "000000.ts,0.000000,2.0")
    recorder._read_new_entries()
    assert recorder.segments_written == 0

    append(csv, "00000\n")
    recorder._read_new_entries()
    assert recorder.segments_written == 1
    assert recorder.last_segment_at is not None


def test_read_new_entries_counts_each_line_once(recorder: Recorder, tmp_path: Path) -> None:
    csv = tmp_path / SEGMENT_LIST

    append(csv, "000000.ts,0.0,2.0\n")
    recorder._read_new_entries()
    recorder._read_new_entries()
    append(csv, "000001.ts,2.0,4.0\n000002.ts,4.0,6.0\n")
    recorder._read_new_entries()

    assert recorder.segments_written == 3


async def test_wait_before_start_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        await Recorder("url", tmp_path).wait()


async def test_stop_before_start_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        await Recorder("url", tmp_path).stop()
