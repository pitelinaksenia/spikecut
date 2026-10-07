from types import SimpleNamespace
from typing import Any

import pytest
from streamlink.exceptions import PluginError

from spikecut.sources.static_video import StaticVideoSource
from spikecut.sources.twitch_video import TwitchVideoSource


async def test_static_source_returns_url_for_any_login() -> None:
    source = StaticVideoSource("http://mediamtx:8888/demo/index.m3u8")

    assert await source.stream_url("a") == "http://mediamtx:8888/demo/index.m3u8"
    assert await source.stream_url("b") == "http://mediamtx:8888/demo/index.m3u8"


def fake_stream(url: str) -> SimpleNamespace:
    return SimpleNamespace(url=url)


@pytest.fixture
def twitch() -> TwitchVideoSource:
    return TwitchVideoSource(quality="720p")


def set_streams(
    monkeypatch: pytest.MonkeyPatch, source: TwitchVideoSource, result: dict[str, Any] | Exception
) -> list[str]:
    """Replace the network call; return the list of URLs streamlink was asked for."""
    calls: list[str] = []

    def streams(url: str) -> dict[str, Any]:
        calls.append(url)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(source._session, "streams", streams)
    return calls


async def test_twitch_returns_requested_quality(
    monkeypatch: pytest.MonkeyPatch, twitch: TwitchVideoSource
) -> None:
    calls = set_streams(
        monkeypatch,
        twitch,
        {"720p": fake_stream("http://hls/720"), "best": fake_stream("http://hls/best")},
    )

    assert await twitch.stream_url("streamer") == "http://hls/720"
    assert calls == ["https://twitch.tv/streamer"]


async def test_twitch_falls_back_to_best(
    monkeypatch: pytest.MonkeyPatch, twitch: TwitchVideoSource
) -> None:
    set_streams(monkeypatch, twitch, {"best": fake_stream("http://hls/best")})

    assert await twitch.stream_url("streamer") == "http://hls/best"


async def test_twitch_offline_channel_returns_none(
    monkeypatch: pytest.MonkeyPatch, twitch: TwitchVideoSource
) -> None:
    set_streams(monkeypatch, twitch, {})

    assert await twitch.stream_url("streamer") is None


async def test_twitch_streamlink_error_returns_none(
    monkeypatch: pytest.MonkeyPatch, twitch: TwitchVideoSource
) -> None:
    set_streams(monkeypatch, twitch, PluginError("Twitch API error"))

    assert await twitch.stream_url("streamer") is None
