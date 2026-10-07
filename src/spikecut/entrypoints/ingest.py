from spikecut.config import Settings
from spikecut.sources.base import VideoSource
from spikecut.sources.static_video import StaticVideoSource
from spikecut.sources.twitch_video import TwitchVideoSource


def make_video_source(settings: Settings) -> VideoSource:
    if settings.demo_stream_url:
        return StaticVideoSource(settings.demo_stream_url)
    return TwitchVideoSource(settings.video_quality)
