# ytt-dl

Download readable YouTube transcripts for one or many videos in a single command.
Each successful video becomes a separate UTF-8 text file in a named folder.

```bash
ytt-dl 'https://youtu.be/<VIDEO_ID_1>' '<VIDEO_ID_2>' --output-dir ~/notes
```

Replace bracketed IDs in these examples with actual 11-character YouTube video
IDs. Quote URLs so your shell does not interpret `&`, `?`, or other punctuation.

## Install

Supported platforms: **macOS and Linux**, with Python **3.11–3.13**. The installer
uses Python 3.13 and uv can provision that interpreter when needed.

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and
[Deno](https://docs.deno.com/runtime/getting_started/installation/), then run from
your checkout:

```bash
make install
ytt-dl --help
```

`make install` builds a wheel directly from the checkout and installs the command
into uv's isolated tool environment. It exports runtime constraints from
`uv.lock`, so installation uses the same dependency versions as the project.
It also refreshes an existing installation. It does not use sudo, edit your shell
profile, or install Deno.
If `ytt-dl` is not on PATH, add the directory reported by `uv tool dir --bin`.
Use `make build` to build and validate both the source archive and its wheel.

For development, or to run without installing a global command:

```bash
uv sync --locked
uv run --locked ytt-dl --help
uv run --locked ytt-dl '<VIDEO_ID>'
```

The caption backend is the Python `yt-dlp` package, including its EJS dependency.
Deno 2.3 or newer provides the supported JavaScript runtime; see
[yt-dlp's runtime setup](https://github.com/yt-dlp/yt-dlp/wiki/EJS).
No separate `yt-dlp` executable or FFmpeg is needed: this application retrieves
metadata and JSON3 captions, not audio or video.

## Usage

```text
ytt-dl [OPTIONS] [URL_OR_ID...]
```

| Option | Meaning |
| --- | --- |
| `-i, --input-file FILE` | One URL/ID per line; repeatable. `-` reads stdin. |
| `-o, --output-dir DIR` | Root for named folders; default `~/ytt-dl`. |
| `-l, --language CODE` | Language; default `en`. Repeat for fallback order. |
| `--timestamps` | Add `HH:MM:SS` timestamps to paragraphs. |
| `--list-languages` | List JSON3 tracks without creating output folders. |
| `--overwrite` | Allow replacement of differing transcript files. |
| `--timeout SECONDS` | Positive, finite socket timeout; default `30`. |
| `--retries N` | Extra attempts per transient operation failure; default `2`. |
| `--json` | Write one structured result summary to stdout. |
| `--version` | Print package version and exit. |
| `-h, --help` | Show usage, defaults, layout, exit codes, and examples. |

### One video, multiple videos, or a list file

```bash
ytt-dl 'https://www.youtube.com/watch?v=<VIDEO_ID>'
ytt-dl '<VIDEO_ID_1>' '<VIDEO_ID_2>'
ytt-dl 'https://youtu.be/<VIDEO_ID_1>' '<VIDEO_ID_2>'
ytt-dl --input-file videos.txt --output-dir ~/notes
ytt-dl --input-file first.txt --input-file second.txt
cat videos.txt | ytt-dl --input-file -
```

List files contain one video URL or ID per line. Blank lines, full-line `#`
comments, surrounding whitespace, UTF-8 BOMs, and CRLF line endings are accepted.
Positional inputs come first, followed by files in option order. Duplicate IDs
are removed after their first occurrence. Every input is validated before any
network request or output creation.

Standard watch URLs, `youtu.be`, Shorts, live-video, and embed URLs are supported.
Playlist and channel URLs are rejected; a video URL containing playlist
parameters downloads only that video. To pass an ID beginning with a hyphen,
place it after `--`:

```bash
ytt-dl -- '-VIDEO_ID01'
```

### Languages and timestamps

```bash
ytt-dl '<VIDEO_ID>' --language en --timestamps
ytt-dl '<VIDEO_ID>' --language fr --language en
ytt-dl '<VIDEO_ID>' --list-languages
```

Within each requested language, human captions take precedence over automatic
captions. A base code such as `en` also matches variants such as `en-US` and
`en-orig`. An explicit variant such as `en-US` requires that exact track code.
Languages are tried in the order supplied. If none match, the video fails with
a list of available tracks.

Track discovery can be combined with input files, `--json`, and network options.
It cannot be combined with `--output-dir`, `--language`, `--timestamps`, or
`--overwrite`. Only native caption tracks are selected; the tool does not request
translated tracks, transcribe audio, summarize, or rewrite caption wording.
Translated tracks are excluded from both discovery and language fallback selection.

Text files contain a title, canonical source URL, channel when available,
caption language/type, and readable paragraphs grouped approximately every
30 seconds. Repeated speech is preserved. Automatic captions can contain errors.

### Output folders

With no output option, the root is `~/ytt-dl`. With `--output-dir ~/notes`, the
root is `~/notes`; the grouping layout remains the same:

```text
<root>/
  <video-or-batch-name>/
    manifest.json
    text-files/
      <title>--<video-id>.<language>.txt
```

For one video, the folder name is its sanitized title plus video ID. For a batch,
the folder name begins with **up to 12 characters of the first video's sanitized
title**, followed by `--` and an eight-character identity hash. The suffix grows
if necessary to distinguish a collision. Titles used for individual files and
single-video folders are sanitized and limited to 80 UTF-8 bytes.

For example, a batch whose first title is “Python introduction” has a folder
shaped like `python-intro--a1b2c3d4/text-files`. The suffix comes from the ordered,
deduplicated video IDs. Changing their order or membership creates a different
batch. If the first title cannot be retrieved, its video ID is used instead.

The manifest preserves the full batch identity and assigned paths, so later title
changes do not rename an existing batch or its files. Keep the manifest alongside
the transcripts. Hidden `.ytt-dl.lock` files coordinate writers and remain in
place after exit; the operating system releases their locks when a process ends.

The terminal summary prints the absolute `text-files` directory. Raw caption
downloads and signed caption URLs are not saved in the output or manifest.

### Reruns and failures

```bash
ytt-dl --input-file videos.txt --output-dir ~/notes
ytt-dl --input-file videos.txt --output-dir ~/notes --overwrite
ytt-dl '<VIDEO_ID>' --timeout 45 --retries 3
```

A rerun fetches the currently requested captions and compares the rendered bytes.
Identical files are reported as unchanged. A changed upstream transcript, title
header, caption type, timestamp setting, or locally edited file requires
`--overwrite` before replacement. Selecting another language creates a separate
language file in the same batch folder.

Individual unavailable videos and caption failures do not discard successful
outputs. Temporary files are published atomically, and interrupted runs can
reuse complete files. Filesystem errors or invalid batch manifests stop the run.
Symlink destinations and paths outside the managed batch are rejected.

New batch folders are prepared under a hidden temporary name and published only
after their manifest and `text-files` directory are complete. An interruption
during setup therefore permits the same command to run again. Publication never
replaces an existing folder, file, or symlink. It requires filesystem support for
exclusive directory renaming; unsupported operations stop with an error.

Interrupted setup can leave hidden `.ytt-dl-init-*.tmp` folders. They contain no
transcripts and are ignored on later runs. The application does not automatically
adopt or delete them, or repair unidentified final folders left by older runs.
An existing folder without a manifest still requires separate inspection.

Transient network failures use bounded exponential backoff. The timeout applies
to socket operations, not the entire video or batch. Access restrictions,
malformed captions, and unavailable videos are not blindly retried. Requests
are sequential to limit load. Caption responses are limited to 20 MiB.

If YouTube blocks requests, reports no captions, or changes its extraction
behavior, inspect `--list-languages`, check Deno and connectivity, and retry later.
The CLI does not import browser cookies, use login credentials, load yt-dlp
plugins/configuration, or bypass access restrictions.

### JSON and exit codes

```bash
ytt-dl --input-file videos.txt --json > results.json
ytt-dl '<VIDEO_ID>' --list-languages --json
```

JSON mode writes a single object to stdout; errors remain on stderr. The object
contains `schema_version: 1`, `output_dir`, `counts`, `results`, `error`, and
`interrupted`. Each result contains `video_id`, `status`, `language`, `path`,
`error`, and `tracks`; inapplicable fields are `null`. Errors have `code` and
`message`. Statuses are `downloaded`, `unchanged`, `listed`, or `failed`.
`output_dir` is the absolute text-file directory, or `null` for discovery or a
failure before opening a batch. Interrupted/fatal runs contain completed results
only, plus the top-level interruption or error information. Invalid arguments
use normal CLI usage errors and do not emit a JSON summary.

| Exit code | Meaning |
| --- | --- |
| `0` | Success, including unchanged files or completed track discovery. |
| `1` | At least one video failed, or an operational error stopped the run. |
| `2` | Invalid arguments or input. |
| `130` | Interrupted; completed transcripts remain available. |

Color is disabled for redirected output, `TERM=dumb`, and whenever `NO_COLOR` is
set. Download content is never written to stdout.

## Development and validation

```bash
make                    # Locked sync, lint, unit tests, wheel and source archive
make test-unit
make test-integration   # Builds, then checks process locks and an isolated wheel
make coverage
make format
uv run --locked pre-commit install
bash scripts/install.sh --help
```

`pyproject.toml` describes dependencies and `uv.lock` is the sole resolved graph.
Runtime constraints used for installation are temporary derived exports, not
another dependency authority. The installer does not change the lock.

Application tests use synthetic captions and block network access. The isolated
wheel and installer tests may contact the package index for locked dependencies;
the installer test can also provision Python 3.13. Neither contacts YouTube.
CI checks Python 3.11–3.13 on Linux and 3.13 on macOS. Pull requests run lint,
unit tests, and builds; manual and release-tag runs add integration and coverage.
Real YouTube validation is separate from those deterministic checks.

The [project requirements](docs/requirements.md) and
[design](docs/design.md) define interruption recovery, checkout installation,
and their validation
boundaries. Process-interruption tests do not establish power-loss durability.

Versions are inferred with setuptools-scm from tags shaped like
`yt-transcript-dl-vMAJOR.MINOR.PATCH`. Source checkouts resolve live SCM state;
installed packages use distribution metadata. No publishing workflow is enabled.
Checkout and build versions use the same SCM settings, including the untagged fallback.
After pulling a newer checkout, rerun `make install` to update the command.

Only generic source and synthetic fixtures belong in this repository. Keep
downloaded transcripts, local manifests, credentials, and unrelated collections
outside the checkout. The application is licensed under [Apache-2.0](LICENSE).
