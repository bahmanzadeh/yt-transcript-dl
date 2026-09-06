import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from yt_transcript_dl.models import Failure, Track, Video
from yt_transcript_dl.storage import Batch, Directory, open_batch, slug

IDS = ["abcdefghijk", "lmnopqrstuv"]
TRACK = Track("en", "English", "human", "https://www.youtube.com/api/timedtext")
VIDEO = Video(IDS[0], "An introduction to Python", "Example", (TRACK,))


def test_interrupted_initial_manifest_does_not_block_rerun(tmp_path, monkeypatch):
    final = tmp_path / f"{slug(VIDEO.title)}--{IDS[0]}"

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(Batch, "save", interrupt)
        with pytest.raises(KeyboardInterrupt), open_batch(tmp_path, [IDS[0]], VIDEO.title):
            pytest.fail("initial manifest publication was not interrupted")
    assert not final.exists()
    with open_batch(tmp_path, [IDS[0]], VIDEO.title) as batch:
        assert batch.path == final
        result = batch.write(VIDEO, TRACK, b"recovered", overwrite=False)
        assert Path(result.path).read_bytes() == b"recovered"


@pytest.mark.parametrize("after_publication", [False, True])
def test_interrupted_publication_reuses_only_complete_final_batch(
    tmp_path, monkeypatch, after_publication
):
    publish = Directory.publish_directory
    final = tmp_path / f"{slug(VIDEO.title)}--{IDS[0]}"

    def interrupt(directory, source, name):
        assert json.loads((tmp_path / source / "manifest.json").read_text())["video_ids"] == [
            IDS[0]
        ]
        if after_publication:
            publish(directory, source, name)
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(Directory, "publish_directory", interrupt)
        with pytest.raises(KeyboardInterrupt), open_batch(tmp_path, [IDS[0]], VIDEO.title):
            pytest.fail("publication was not interrupted")
    assert final.exists() is after_publication
    stages = list(tmp_path.glob(".ytt-dl-init-*"))
    original_stages = {p.name: (p / "manifest.json").read_bytes() for p in stages}
    with open_batch(tmp_path, [IDS[0]], VIDEO.title) as batch:
        assert batch.path == final
        assert batch.manifest["video_ids"] == [IDS[0]]
    assert {p.name: (p / "manifest.json").read_bytes() for p in stages} == original_stages
    assert len(list(tmp_path.glob(".ytt-dl-init-*"))) == len(stages)


def test_parent_sync_failure_after_publication_preserves_complete_batch(tmp_path, monkeypatch):
    sync = os.fsync
    published = False
    publish = Directory.publish_directory

    def remember_publication(directory, source, name):
        nonlocal published
        publish(directory, source, name)
        published = True

    def fail_parent_sync(fd):
        if published:
            raise OSError(errno.EIO, "synthetic synchronization failure")
        sync(fd)

    with monkeypatch.context() as patch:
        patch.setattr(Directory, "publish_directory", remember_publication)
        patch.setattr(os, "fsync", fail_parent_sync)
        with pytest.raises(OSError), open_batch(tmp_path, [IDS[0]], VIDEO.title):
            pytest.fail("parent synchronization did not fail")
    with open_batch(tmp_path, [IDS[0]], VIDEO.title) as batch:
        assert batch.manifest["video_ids"] == [IDS[0]]
        assert (batch.path / "text-files").is_dir()
    assert not list(tmp_path.glob(".ytt-dl-init-*"))


@pytest.mark.parametrize("kind", ["empty", "populated", "file", "symlink", "dangling"])
def test_publication_preserves_racing_destination(tmp_path, monkeypatch, kind):
    final = tmp_path / f"{slug(VIDEO.title)}--{IDS[0]}"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_bytes(b"outside data")
    publish = Directory.publish_directory
    prior = None

    def collide(directory, source, name):
        nonlocal prior
        if kind in {"empty", "populated"}:
            final.mkdir()
            if kind == "populated":
                (final / "keep.txt").write_bytes(b"unrelated data")
        elif kind == "file":
            final.write_bytes(b"unrelated data")
        else:
            final.symlink_to(outside if kind == "symlink" else tmp_path / "absent")
        prior = final.lstat()
        publish(directory, source, name)

    monkeypatch.setattr(Directory, "publish_directory", collide)
    with pytest.raises(Failure) as caught, open_batch(tmp_path, [IDS[0]], VIDEO.title):
        pytest.fail("foreign destination was replaced")
    assert caught.value.code == "output_conflict"
    assert (final.lstat().st_ino, final.lstat().st_mode) == (prior.st_ino, prior.st_mode)
    if kind == "file":
        assert final.read_bytes() == b"unrelated data"
    elif kind == "populated":
        assert (final / "keep.txt").read_bytes() == b"unrelated data"
    elif kind == "empty":
        assert not list(final.iterdir())
    else:
        assert final.readlink() == (outside if kind == "symlink" else tmp_path / "absent")
    assert (outside / "keep.txt").read_bytes() == b"outside data"


