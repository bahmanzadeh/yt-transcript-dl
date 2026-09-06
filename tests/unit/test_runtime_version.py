import subprocess
import tomllib
from pathlib import Path

import pytest
from setuptools_scm import get_version

from yt_transcript_dl import runtime_version

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("tagged", [False, True])
@pytest.mark.parametrize("dirty", [False, True])
def test_checkout_version_matches_build_configuration(tmp_path, monkeypatch, tagged, dirty):
    project = (ROOT / "pyproject.toml").read_text()
    (tmp_path / "pyproject.toml").write_text(project)

    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, timeout=10)

    git("init", "--quiet")
    git("add", "pyproject.toml")
    git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "-c",
        "core.hooksPath=/dev/null",
        "commit",
        "--no-gpg-sign",
        "-m",
        "Fixture",
    )
    if tagged:
        git("-c", "tag.gpgSign=false", "tag", "yt-transcript-dl-v1.2.3")
    if dirty:
        (tmp_path / "pyproject.toml").write_text(project + "\n# Changed checkout\n")
    monkeypatch.setattr(
        runtime_version, "__file__", str(tmp_path / "src/yt_transcript_dl/runtime_version.py")
    )
    config = tomllib.loads(project)["tool"]["setuptools_scm"]
    config.pop("version_file")  # Compare build inference without generating a version file.
    assert runtime_version.version() == get_version(root=str(tmp_path), **config)
