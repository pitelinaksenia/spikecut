from spikecut.domain.errors import SegmentsExpiredError, SegmentsNotReadyError
from spikecut.domain.models import ClipPlan, ClipRequest, Segment

GAP_TOLERANCE_S = 1.5


def plan_clip(segments: list[Segment], req: ClipRequest) -> ClipPlan:
    if not segments:
        raise SegmentsNotReadyError("buffer is empty", available_s=0)

    available_s = (segments[-1].end - segments[0].start).total_seconds()

    if req.start < segments[0].start:
        raise SegmentsExpiredError("clip start is no longer in buffer", available_s)
    if req.end > segments[-1].end:
        raise SegmentsNotReadyError("clip end is not recorded yet", available_s)

    selected = [s for s in segments if s.end > req.start and s.start < req.end]
    offset = (req.start - selected[0].start).total_seconds()
    duration = req.duration

    has_gap = False

    for i in range(0, len(selected) - 1):
        if (selected[i + 1].start - selected[i].end).total_seconds() > GAP_TOLERANCE_S:
            has_gap = True
            break

    clip_plan = ClipPlan(segments=selected, offset=offset, duration=duration, has_gap=has_gap)
    return clip_plan
