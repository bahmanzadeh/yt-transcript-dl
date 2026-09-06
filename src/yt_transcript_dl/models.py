"""Validated domain values; upstream payloads stay in the adapter."""

from dataclasses import dataclass, field
from typing import Literal


class Failure(Exception):
    """An expected failure whose message is safe to show and persist."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class Track:
    language: str
    name: str
    kind: Literal["human", "automatic"]
    url: str = field(repr=False)
    headers: dict[str, str] = field(default_factory=dict, repr=False)

    def description(self) -> dict[str, str]:
        return {"language": self.language, "name": self.name, "kind": self.kind}


@dataclass(frozen=True)
class Video:
    video_id: str
    title: str
    channel: str
    tracks: tuple[Track, ...]


@dataclass(frozen=True)
class Cue:
    start_ms: int
    text: str


@dataclass(frozen=True)
class Error:
    code: str
    message: str


@dataclass
class Result:
    video_id: str
    status: Literal["downloaded", "unchanged", "listed", "failed"]
    language: str | None = None
    path: str | None = None
    error: Error | None = None
    tracks: list[dict[str, str]] | None = None


def select_track(video: Video, languages: tuple[str, ...]) -> Track:
    for language in languages:
        candidates = [
            t
            for t in video.tracks
            if t.language.lower() == language
            or ("-" not in language and t.language.lower().startswith(language + "-"))
        ]
        if candidates:
            return min(
                candidates,
                key=lambda t: (
                    t.kind != "human",
                    t.language.lower() != language,
                    not t.language.lower().endswith("-orig"),
                    t.language.lower(),
                ),
            )
    available = ", ".join(sorted({t.language for t in video.tracks})) or "none"
    raise Failure(
        "missing_captions",
        f"No requested captions ({', '.join(languages)}). Available JSON3 tracks: {available}.",
    )