def test_preexisting_manifestless_folder_is_not_adopted(tmp_path):
    final = tmp_path / f"{slug(VIDEO.title)}--{IDS[0]}"
    final.mkdir()
    before = final.stat()
    with pytest.raises(Failure, match="occupied"), open_batch(tmp_path, [IDS[0]], VIDEO.title):
        pytest.fail("unidentified folder was adopted")
    assert final.stat().st_ino == before.st_ino
    assert not list(final.iterdir())


@pytest.mark.parametrize(
    "platform,symbol,flags", [("darwin", "renameatx_np", 4), ("linux", "renameat2", 1)]
)
def test_native_exclusive_rename_arguments(tmp_path, monkeypatch, platform, symbol, flags):
    import yt_transcript_dl.storage as storage

    native = MagicMock(return_value=0)
    library = MagicMock()
    setattr(library, symbol, native)
    constructor = MagicMock(return_value=library)
    monkeypatch.setattr(storage.sys, "platform", platform)
    monkeypatch.setattr(ctypes, "CDLL", constructor)
    directory = Directory(tmp_path)
    try:
        directory.publish_directory("prepared-世界", "final-世界")
        constructor.assert_called_once_with(None, use_errno=True)
        native.assert_called_once_with(
            directory.fd, "prepared-世界".encode(), directory.fd, "final-世界".encode(), flags
        )
        assert native.argtypes == [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        assert native.restype is ctypes.c_int
    finally:
        directory.close()


@pytest.mark.parametrize("reason", ["missing_symbol", errno.ENOSYS, errno.EINVAL, errno.ENOTSUP])
def test_unsupported_publication_does_not_fall_back(tmp_path, monkeypatch, reason):
    import yt_transcript_dl.storage as storage

    native = MagicMock(return_value=-1)
    library = MagicMock(renameatx_np=native, renameat2=native)
    if reason == "missing_symbol":
        library = object()
    else:
        monkeypatch.setattr(ctypes, "get_errno", lambda: reason)
    monkeypatch.setattr(ctypes, "CDLL", lambda *args, **kwargs: library)
    fallback = MagicMock(side_effect=AssertionError("ordinary rename must not be used"))
    monkeypatch.setattr(storage.os, "rename", fallback)
    with pytest.raises(Failure) as caught, open_batch(tmp_path, [IDS[0]], VIDEO.title):
        pytest.fail("unsupported publication succeeded")
    assert caught.value.code == "unsupported_output"
    assert not (tmp_path / f"{slug(VIDEO.title)}--{IDS[0]}").exists()
    fallback.assert_not_called()


def test_batch_name_rerun_and_title_change(tmp_path):
    with open_batch(tmp_path, IDS, VIDEO.title) as batch:
        path = batch.path
        assert path.name.startswith("an-introduct--")
        assert len(path.name.split("--")[0]) == 12
        result = batch.write(VIDEO, TRACK, b"original\n", overwrite=False)
        filename = result.path
        assert result.status == "downloaded"
    with open_batch(tmp_path, IDS, "A changed title") as batch:
        assert batch.path == path
        assert batch.write(VIDEO, TRACK, b"original\n", overwrite=False).status == "unchanged"
        assert batch.write(VIDEO, TRACK, b"original\n", overwrite=False).path == filename
    with open_batch(tmp_path, IDS[::-1], "Another video") as other:
        assert other.path != path


def test_single_id_with_double_hyphen_reuses_folder(tmp_path):
    identity = "abc--defghi"
    with open_batch(tmp_path, [identity], "first title") as batch:
        first = batch.path
    with open_batch(tmp_path, [identity], "second title") as batch:
        assert batch.path == first


def test_changed_files_require_overwrite_and_preserve_checksum(tmp_path):
    with open_batch(tmp_path, IDS, VIDEO.title) as batch:
        result = batch.write(VIDEO, TRACK, b"original", overwrite=False)
        path = Path(result.path)
        path.write_bytes(b"edited by user")
        with pytest.raises(Failure, match="--overwrite"):
            batch.write(VIDEO, TRACK, b"updated upstream", overwrite=False)
        assert path.read_bytes() == b"edited by user"
        stored = json.loads((batch.path / "manifest.json").read_text())
        assert stored["files"][f"{IDS[0]}.en"]["sha256"] == hashlib.sha256(b"original").hexdigest()
        assert batch.write(VIDEO, TRACK, b"updated upstream", overwrite=True).status == "downloaded"
        assert path.read_bytes() == b"updated upstream"


def test_recover_after_file_publication_before_manifest_commit(tmp_path, monkeypatch):
    original_record = Batch.record
    with open_batch(tmp_path, IDS, VIDEO.title) as batch:
        monkeypatch.setattr(
            Batch, "record", lambda *args: (_ for _ in ()).throw(KeyboardInterrupt())
        )
        with pytest.raises(KeyboardInterrupt):
            batch.write(VIDEO, TRACK, b"complete file", overwrite=False)
        folder = batch.path
    monkeypatch.setattr(Batch, "record", original_record)
    with open_batch(tmp_path, IDS, "changed title") as batch:
        assert batch.path == folder
        assert batch.write(VIDEO, TRACK, b"complete file", overwrite=False).status == "unchanged"


def test_lock_blocks_second_writer_and_is_released(tmp_path):
    with (
        open_batch(tmp_path, IDS, VIDEO.title),
        pytest.raises(Failure, match="Another ytt-dl"),
        open_batch(tmp_path, IDS, "changed title"),
    ):
        pytest.fail("overlapping writer admitted")
    with open_batch(tmp_path, IDS, VIDEO.title):
        pass


@pytest.mark.parametrize(
    "bad_path",
    [
        "../escape--abcdefghijk.en.txt",
        "/tmp/escape--abcdefghijk.en.txt",
        "text-files/../../escape--abcdefghijk.en.txt",
        "text-files/unrelated.txt",
    ],
)
def test_rejects_manifest_path_injection(tmp_path, bad_path):
    with open_batch(tmp_path, IDS, VIDEO.title) as batch:
        batch.write(VIDEO, TRACK, b"original", overwrite=False)
        path = batch.path / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["files"][f"{IDS[0]}.en"]["path"] = bad_path
    path.write_text(json.dumps(manifest))
    with pytest.raises(Failure, match="malformed"), open_batch(tmp_path, IDS, VIDEO.title):
        pass


def test_symlink_and_nonfile_destinations_are_never_followed(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"private")
    with open_batch(tmp_path / "output", IDS, VIDEO.title) as batch:
        name = f"{slug(VIDEO.title)}--{IDS[0]}.en.txt"
        (batch.path / "text-files" / name).symlink_to(outside)
        with pytest.raises(OSError):
            batch.write(VIDEO, TRACK, b"new", overwrite=True)
        assert outside.read_bytes() == b"private"


def test_symlinked_text_directory_is_rejected(tmp_path):
    with open_batch(tmp_path, IDS, VIDEO.title) as batch:
        directory = batch.path / "text-files"
    directory.rmdir()
    directory.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(OSError), open_batch(tmp_path, IDS, VIDEO.title):
        pass


def test_atomic_no_clobber_and_temporary_cleanup(tmp_path, monkeypatch):
    directory = Directory(tmp_path)
    try:
        directory.publish("result.txt", b"old", overwrite=False)
        with pytest.raises(FileExistsError):
            directory.publish("result.txt", b"new", overwrite=False)
        assert directory.read("result.txt") == b"old"
        assert not list(tmp_path.glob("*.tmp"))
        original_link = os.link

        def racing_link(src, dst, **kwargs):
            (tmp_path / dst).write_bytes(b"other writer")
            return original_link(src, dst, **kwargs)

        monkeypatch.setattr(os, "link", racing_link)
        with pytest.raises(FileExistsError):
            directory.publish("race.txt", b"new", overwrite=False)
        assert directory.read("race.txt") == b"other writer"
    finally:
        directory.close()


def test_unicode_long_and_empty_titles():
    assert len(slug("世" * 1000).encode()) <= 80
    assert slug("../../") == "video"
    assert "/" not in slug("../unsafe/title")


def test_hash_collision_extends_suffix(tmp_path):
    with open_batch(tmp_path, IDS, VIDEO.title) as batch:
        first = batch.path
        path = first / "manifest.json"
    data = json.loads(path.read_text())
    data["video_ids"] = ["wxyz0123456"]
    path.write_text(json.dumps(data))
    with open_batch(tmp_path, IDS, VIDEO.title) as batch:
        assert batch.path != first
        assert len(batch.path.name.rsplit("--", 1)[1]) == 12


def test_reload_manifest_after_previous_writer_finishes(tmp_path, monkeypatch):
    import yt_transcript_dl.storage as storage

    first_context = open_batch(tmp_path, IDS, VIDEO.title)
    first = first_context.__enter__()
    original_load = storage.load_manifest
    committed = False

    def interleave(directory):
        nonlocal committed
        snapshot = original_load(directory)
        if not committed:
            first.write(VIDEO, TRACK, b"first video", overwrite=False)
            first_context.__exit__(None, None, None)
            committed = True
        return snapshot

    monkeypatch.setattr(storage, "load_manifest", interleave)
    try:
        with open_batch(tmp_path, IDS, "Changed first title") as second:
            assert f"{IDS[0]}.en" in second.manifest["files"]
            video = Video(IDS[1], "Second", "", (TRACK,))
            second.write(video, TRACK, b"second video", overwrite=False)
            assert len(json.loads((second.path / "manifest.json").read_text())["files"]) == 2
    finally:
        if not committed:
            first_context.__exit__(None, None, None)


@pytest.mark.parametrize("bad_character", ["\x00", "\ud800"])
def test_invalid_filename_encoding_is_a_manifest_error(tmp_path, bad_character):
    with open_batch(tmp_path, IDS, VIDEO.title) as batch:
        batch.write(VIDEO, TRACK, b"original", overwrite=False)
        path = batch.path / "manifest.json"
    data = json.loads(path.read_text())
    data["files"][f"{IDS[0]}.en"]["path"] = f"text-files/{bad_character}--{IDS[0]}.en.txt"
    path.write_text(json.dumps(data))
    with pytest.raises(Failure, match="malformed"), open_batch(tmp_path, IDS, VIDEO.title):
        pass
