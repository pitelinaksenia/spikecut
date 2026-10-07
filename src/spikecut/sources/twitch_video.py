import asyncio

import structlog
from streamlink import Streamlink
from streamlink.exceptions import StreamlinkError

from spikecut.sources.base import VideoSource

log = structlog.get_logger(__name__)


class TwitchVideoSource(VideoSource):
    def __init__(self, quality: str = "720p") -> None:
        self._quality = quality
        self._session = Streamlink()

    async def stream_url(self, login: str) -> str | None:
        return await asyncio.to_thread(self._resolve, login)

    def _resolve(self, login: str) -> str | None:
        try:
            streams = self._session.streams(f"https://twitch.tv/{login}")
        except StreamlinkError as e:
            log.warning("twitch_resolve_failed", login=login, error=str(e))
            return None
        stream = streams.get(self._quality) or streams.get("best")
        if stream is None:
            return None  # channel offline
        url: str = stream.url
        return url
