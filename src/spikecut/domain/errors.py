from uuid import UUID


class DomainError(Exception):
    """Base class for domain errors."""


class ClipNotFoundError(DomainError):
    """Clip with the given id does not exist."""

    def __init__(self, clip_id: UUID) -> None:
        super().__init__(f"Clip {clip_id} not found")
        self.clip_id = clip_id


class OutOfBufferError(DomainError):
    """Requested range is not fully available in the buffer."""

    def __init__(self, message: str, available_s: float) -> None:
        super().__init__(message)
        self.available_s = available_s


class SegmentsExpiredError(OutOfBufferError):
    """Start of the range was already removed from the buffer. Permanent."""


class SegmentsNotReadyError(OutOfBufferError):
    """End of the range is not recorded yet. Retry later."""


class SegmentsMissingError(OutOfBufferError):
    """Range falls into a gap, no footage was recorded. Permanent."""
