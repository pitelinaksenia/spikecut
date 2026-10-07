from abc import ABC, abstractmethod


class VideoSource(ABC):
    @abstractmethod
    async def stream_url(self, login: str) -> str | None:
        """Return a playable HLS URL, or None if the channel is offline."""
