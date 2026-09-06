"""The only boundary to yt-dlp and YouTube. Never expose signed caption URLs."""

import os
import random
import time
from collections.abc import Callable
from typing import TypeVar
from urllib.parse import parse_qs, urlsplit

from yt_dlp import YoutubeDL
from yt_dlp.networking import Request
from yt_dlp.networking.exceptions import (
    CertificateVerifyError,
    HTTPError,
    RequestError,
    TransportError,
)
from yt_dlp.utils import DownloadError, ExtractorError

from .captions import clean_text, parse_json3
from .inputs import LANGUAGE
from .models import Cue, Failure, Track, Video

T = TypeVar("T")
MAX_CAPTION_BYTES = 20 * 1024 * 1024


class QuietLogger:
    """Upstream messages may contain signed URLs; translate exceptions instead."""

    def debug(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        pass

    def error(self, message: str) -> None:
        pass


def classify(exc: Exception) -> tuple[Failure, bool]:
    current = exc
    for _ in range(8):
        if isinstance(current, HTTPError):
            status = current.status
            current.close()
            if status in {429, 500, 502, 503, 504}:
                return Failure(
                    "network_error", f"YouTube returned HTTP {status}; retry later."
                ), True
            if status == 403:
                return Failure("access_denied", "YouTube denied access to these captions."), False
            if status == 404:
                return Failure("unavailable", "The video or caption track is unavailable."), False
            return Failure("network_error", f"YouTube returned HTTP {status}."), False
        if isinstance(current, CertificateVerifyError):
            return Failure("network_error", "TLS certificate verification failed."), False
        if isinstance(current, (TransportError, TimeoutError, ConnectionError)):
            return Failure("network_error", "A YouTube network request failed or timed out."), True
        cause = getattr(current, "cause", None)
        info = getattr(current, "exc_info", None)
        if cause is None and info:
            cause = info[1]
        if not isinstance(cause, Exception) or cause is current:
            break
        current = cause
    # Inspect only for categorization. Never return upstream text or URLs.
    message = str(current).lower()
    if "sign in" in message or "bot" in message or "429" in message:
        return Failure(
            "access_denied", "YouTube blocked this request; retry later from your network."
        ), False
    if isinstance(current, ExtractorError) and current.expected:
        return Failure(
            "unavailable", "Video is unavailable, restricted, or has no accessible captions."
        ), False
    return Failure(
        "extraction_failed",
        "YouTube extraction failed. Check connectivity, Deno, and the installed yt-dlp version.",
    ), False


class YouTube:
    def __init__(self, timeout: float, retries: int):
        self.retries = retries
        # Direct embedding skips config parsing, but the constructor loads plugins.
        os.environ["YTDLP_NO_PLUGINS"] = "1"
        self.client = YoutubeDL(
            {
                "quiet": True,
                "no_warnings": True,
                "logger": QuietLogger(),
                "noplaylist": True,
                "skip_download": True,
                "ignore_no_formats_error": True,
                "cachedir": False,
                "cookiefile": None,
                "socket_timeout": timeout,
                "extractor_retries": 0,
                "retries": 0,
                "remote_components": [],
                "extractor_args": {"youtube": {"skip": ["hls", "dash", "translated_subs"]}},
            }
        )

    def __enter__(self) -> "YouTube":
        self.client.__enter__()
        return self

    def __exit__(self, *args) -> None:
        self.client.__exit__(*args)

    def _request(self, operation: Callable[[], T]) -> T:
        for attempt in range(self.retries + 1):
            try:
                return operation()
            except (
                DownloadError,
                ExtractorError,
                RequestError,
                TimeoutError,
                ConnectionError,
            ) as exc:
                error, retry = classify(exc)
                if not retry or attempt == self.retries:
                    raise error from None
                time.sleep(min(2 ** min(attempt, 5) + random.uniform(0, 0.25), 60))
        raise AssertionError("unreachable")

    def video(self, identity: str) -> Video:
        info = self._request(
            lambda: self.client.extract_info(
                f"https://www.youtube.com/watch?v={identity}",
                download=False,
                process=False,
            )
        )
        if (
            not isinstance(info, dict)
            or info.get("id") != identity
            or info.get("_type", "video") != "video"
        ):
            raise Failure("invalid_metadata", "YouTube returned an unexpected video identity.")
        title = info.get("title")
        channel = info.get("channel") or info.get("uploader") or ""
        if not isinstance(title, str) or not clean_text(title) or not isinstance(channel, str):
            raise Failure("invalid_metadata", "YouTube returned invalid title/channel metadata.")
        tracks: list[Track] = []
        for key, kind in (("subtitles", "human"), ("automatic_captions", "automatic")):
            available = info.get(key) or {}
            if not isinstance(available, dict):
                raise Failure("invalid_metadata", "YouTube returned invalid caption metadata.")
            for language, formats in available.items():
                if not isinstance(language, str) or not LANGUAGE.fullmatch(language):
                    continue  # Includes live_chat, which is not a caption track.
                if not isinstance(formats, list):
                    raise Failure("invalid_metadata", "YouTube returned invalid caption formats.")
                for form in formats:
                    if not isinstance(form, dict) or form.get("ext") != "json3":
                        continue
                    url = form.get("url")
                    if not isinstance(url, str):
                        continue
                    try:
                        parsed = urlsplit(url)
                        host = parsed.hostname or ""
                        if (
                            parsed.scheme != "https"
                            or parsed.username
                            or parsed.password
                            or parsed.port
                        ):
                            raise ValueError
                        if not any(
                            host == base or host.endswith("." + base)
                            for base in (
                                "youtube.com",
                                "googlevideo.com",
                            )
                        ):
                            raise ValueError
                    except ValueError:
                        raise Failure(
                            "invalid_metadata", "Unexpected caption URL origin."
                        ) from None
                    # yt-dlp can still expose automatic translations when skipping them.
                    if "tlang" in parse_qs(parsed.query, keep_blank_values=True):
                        continue
                    headers: dict[str, str] = {}
                    for source in (info, form):
                        supplied = source.get("http_headers") or {}
                        if not isinstance(supplied, dict) or not all(
                            isinstance(k, str) and isinstance(v, str) for k, v in supplied.items()
                        ):
                            raise Failure("invalid_metadata", "Invalid caption request headers.")
                        headers.update(supplied)
                    name = form.get("name") or language
                    tracks.append(Track(language, clean_text(str(name)), kind, url, headers))
                    break
        return Video(identity, clean_text(title), clean_text(channel), tuple(tracks))

    def captions(self, track: Track) -> list[Cue]:
        def fetch() -> bytes:
            with self.client.urlopen(Request(track.url, headers=track.headers)) as response:
                data = response.read(MAX_CAPTION_BYTES + 1)
                if len(data) > MAX_CAPTION_BYTES:
                    raise Failure("invalid_captions", "Caption response exceeds the 20 MiB limit.")
                return data

        return parse_json3(self._request(fetch))
