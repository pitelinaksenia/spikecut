from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from spikecut.domain.errors import SegmentsExpiredError, SegmentsMissingError, SegmentsNotReadyError
from spikecut.domain.models import ClipPlan, ClipRequest, Segment
from spikecut.domain.planner import plan_clip

T0 = datetime(2026, 9, 25, 18, 0, 0, tzinfo=UTC)


def at(s: float) -> datetime:
    return T0 + timedelta(seconds=s)


def seg(start: float, end: float) -> Segment:
    return Segment(path=Path(f"{start}.ts"), start=at(start), duration=end - start)


def req(start: float, end: float) -> ClipRequest:
    return ClipRequest(channel_id=uuid4(), start=at(start), end=at(end))


def test_empty_buffer_raises_not_ready() -> None:
    with pytest.raises(SegmentsNotReadyError) as exc_info:
        plan_clip([], req(0, 5))

    assert exc_info.value.available_s == 0


def test_start_before_buffer_raises_expired() -> None:
    with pytest.raises(SegmentsExpiredError) as exc_info:
        plan_clip([seg(10, 20)], req(5, 10))

        assert exc_info.value.available_s == 10


def test_end_after_buffer_raises_not_ready() -> None:
    with pytest.raises(SegmentsNotReadyError) as exc_info:
        plan_clip([seg(0, 10)], req(5, 15))

    assert exc_info.value.available_s == 10


def test_plans_clip_inside_continuous_buffer() -> None:
    segments = [seg(0, 10), seg(10, 20), seg(20, 30), seg(30, 40)]

    plan = plan_clip(segments, req(12, 25))

    assert plan == ClipPlan(
        segments=[segments[1], segments[2]],
        offset=2,
        duration=13,
        has_gap=False,
    )


def test_segment_touching_clip_start_is_not_selected() -> None:
    segments = [seg(0, 10), seg(10, 20)]
    plan = plan_clip(segments, req(10, 15))

    assert plan.segments == [segments[1]]


def test_segment_touching_clip_end_is_not_selected() -> None:
    segments = [seg(0, 10), seg(10, 20)]

    plan = plan_clip(segments, req(5, 10))

    assert plan.segments == [segments[0]]


def test_offset_is_distance_from_first_selected_segment() -> None:
    segments = [seg(0, 10), seg(10, 20)]
    plan = plan_clip(segments, req(13, 18))
    assert plan.offset == 3


@pytest.mark.parametrize(
    "gap, expected",
    [
        (0, False),
        (1.5, False),
        (1.6, True),
    ],
)
def test_gap_detection(gap, expected) -> None:
    segments = [seg(0, 10), seg(10 + gap, 20)]
    plan = plan_clip(segments, req(5, 15))
    assert plan.has_gap is expected


def test_clip_entirely_inside_gap() -> None:
    segments = [seg(0, 10), seg(20, 30)]
    with pytest.raises(SegmentsMissingError):
        plan_clip(segments, req(12, 18))
