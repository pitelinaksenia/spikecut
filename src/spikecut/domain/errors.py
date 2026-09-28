class DomainError(Exception):
    """Base class for domain errors."""


class OutOfBufferError(DomainError):
    """Requested range is not fully available in the buffer."""

    def __init__(self, message: str, available_s: float) -> None:
        super().__init__(message)
        self.available_s = available_s


class SegmentsExpiredError(OutOfBufferError):
    """Start of the range was already removed from the buffer. Permanent."""


class SegmentsNotReadyError(OutOfBufferError):
    """End of the range is not recorded yet. Retry later."""
