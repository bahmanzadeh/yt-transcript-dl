import io
from unittest.mock import MagicMock, patch

import pytest
from yt_dlp.networking import Response
from yt_dlp.networking.exceptions import HTTPError, TransportError
from yt_dlp.utils import DownloadError, ExtractorError

from yt_transcript_dl.models import Failure, Track, select_track
from yt_transcript_dl.provider import YouTube

ID = "abcdefghijk"
URL = "https://www.youtube.com/api/timedtext?signature=synthetic-fixture"


@pytest.fixture
def provider():
    with patch("yt_transcript_dl.provider.YoutubeDL") as constructor:
        client = YouTube(30, 2)
        yield client, constructor.return_value, constructor


def metadata():
    return {
        "id": ID,
        "title": "Example",
        "channel": "Channel",
        "formats": [],
        "http_headers": {"Referer": "https://www.youtube.com/", "X-Example": "old"},
        "automatic_captions": {
            "en-orig": [
                {
                    "ext": "json3",
                    "url": URL,
                    "name": "English (Original)",
                    "http_headers": {"X-Example": "new"},
                }
            ]
        },
    }


def test_metadata_without_media_and_track_headers(provider, caption_bytes):
    adapter, client, constructor = provider
    client.extract_info.return_value = metadata()
    video = adapter.video(ID)
    track = video.tracks[0]
    assert track.kind == "automatic"
    assert track.headers == {"Referer": "https://www.youtube.com/", "X-Example": "new"}
    client.extract_info.assert_called_once_with(
        f"https://www.youtube.com/watch?v={ID}",
        download=False,
        process=False,
    )
    options = constructor.call_args.args[0]
    assert options["ignore_no_formats_error"] and options["skip_download"]
    assert options["cachedir"] is False and options["extractor_retries"] == 0
    response = Response(io.BytesIO(caption_bytes), URL, {})
    client.urlopen.return_value = response
    assert adapter.captions(track)[0].text == "Hello world."
    assert response.closed
    request = client.urlopen.call_args.args[0]
    assert request.headers["X-Example"] == "new"
    client.download.assert_not_called()


def test_wrong_video_identity(provider):
    adapter, client, _ = provider
    client.extract_info.return_value = {**metadata(), "id": "wrong"}
    with pytest.raises(Failure, match="identity"):
        adapter.video(ID)


@pytest.mark.parametrize("translation", ["tlang=en", "tlang=", "%74lang=en"])
def test_translated_tracks_are_excluded_from_discovery_and_selection(provider, translation):
    adapter, client, _ = provider
    native = f"{URL}&lang=fr"
    client.extract_info.return_value = {
        **metadata(),
        "automatic_captions": {
            "fr-orig": [{"ext": "json3", "url": native}],
            "en": [{"ext": "json3", "url": f"{native}&{translation}"}],
        },
    }
    video = adapter.video(ID)
    assert [t.description()["language"] for t in video.tracks] == ["fr-orig"]
    with pytest.raises(Failure, match="No requested captions"):
        select_track(video, ("en",))
    assert select_track(video, ("en", "fr")).url == native


@pytest.mark.parametrize("language", ["en", "en-orig"])
def test_native_format_after_translation_remains_available(provider, language):
    adapter, client, _ = provider
    native = f"{URL}&lang=en"
    client.extract_info.return_value = {
        **metadata(),
        "automatic_captions": {
            language: [
                {"ext": "json3", "url": f"{URL}&lang=fr&tlang=en"},
                {"ext": "json3", "url": native},
            ],
        },
    }
    assert select_track(adapter.video(ID), ("en",)).url == native


@pytest.mark.parametrize("status,expected_calls", [(429, 3), (503, 3), (403, 1), (404, 1)])
def test_http_errors_are_sanitized_bounded_and_closed(provider, status, expected_calls):
    adapter, client, _ = provider
    responses = [Response(io.BytesIO(b""), URL, {}, status=status) for _ in range(expected_calls)]
    client.urlopen.side_effect = [HTTPError(r) for r in responses]
    with patch("yt_transcript_dl.provider.time.sleep") as sleep, pytest.raises(Failure) as caught:
        adapter.captions(Track("en", "English", "human", URL))
    assert client.urlopen.call_count == expected_calls
    assert sleep.call_count == expected_calls - 1
    assert "signature" not in str(caught.value)
    assert all(r.closed for r in responses)


def test_transient_failure_then_success(provider, caption_bytes):
    adapter, client, _ = provider
    client.urlopen.side_effect = [
        TransportError("synthetic transport error"),
        Response(io.BytesIO(caption_bytes), URL, {}),
    ]
    with patch("yt_transcript_dl.provider.time.sleep"):
        assert adapter.captions(Track("en", "English", "human", URL))
    assert client.urlopen.call_count == 2


def test_nested_extraction_error(provider):
    adapter, client, _ = provider
    cause = ExtractorError("private upstream details", expected=True)
    client.extract_info.side_effect = DownloadError(
        "raw details", exc_info=(type(cause), cause, None)
    )
    with pytest.raises(Failure) as caught:
        adapter.video(ID)
    assert caught.value.code == "unavailable"
    assert "details" not in str(caught.value)
    assert client.extract_info.call_count == 1


def test_read_failure_closes_response(provider):
    adapter, client, _ = provider
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.side_effect = TransportError("read failed")
    client.urlopen.return_value = response
    with patch("yt_transcript_dl.provider.time.sleep"), pytest.raises(Failure):
        adapter.captions(Track("en", "English", "human", URL))
    assert response.__exit__.call_count == 3
