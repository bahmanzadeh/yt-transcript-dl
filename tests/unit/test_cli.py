import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from yt_transcript_dl.cli import app
from yt_transcript_dl.models import Cue, Failure, Track, Video

IDS = ["abcdefghijk", "lmnopqrstuv"]
runner = CliRunner()


class FakeYouTube:
    titles = {IDS[0]: "First video title", IDS[1]: "Second video title"}
    calls = []
    failures = set()
    caption_calls = 0

    def __init__(self, timeout, retries):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def video(self, identity):
        self.calls.append(identity)
        if identity in self.failures:
            raise Failure("unavailable", "Video is unavailable.")
        track = Track("en", "English", "human", "https://youtube.com/api/timedtext")
        return Video(identity, self.titles.get(identity, "Title"), "Example channel", (track,))

    def captions(self, track):
        type(self).caption_calls += 1
        return [Cue(0, "Hello world."), Cue(31_000, "Next paragraph.")]


@pytest.fixture
def fake():
    FakeYouTube.calls = []
    FakeYouTube.failures = set()
    FakeYouTube.caption_calls = 0
    with patch("yt_transcript_dl.service.YouTube", FakeYouTube):
        yield FakeYouTube


@pytest.mark.parametrize("args", [["--help"], ["-h"], ["--version"]])
def test_help_version_no_provider(args):
    with patch("yt_transcript_dl.service.YouTube") as provider:
        result = runner.invoke(app, args, env={"NO_COLOR": "1", "TERM": "dumb"})
    assert result.exit_code == 0, result.output
    assert "ytt-dl" in result.output
    assert "\x1b[" not in result.output
    provider.assert_not_called()
    if args != ["--version"]:
        for option in (
            "--input-file",
            "--output-dir",
            "--language",
            "--timestamps",
            "--list-languages",
            "--overwrite",
            "--timeout",
            "--retries",
            "--json",
        ):
            assert option in result.output
        assert "Examples" in result.output and "~/ytt-dl" in result.output
        assert "--install-completion" not in result.output


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["invalid"],
        ["--unknown"],
        [IDS[0], "--timeout", "nan"],
        [IDS[0], "--timeout", "inf"],
        [IDS[0], "--timeout", "0"],
        [IDS[0], "--retries", "-1"],
        [IDS[0], "--language", "../../en"],
        [IDS[0], "--list-languages", "--timestamps"],
        [IDS[0], "--list-languages", "--output-dir", "somewhere"],
    ],
)
def test_invalid_arguments_never_initialize_provider(args):
    with patch("yt_transcript_dl.service.YouTube") as provider:
        result = runner.invoke(app, args)
    assert result.exit_code == 2, result.output
    provider.assert_not_called()


def test_default_output_and_safe_reruns(tmp_path, monkeypatch, fake):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    args = [*IDS, "--json"]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    data = json.loads(first.stdout)
    assert data["counts"]["downloaded"] == 2
    assert data["output_dir"].startswith(str(tmp_path / "ytt-dl"))
    assert data["output_dir"].endswith("/text-files")
    assert fake.calls == IDS
    second = runner.invoke(app, args)
    assert second.exit_code == 0, second.output
    assert json.loads(second.stdout)["counts"]["unchanged"] == 2
    assert fake.caption_calls == 4  # Current captions were compared, not a stale checksum.
    changed = runner.invoke(app, [*args, "--timestamps"])
    assert changed.exit_code == 1
    assert json.loads(changed.stdout)["counts"]["failed"] == 2
    replaced = runner.invoke(app, [*args, "--timestamps", "--overwrite"])
    assert replaced.exit_code == 0
    assert json.loads(replaced.stdout)["counts"]["downloaded"] == 2


def test_failed_first_video_does_not_prevent_second_output(tmp_path, fake):
    fake.failures = {IDS[0]}
    result = runner.invoke(app, [*IDS, "--output-dir", str(tmp_path), "--json"])
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["counts"] == {"downloaded": 1, "unchanged": 0, "listed": 0, "failed": 1}
    assert f"/{IDS[0]}--" in data["output_dir"]
    assert len(list(tmp_path.rglob("*.txt"))) == 1
    assert "ERROR" in result.stderr


def test_list_languages_creates_nothing(tmp_path, monkeypatch, fake):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    result = runner.invoke(app, [*IDS, "--list-languages", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["output_dir"] is None
    assert data["results"][0]["tracks"] == [{"language": "en", "name": "English", "kind": "human"}]
    assert not list(tmp_path.iterdir())
    assert fake.caption_calls == 0


def test_stdin_mixed_inputs_and_separator(tmp_path, fake):
    result = runner.invoke(
        app,
        ["-o", str(tmp_path), "-i", "-", "--json", "--", "-VIDEO_ID01"],
        input=IDS[0] + "\n",
    )
    assert result.exit_code == 0, result.output
    assert fake.calls == ["-VIDEO_ID01", IDS[0]]


def test_interrupt_preserves_completed_files(tmp_path, fake, monkeypatch):
    original = fake.video

    def interrupt(self, identity):
        if identity == IDS[1]:
            raise KeyboardInterrupt
        return original(self, identity)

    monkeypatch.setattr(fake, "video", interrupt)
    result = runner.invoke(app, [*IDS, "-o", str(tmp_path), "--json"])
    assert result.exit_code == 130
    assert json.loads(result.stdout)["counts"]["downloaded"] == 1
    assert len(list(tmp_path.rglob("*.txt"))) == 1


@pytest.mark.parametrize("after_publication", [False, True])
def test_initialization_interrupt_allows_same_command_rerun(tmp_path, fake, after_publication):
    from yt_transcript_dl.storage import Directory

    publish = Directory.publish_directory

    def interrupt(directory, source, name):
        if after_publication:
            publish(directory, source, name)
        raise KeyboardInterrupt

    args = [IDS[0], "-o", str(tmp_path), "--json"]
    with patch.object(Directory, "publish_directory", interrupt):
        interrupted = runner.invoke(app, args)
    assert interrupted.exit_code == 130, interrupted.output
    summary = json.loads(interrupted.stdout)
    assert summary["interrupted"] is True
    assert summary["error"] is None
    assert summary["results"] == []
    rerun = runner.invoke(app, args)
    assert rerun.exit_code == 0, rerun.output
    assert json.loads(rerun.stdout)["counts"]["downloaded"] == 1
    assert len(list(tmp_path.rglob("*.txt"))) == 1


def test_existing_output_file_fails_before_network(tmp_path):
    file = tmp_path / "not-a-folder"
    file.write_text("unrelated")
    with patch("yt_transcript_dl.service.YouTube") as provider:
        result = runner.invoke(app, [IDS[0], "--output-dir", str(file)])
    assert result.exit_code == 2
    provider.assert_not_called()
