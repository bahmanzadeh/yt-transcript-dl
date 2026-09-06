"""Identity-based batch directories and atomic, protected transcript publication.

Directory descriptors keep managed operations anchored even if a pathname changes.
Advisory locks coordinate ytt-dl writers; no-clobber links protect new files from
other writers. Lock files remain in place so every process locks the same inode.
"""

import ctypes
import errno
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import unicodedata
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path

from .inputs import LANGUAGE, VIDEO_ID
from .models import Failure, Result, Track, Video

MANIFEST = "manifest.json"
HEX = re.compile(r"[0-9a-f]{64}\Z")


def slug(title: str, max_bytes: int = 80) -> str:
    title = unicodedata.normalize("NFKC", title).lower()
    name = re.sub(r"[^\w]+", "-", title, flags=re.UNICODE).strip("-_")
    return name.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore").rstrip("-_") or "video"


class Directory:
    def __init__(self, path: str | Path, *, parent: "Directory | None" = None):
        self.fd = os.open(
            path,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent.fd if parent else None,
        )

    def close(self) -> None:
        os.close(self.fd)

    def exists(self, name: str) -> bool:
        try:
            os.stat(name, dir_fd=self.fd, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False

    def read(self, name: str, limit: int = 32 * 1024 * 1024) -> bytes:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise Failure("unsafe_output", "Managed output must be a regular file.")
            data = handle.read(limit + 1)
        if len(data) > limit:
            raise Failure("unsafe_output", "Managed file exceeds the supported size limit.")
        return data

    @contextmanager
    def lock(self):
        fd = os.open(
            ".ytt-dl.lock",
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
            dir_fd=self.fd,
        )
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise Failure("unsafe_output", "Output lock must be a regular file.")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Failure(
                    "output_busy", "Another ytt-dl process is using this output."
                ) from None
            yield
        finally:
            os.close(fd)

    def publish(self, name: str, data: bytes, *, overwrite: bool) -> None:
        if self.exists(name):
            mode = os.stat(name, dir_fd=self.fd, follow_symlinks=False).st_mode
            if not stat.S_ISREG(mode):
                raise Failure("unsafe_output", "Refusing a symlink or non-file destination.")
        temporary = f".ytt-dl-{uuid.uuid4().hex}.tmp"
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=self.fd)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if overwrite:
                os.replace(temporary, name, src_dir_fd=self.fd, dst_dir_fd=self.fd)
            else:
                os.link(
                    temporary,
                    name,
                    src_dir_fd=self.fd,
                    dst_dir_fd=self.fd,
                    follow_symlinks=False,
                )
            os.fsync(self.fd)
        finally:
            if self.exists(temporary):
                os.unlink(temporary, dir_fd=self.fd)

    def publish_directory(self, source: str, name: str) -> None:
        """Atomically rename a prepared child without replacing any destination."""
        unsupported = Failure(
            "unsupported_output",
            "This platform or filesystem does not support exclusive batch publication.",
        )
        if sys.platform == "darwin":
            symbol, flags = "renameatx_np", 0x00000004  # RENAME_EXCL
        elif sys.platform == "linux":
            symbol, flags = "renameat2", 1  # RENAME_NOREPLACE
        else:
            raise unsupported
        try:
            rename = getattr(ctypes.CDLL(None, use_errno=True), symbol)
        except AttributeError:
            raise unsupported from None
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        if rename(self.fd, os.fsencode(source), self.fd, os.fsencode(name), flags) != 0:
            code = ctypes.get_errno()
            if code in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}:
                raise unsupported
            raise OSError(code, os.strerror(code), name)


def load_manifest(directory: Directory) -> dict:
    try:
        value = json.loads(directory.read(MANIFEST, limit=4 * 1024 * 1024))
        # JSON permits escaped lone surrogates, but UTF-8 files and paths do not.
        json.dumps(value, ensure_ascii=False).encode("utf-8")
        if not isinstance(value, dict) or type(value.get("schema_version")) is not int:
            raise ValueError
        if value["schema_version"] != 1:
            raise ValueError
        ids = value["video_ids"]
        if (
            not isinstance(ids, list)
            or not ids
            or not all(isinstance(i, str) and VIDEO_ID.fullmatch(i) for i in ids)
            or len(ids) != len(set(ids))
        ):
            raise ValueError
        if not isinstance(value["first_title"], str) or not isinstance(value["files"], dict):
            raise ValueError
        if not isinstance(value["outcomes"], dict):
            raise ValueError
        paths: set[str] = set()
        for key, entry in value["files"].items():
            if not isinstance(entry, dict):
                raise ValueError
            identity, language, path = entry["video_id"], entry["language"], entry["path"]
            if (
                identity not in ids
                or not isinstance(language, str)
                or not LANGUAGE.fullmatch(language)
            ):
                raise ValueError
            if key != f"{identity}.{language}" or not isinstance(path, str):
                raise ValueError
            relative = Path(path)
            if (
                len(relative.parts) != 2
                or relative.parts[0] != "text-files"
                or relative.name in {".", ".."}
                or "\\" in path
                or "\x00" in path
                or not relative.name.endswith(f"--{identity}.{language}.txt")
                or path in paths
            ):
                raise ValueError
            checksum = entry["sha256"]
            if checksum is not None and (
                not isinstance(checksum, str) or not HEX.fullmatch(checksum)
            ):
                raise ValueError
            if entry["kind"] not in {"human", "automatic"}:
                raise ValueError
            paths.add(path)
        return value
    except (ValueError, KeyError, TypeError, UnicodeError, RecursionError):
        raise Failure(
            "invalid_manifest",
            "Batch manifest is malformed or unsupported; no files were replaced.",
        ) from None


