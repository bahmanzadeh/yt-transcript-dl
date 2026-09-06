from io import StringIO

import pytest

from yt_transcript_dl.inputs import read_inputs, video_id

ID = "abcdefghijk"


@pytest.mark.parametrize(
    "value",
    [
        ID,
        f" https://youtu.be/{ID}?si=example ",
        f"http://youtube.com/watch?v={ID}",
        f"https://www.youtube.com/watch?v={ID}&list=example&t=60",
        f"https://m.youtube.com/shorts/{ID}",
        f"https://music.youtube.com/watch?v={ID}",
        f"https://youtube.com/live/{ID}",
        f"https://youtube.com/embed/{ID}",
    ],
)
def test_video_urls(value):
    assert video_id(value) == ID


@pytest.mark.parametrize(
    "value",
    [
        "",
        "too-short",
        "https://youtube.com/playlist?list=example",
        "https://youtube.com/@channel",
        f"https://youtube.com.evil.example/watch?v={ID}",
        f"https://example.com/{ID}",
        f"https://youtu.be/{ID}/extra",
        f"file:///watch?v={ID}",
        f"https://user:password@youtube.com/watch?v={ID}",
        f"https://youtube.com:443/watch?v={ID}",
        f"https://youtube.com/watch?v={ID}&v={ID}",
        f"https://youtube.com/watch?v={ID}%2F",
        "https://[malformed",
        "videos.txt",
    ],
)
def test_rejects_non_video_inputs(value):
    with pytest.raises(ValueError):
        video_id(value)


def test_files_order_comments_bom_and_duplicates(tmp_path):
    first = tmp_path / "one.txt"
    first.write_bytes(b"\xef\xbb\xbf # comment\r\n\r\n lmnopqrstuv \r\nabcdefghijk")
    second = tmp_path / "two.txt"
    second.write_text("https://youtu.be/wxyz0123456\n")
    assert read_inputs([ID], [str(first), str(second)], StringIO()) == [
        ID,
        "lmnopqrstuv",
        "wxyz0123456",
    ]


def test_stdin_and_invalid_location():
    assert read_inputs([], ["-"], StringIO(ID)) == [ID]
    with pytest.raises(ValueError, match="at most once"):
        read_inputs([], ["-", "-"], StringIO(ID))
    with pytest.raises(ValueError, match="stdin, item 2"):
        read_inputs([], ["-"], StringIO(ID + "\nbad-input"))


def test_missing_invalid_and_empty_files(tmp_path):
    path = tmp_path / "list.txt"
    with pytest.raises(ValueError, match="readable UTF-8"):
        read_inputs([], [str(path)], StringIO())
    path.write_bytes(b"\xff")
    with pytest.raises(ValueError, match="readable UTF-8"):
        read_inputs([], [str(path)], StringIO())
    with pytest.raises(ValueError, match="Provide a video"):
        read_inputs([], ["-"], StringIO("# empty\n"))
