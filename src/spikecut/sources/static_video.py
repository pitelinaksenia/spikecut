from spikecut.sources.base import VideoSource


class StaticVideoSource(VideoSource):
    def __init__(self, url: str) -> None:
        self._url = url

    async def stream_url(self, login: str) -> str | None:
        return self._url
