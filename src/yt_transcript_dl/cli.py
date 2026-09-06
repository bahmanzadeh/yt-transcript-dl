"""Flat command-line interface. Help/version never initialize the provider."""

import json
import math
import os
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from . import __version__
from .inputs import LANGUAGE, read_inputs
from .models import Result

EXAMPLES = """Examples (replace the bracketed video IDs):

  ytt-dl 'https://youtu.be/<VIDEO_ID>'
  ytt-dl '<VIDEO_ID_1>' '<VIDEO_ID_2>'
  ytt-dl 'https://youtu.be/<VIDEO_ID_1>' '<VIDEO_ID_2>'
  ytt-dl --input-file videos.txt --output-dir ~/notes
  cat videos.txt | ytt-dl --input-file -
  ytt-dl '<VIDEO_ID>' --language en --timestamps
  ytt-dl '<VIDEO_ID>' --language fr --language en
  ytt-dl '<VIDEO_ID>' --list-languages
  ytt-dl --input-file videos.txt --overwrite --json
  ytt-dl '<VIDEO_ID>' --timeout 45 --retries 3
  ytt-dl -- '-VIDEO_ID01'
  ytt-dl --help
  ytt-dl --version

Output: ROOT/<title>--<video-id>/text-files for one video;
ROOT/<first-title-up-to-12-chars>--<batch-hash>/text-files for multiple videos.
ROOT defaults to ~/ytt-dl. --output-dir changes ROOT, not the grouping layout.
Identical ordered batches reuse their folder. Differing files need --overwrite.

Exit codes: 0 complete success, 1 operational/partial failure, 2 invalid usage,
130 interrupted. No playlist or channel expansion; no media downloads.
"""

app = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    pretty_exceptions_enable=False,
)


def show_version(value: bool) -> None:
    if value:
        typer.echo(f"ytt-dl {__version__}")
        raise typer.Exit()


@app.command(epilog=EXAMPLES)
def download(
    ctx: typer.Context,
    videos: Annotated[
        list[str] | None,
        typer.Argument(
            metavar="[URL_OR_ID...]",
            help="One or more video URLs or IDs; duplicates use first occurrence.",
        ),
    ] = None,
    input_file: Annotated[
        list[str] | None,
        typer.Option(
            "--input-file",
            "-i",
            metavar="FILE",
            help="One URL/ID per line; repeatable. '-' reads stdin.",
            rich_help_panel="Inputs and output",
        ),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            "-o",
            metavar="DIR",
            help="Create the named batch folder beneath this root.",
            show_default="~/ytt-dl",
            rich_help_panel="Inputs and output",
        ),
    ] = None,
    language: Annotated[
        list[str] | None,
        typer.Option(
            "--language",
            "-l",
            metavar="CODE",
            help="Caption language; repeat for ordered fallbacks.",
            show_default="en",
            rich_help_panel="Captions",
        ),
    ] = None,
    timestamps: Annotated[
        bool,
        typer.Option(
            "--timestamps",
            help="Add HH:MM:SS paragraph timestamps.",
            rich_help_panel="Captions",
        ),
    ] = False,
    list_languages: Annotated[
        bool,
        typer.Option(
            "--list-languages",
            help="List available JSON3 caption tracks without creating output folders.",
            rich_help_panel="Captions",
        ),
    ] = False,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            help="Allow replacement of differing existing transcript files.",
            rich_help_panel="Inputs and output",
        ),
    ] = False,
    timeout: Annotated[
        float,
        typer.Option(
            "--timeout",
            metavar="SECONDS",
            help="Positive socket-operation timeout.",
            rich_help_panel="Networking",
        ),
    ] = 30.0,
    retries: Annotated[
        int,
        typer.Option(
            "--retries",
            min=0,
            metavar="N",
            help="Additional attempts per transiently failing operation.",
            rich_help_panel="Networking",
        ),
    ] = 2,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Write one structured result summary to stdout.",
        ),
    ] = False,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=show_version,
            is_eager=True,
            help="Print package version and exit.",
        ),
    ] = False,
) -> None:
    """Download separate readable text transcripts for explicit YouTube videos.

    Prefer human captions, then automatic captions in the requested language.
    List files allow blank lines and full-line # comments. Positional videos
    precede files; files are read in option order.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise typer.BadParameter(
            "Must be a finite number greater than zero.", param_hint="--timeout"
        )
    if list_languages:
        for parameter in ("output_dir", "language", "timestamps", "overwrite"):
            source = ctx.get_parameter_source(parameter)
            if source is not None and source.name == "COMMANDLINE":
                raise typer.BadParameter(
                    "Cannot combine --list-languages with download-only options.",
                )
    languages = tuple(dict.fromkeys(s.lower() for s in (language or ["en"])))
    if not all(LANGUAGE.fullmatch(s) for s in languages):
        raise typer.BadParameter(
            "Use a language code such as en, en-US, or fr.", param_hint="--language"
        )
    try:
        ids = read_inputs(videos or [], input_file or [], sys.stdin)
        root = (output_dir or Path.home() / "ytt-dl").expanduser().absolute()
        if not list_languages and (root.is_symlink() or (root.exists() and not root.is_dir())):
            raise ValueError("The output root must be a directory, not a file or symlink.")
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from None

    console = Console(stderr=True, no_color="NO_COLOR" in os.environ or os.getenv("TERM") == "dumb")

    def progress(result: Result) -> None:
        if result.error:
            console.print(
                f"ERROR: {result.video_id}: {result.error.message}", style="red", markup=False
            )
        elif not json_output:
            if result.status == "listed":
                console.print(f"{result.video_id}:", markup=False)
                for track in result.tracks or []:
                    console.print(
                        f"  {track['language']}  {track['kind']}  {track['name']}",
                        markup=False,
                    )
                if not result.tracks:
                    console.print("  No accessible JSON3 caption tracks.")
            else:
                console.print(f"{result.status}: {result.path}", markup=False)

    # Delay yt-dlp imports, platform locking, and provider setup until after validation.
    from .service import run

    if not json_output:
        console.print(f"Processing {len(ids)} video(s)...", markup=False)
    summary = run(
        ids,
        root,
        languages,
        timestamps=timestamps,
        overwrite=overwrite,
        list_languages=list_languages,
        timeout=timeout,
        retries=retries,
        progress=progress,
    )
    if summary.error:
        console.print(f"ERROR: {summary.error.message}", style="red", markup=False)
    if summary.interrupted:
        console.print("Interrupted. Completed transcripts are preserved.", style="yellow")
    if json_output:
        typer.echo(json.dumps(summary.to_dict(), ensure_ascii=False))
    else:
        counts = summary.to_dict()["counts"]
        typer.echo(
            f"Downloaded: {counts['downloaded']}; unchanged: {counts['unchanged']}; "
            f"listed: {counts['listed']}; failed: {counts['failed']}."
        )
        if summary.output_dir:
            typer.echo(f"Transcripts: {summary.output_dir}")
    raise typer.Exit(summary.exit_code)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
