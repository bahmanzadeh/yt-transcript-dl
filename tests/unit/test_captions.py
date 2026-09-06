import json

import pytest

from yt_transcript_dl.captions import clean_text, parse_json3, render, timestamp
from yt_transcript_dl.models import Cue, Failure, Track, Video, select_track


def track(language="en", kind="human"):
    return Track(language, language, kind, "https://www.youtube.com/api/timedtext")


def test_caption_append_events_and_genuine_repetition():
    events = [
        {"tStartMs": 0, "wWinId": 1},
        {"tStartMs": 0, "segs": [{"utf8": "Hello "}, {"utf8": "世界."}]},
        {"tStartMs": 1, "aAppend": 1, "segs": [{"utf8": "\n"}]},
        {"tStartMs": 2, "aAppend": 1, "segs": [{"utf8": "Yes, yes."}]},
        {"tStartMs": 3, "segs": [{"utf8": "Yes, yes."}]},
    ]
    cues = parse_json3(json.dumps({"events": events}).encode())
    assert [c.text for c in cues] == ["Hello 世界.", "Yes, yes.", "Yes, yes."]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [],
        {"events": []},
        {"events": [None]},
        {"events": [{"segs": None}]},
        {"events": [{"segs": [{"utf8": "text"}]}]},
        {"events": [{"tStartMs": -1, "segs": [{"utf8": "text"}]}]},
        {"events": [{"tStartMs": True, "segs": [{"utf8": "text"}]}]},
        {"events": [{"tStartMs": 0, "dDurationMs": -1, "segs": [{"utf8": "text"}]}]},
        {"events": [{"tStartMs": 0, "segs": [{"utf8": 42}]}]},
    ],
)
def test_malformed_json3(payload):
    with pytest.raises(Failure, match="malformed"):
        parse_json3(json.dumps(payload).encode())


def test_readable_and_timestamped_text_preserve_words():
    video = Video("abcdefghijk", "A title\nwith a newline", "Example channel", ())
    cues = [Cue(0, "First line."), Cue(29_999, "Same paragraph."), Cue(3_600_000, "An hour later.")]
    plain = render(video, track(), cues, timestamps=False).decode()
    timed = render(video, track(), cues, timestamps=True).decode()
    assert "Title: A title with a newline\n" in plain
    assert "Source: https://youtu.be/abcdefghijk\n" in plain
    assert "First line. Same paragraph.\n\nAn hour later.\n" in plain
    assert "[01:00:00] An hour later." in timed
    assert "[00:00:00]" not in plain
    assert timestamp(86_400_000) == "24:00:00"
    assert clean_text("a\t b\x00\x1b") == "a b"


def test_language_and_caption_preference():
    auto = track("en", "automatic")
    manual = track("en-US")
    french = track("fr", "automatic")
    video = Video("abcdefghijk", "Title", "", (auto, manual, french))
    assert select_track(video, ("en",)) == manual
    assert select_track(video, ("fr", "en")) == french
    assert select_track(video, ("de", "en")) == manual
    with pytest.raises(Failure, match="Available JSON3 tracks"):
        select_track(video, ("de",))
    original = track("en-orig", "automatic")
    assert select_track(Video("abcdefghijk", "Title", "", (original,)), ("en",)) == original
