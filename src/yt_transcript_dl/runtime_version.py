"""Resolve live checkout versions without making SCM a runtime dependency."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version
from pathlib import Path


def version() -> str:
    root = Path(__file__).resolve().parents[2]
    if (root / ".git").exists() and (root / "pyproject.toml").is_file():
        try:
            from setuptools_scm import get_version

            return get_version(
                root=str(root),
                tag_regex=r"^yt-transcript-dl-v(?P<version>\d+\.\d+\.\d+)$",
                fallback_version="0+unknown",
                scm={
                    "git": {
                        "describe_command": (
                            "git describe --dirty --tags --long --match yt-transcript-dl-v*"
                        )
                    }
                },
            )
        except (ImportError, LookupError, OSError):
            pass
    try:
        return installed_version("yt-transcript-dl")
    except PackageNotFoundError:
        try:
            from ._version import __version__

            return __version__
        except ImportError:
            return "0+unknown"
