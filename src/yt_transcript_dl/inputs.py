"""Normalize explicit video inputs before any network or output work."""

import re
from collections.abc import Iterable
from pathlib import Path
from typing import TextIO
from urllib.parse import parse_qs, urlsplit

VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
LANGUAGE = re.compile(r"[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]+)*\Z")
HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}


def video_id(value: str) -> str:
    value = value.strip()
    if VIDEO_ID.fullmatch(value):
        return value
    try:
        url = urlsplit(value)
        if url.scheme not in {"https", "http"} or url.username or url.password or url.port:
            raise ValueError
        parts = url.path.strip("/").split("/")
        if url.hostname == "youtu.be" and len(parts) == 1:
            candidate = parts[0]
        elif url.hostname in HOSTS and url.path == "/watch":
            values = parse_qs(url.query).get("v", [])
            if len(values) != 1:
                raise ValueError
            candidate = values[0]
        elif (
            url.hostname in HOSTS
            and len(parts) == 2
            and parts[0]
            in {
                "shorts",
                "live",
                "embed",
            }
        ):
            candidate = parts[1]
        else:
            raise ValueError
        if not VIDEO_ID.fullmatch(candidate):
            raise ValueError
        return candidate
    except ValueError:
        raise ValueError("Expected a YouTube video URL or an 11-character video ID.") from None


def read_inputs(values: list[str], files: list[str], stdin: TextIO) -> list[str]:
    """Positionals first, then files; preserve first occurrence across all inputs."""
    found: dict[str, None] = {}

    def collect(lines: Iterable[str], source: str, *, comments: bool) -> None:
        for number, line in enumerate(lines, 1):
            line = line.strip().removeprefix("\ufeff").strip()
            if comments and (not line or line.startswith("#")):
                continue
            try:
                found[video_id(line)] = None
            except ValueError as exc:
                raise ValueError(f"{source}, item {number}: {exc}") from None

    collect(values, "arguments", comments=False)
    if files.count("-") > 1:
        raise ValueError("Use --input-file - at most once.")
    for index, file in enumerate(files, 1):
        try:
            if file == "-":
                collect(stdin, "stdin", comments=True)
            else:
                with Path(file).expanduser().open(encoding="utf-8-sig") as handle:
                    collect(handle, f"input file {index}", comments=True)
        except (OSError, UnicodeError):
            raise ValueError(f"Input file {index} must be readable UTF-8 text.") from None
    if not found:
        raise ValueError("Provide a video URL/ID or --input-file FILE. See --help for examples.")
    return list(found)
