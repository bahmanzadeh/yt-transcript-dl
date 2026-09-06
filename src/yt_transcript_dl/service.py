"""One visible sequential batch workflow with isolated per-video failures."""

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .captions import render
from .models import Error, Failure, Result, Video, select_track
from .provider import YouTube
from .storage import open_batch


@dataclass
class Summary:
    schema_version: int = 1
    output_dir: str | None = None
    results: list[Result] = field(default_factory=list)
    error: Error | None = None
    interrupted: bool = False

    @property
    def exit_code(self) -> int:
        if self.interrupted:
            return 130
        return 1 if self.error or any(r.status == "failed" for r in self.results) else 0

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "counts": {
                s: sum(r.status == s for r in self.results)
                for s in (
                    "downloaded",
                    "unchanged",
                    "listed",
                    "failed",
                )
            },
        }


def run(
    ids: list[str],
    root: Path,
    languages: tuple[str, ...],
    *,
    timestamps: bool,
    overwrite: bool,
    list_languages: bool,
    timeout: float,
    retries: int,
    progress: Callable[[Result], None],
) -> Summary:
    summary = Summary()

    def emit(result: Result) -> None:
        summary.results.append(result)
        progress(result)

    def inspect(client: YouTube, identity: str) -> Video | Failure:
        try:
            return client.video(identity)
        except Failure as exc:
            return exc

    def failed(identity: str, exc: Failure) -> Result:
        return Result(identity, "failed", error=Error(exc.code, exc.message))

    try:
        with YouTube(timeout, retries) as client:
            if list_languages:
                for identity in ids:
                    video = inspect(client, identity)
                    if isinstance(video, Failure):
                        emit(failed(identity, video))
                    else:
                        emit(
                            Result(
                                identity, "listed", tracks=[t.description() for t in video.tracks]
                            )
                        )
                return summary
            first = inspect(client, ids[0])
            title = first.title if isinstance(first, Video) else ids[0]
            with open_batch(root, ids, title) as batch:
                summary.output_dir = str(batch.path / "text-files")
                for index, identity in enumerate(ids):
                    video = first if index == 0 else inspect(client, identity)
                    try:
                        if isinstance(video, Failure):
                            raise video
                        track = select_track(video, languages)
                        data = render(video, track, client.captions(track), timestamps=timestamps)
                        result = batch.write(video, track, data, overwrite=overwrite)
                    except Failure as exc:
                        result = failed(identity, exc)
                        batch.record(result)
                    emit(result)
    except KeyboardInterrupt:
        summary.interrupted = True
    except Failure as exc:
        summary.error = Error(exc.code, exc.message)
    except OSError:
        summary.error = Error(
            "output_io",
            "Output operation failed. Check permissions, free space, and symlinks.",
        )
    return summary
