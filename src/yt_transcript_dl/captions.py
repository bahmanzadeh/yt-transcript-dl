"""JSON3 normalization and deterministic, lossless readable rendering."""

import json
import re
import unicodedata

from .models import Cue, Failure, Track, Video


def clean_text(value: str) -> str:
    # Remove terminal controls, retaining whitespace and ordinary Unicode text.
    value = "".join(c for c in value if c.isspace() or unicodedata.category(c) not in {"Cc", "Cs"})
    return re.sub(r"\s+", " ", value).strip()


def parse_json3(data: bytes) -> list[Cue]:
    try:
        payload = json.loads(data)
        if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
            raise ValueError
        cues: list[Cue] = []
        for event in payload["events"]:
            if not isinstance(event, dict):
                raise ValueError
            segments = event.get("segs", [])
            if not isinstance(segments, list):
                raise ValueError
            texts = []
            for segment in segments:
                if not isinstance(segment, dict) or not isinstance(segment.get("utf8"), str):
                    raise ValueError
                texts.append(segment["utf8"])
            text = clean_text("".join(texts))
            if not text:
                continue  # Window definitions and newline-only events carry no speech.
            start = event.get("tStartMs")
            if type(start) is not int or start < 0:
                raise ValueError
            duration = event.get("dDurationMs")
            if duration is not None and (type(duration) is not int or duration < 0):
                raise ValueError
            cues.append(Cue(start, text))
        if not cues:
            raise ValueError
        return cues
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise Failure("invalid_captions", "Caption data is empty or malformed JSON3.") from None


def timestamp(milliseconds: int) -> str:
    seconds = milliseconds // 1000
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def render(video: Video, track: Track, cues: list[Cue], *, timestamps: bool) -> bytes:
    if not cues:
        raise Failure("invalid_captions", "No caption text to render.")
    paragraphs: list[tuple[int, str]] = []
    start = cues[0].start_ms
    words: list[str] = []
    for cue in cues:
        if words and cue.start_ms - start >= 30_000:
            paragraphs.append((start, " ".join(words)))
            start, words = cue.start_ms, []
        words.append(cue.text)
    paragraphs.append((start, " ".join(words)))
    if clean_text(" ".join(text for _, text in paragraphs)) != clean_text(
        " ".join(cue.text for cue in cues)
    ):
        raise Failure("invalid_captions", "Caption text fidelity check failed.")
    header = [f"Title: {clean_text(video.title)}", f"Source: https://youtu.be/{video.video_id}"]
    if video.channel:
        header.append(f"Channel: {clean_text(video.channel)}")
    header.append(f"Captions: {track.language} ({track.kind})")
    body = "\n\n".join(
        (f"[{timestamp(start)}] " if timestamps else "") + text for start, text in paragraphs
    )
    return ("\n".join(header) + "\n\n" + body + "\n").encode("utf-8")