class Batch:
    def __init__(self, path: Path, directory: Directory, text: Directory, manifest: dict):
        self.path, self.directory, self.text, self.manifest = path, directory, text, manifest

    def save(self, *, new: bool = False) -> None:
        self.directory.publish(
            MANIFEST,
            (json.dumps(self.manifest, indent=2, ensure_ascii=False) + "\n").encode(),
            overwrite=not new,
        )

    def write(self, video: Video, track: Track, data: bytes, *, overwrite: bool) -> Result:
        key = f"{video.video_id}.{track.language}"
        previous = self.manifest["files"].get(key)
        if previous is None:
            previous = {
                "video_id": video.video_id,
                "language": track.language,
                "kind": track.kind,
                "path": f"text-files/{slug(video.title)}--{key}.txt",
                "sha256": None,
            }
            self.manifest["files"][key] = previous
            self.save()  # Reserve the name before publishing; a crash cannot lose its identity.
        name = Path(previous["path"]).name
        status = "downloaded"
        try:
            existing = self.text.read(name)
        except FileNotFoundError:
            existing = None
        if existing == data:
            status = "unchanged"
        elif existing is not None and not overwrite:
            raise Failure("output_conflict", "Transcript differs; use --overwrite to replace it.")
        else:
            try:
                self.text.publish(name, data, overwrite=overwrite)
            except FileExistsError:
                # An unrelated writer created the file between the read and publication.
                if self.text.read(name) != data:
                    raise Failure(
                        "output_conflict", "A different transcript appeared during writing."
                    ) from None
                status = "unchanged"
        self.manifest["files"][key] = {
            **previous,
            "sha256": hashlib.sha256(data).hexdigest(),
            "kind": track.kind,
        }
        result = Result(video.video_id, status, track.language, str(self.path / previous["path"]))
        self.record(result)
        return result

    def record(self, result: Result) -> None:
        self.manifest["outcomes"][result.video_id] = {
            "status": result.status,
            "error_code": result.error.code if result.error else None,
        }
        self.save()


@contextmanager
def open_batch(root: Path, ids: list[str], first_title: str):
    if root.is_symlink():
        raise Failure("unsafe_output", "The output root must not be a symlink.")
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve()
    digest = hashlib.sha256("\n".join(ids).encode()).hexdigest()
    single = len(ids) == 1
    with ExitStack() as stack:
        parent = Directory(root)
        stack.callback(parent.close)
        with parent.lock():
            matches: list[tuple[str, dict]] = []
            for name in os.listdir(parent.fd):
                if name.startswith(".ytt-dl-init-"):
                    continue
                suffix = name.rsplit("--", 1)[-1]
                candidate = (
                    name.endswith(f"--{ids[0]}")
                    if single
                    else (len(suffix) in range(8, 65, 4) and digest.startswith(suffix))
                )
                if not candidate:
                    continue
                try:
                    child = Directory(name, parent=parent)
                except (NotADirectoryError, OSError):
                    raise Failure(
                        "unsafe_output", "A batch path is not a regular directory."
                    ) from None
                try:
                    if child.exists(MANIFEST):
                        manifest = load_manifest(child)
                        if manifest["video_ids"] == ids:
                            matches.append((name, manifest))
                finally:
                    child.close()
            if len(matches) > 1:
                raise Failure("ambiguous_batch", "Multiple folders claim this batch identity.")
            new = not matches
            if matches:
                name, manifest = matches[0]
                working_name = name
            else:
                prefix = slug(first_title)
                if not single:
                    prefix = prefix[:12].rstrip("-_") or "video"
                for length in [11] if single else range(8, 65, 4):
                    suffix = ids[0] if single else digest[:length]
                    name = f"{prefix}--{suffix}"
                    if not parent.exists(name):
                        break
                else:
                    raise Failure("output_conflict", "The batch destination is already occupied.")
                working_name = f".ytt-dl-init-{uuid.uuid4().hex}.tmp"
                os.mkdir(working_name, mode=0o700, dir_fd=parent.fd)
                manifest = {
                    "schema_version": 1,
                    "video_ids": ids,
                    "first_title": first_title,
                    "files": {},
                    "outcomes": {},
                }
            directory = Directory(working_name, parent=parent)
            stack.callback(directory.close)
            stack.enter_context(directory.lock())
            if not new:
                # Discovery may overlap the previous writer's last commit. The
                # authoritative snapshot must be read after owning its lock.
                manifest = load_manifest(directory)
                if manifest["video_ids"] != ids:
                    raise Failure("invalid_manifest", "Batch identity changed during discovery.")
            if not directory.exists("text-files"):
                os.mkdir("text-files", mode=0o700, dir_fd=directory.fd)
            text = Directory("text-files", parent=directory)
            stack.callback(text.close)
            batch = Batch(root / name, directory, text, manifest)
            if new:
                os.fsync(text.fd)
                batch.save(new=True)
                try:
                    parent.publish_directory(working_name, name)
                except FileExistsError:
                    raise Failure(
                        "output_conflict", "The batch destination is already occupied."
                    ) from None
                os.fsync(parent.fd)
        yield batch
