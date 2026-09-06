#!/usr/bin/env bash
set -euo pipefail

bold='' red='' green='' cyan='' reset=''
if [[ ( -t 1 || -t 2 ) && "${TERM:-}" != dumb && -z "${NO_COLOR+x}" ]]; then
  bold=$'\033[1m' red=$'\033[31m' green=$'\033[32m'
  cyan=$'\033[36m' reset=$'\033[0m'
fi

usage() {
  printf '%sUsage%s\n  scripts/install.sh [--help]\n\n' "$bold" "$reset"
  printf 'Build and install ytt-dl with the committed runtime dependency versions.\n'
  printf 'Requires uv. Run from any directory; no sudo or shell-profile edits.\n\n'
  printf '%sOptions%s\n  -h, --help  Show this help without installing anything.\n\n' "$bold" "$reset"
  printf '%sExamples%s\n  %smake install%s\n  %sbash scripts/install.sh --help%s\n' \
    "$bold" "$reset" "$cyan" "$reset" "$cyan" "$reset"
}

error() { printf '%s%sERROR:%s %s\n' "$red" "$bold" "$reset" "$1" >&2; }

if [[ $# -gt 0 ]]; then
  if [[ $# -eq 1 && ( "$1" == --help || "$1" == -h ) ]]; then
    usage
    exit 0
  fi
  error 'Unknown argument. Use --help.'
  exit 2
fi
if ! command -v uv >/dev/null 2>&1; then
  error 'uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/'
  exit 1
fi

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
temp_root=$(cd -- "${TMPDIR:-/tmp}" && pwd -P)
build_dir=$(mktemp -d "$temp_root/ytt-dl-install.XXXXXXXX")
cleanup() {
  if [[ -d "$build_dir" && "$build_dir" == "$temp_root"/ytt-dl-install.* ]]; then
    find "$build_dir" -depth -delete
  fi
}
trap cleanup EXIT

cd -- "$project_root"
uv lock --check
uv sync --locked
uv run --locked python -m build --wheel --no-isolation --outdir "$build_dir"
uv export --locked --no-dev --no-emit-project --no-hashes \
  --output-file "$build_dir/runtime-constraints.txt" >/dev/null
wheels=("$build_dir"/yt_transcript_dl-*.whl)
if [[ ${#wheels[@]} -ne 1 || ! -f "${wheels[0]}" ]]; then
  error 'Build did not produce exactly one application wheel.'
  exit 1
fi
uv tool install --python 3.13 --reinstall \
  --constraints "$build_dir/runtime-constraints.txt" "${wheels[0]}"
printf '%sInstalled ytt-dl.%s Run: ytt-dl --help\n' "$green" "$reset"
printf 'If the command is not on PATH, add the directory printed by: uv tool dir --bin\n'
