import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def test_checkout_install_without_git_discovery_errors(tmp_path):
    checkout = tmp_path / "source checkout"
    checkout.mkdir()
    files = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        text=True,
        timeout=10,
    )
    for name in filter(None, files.split("\0")):
        source = ROOT / name
        if source.is_file():
            target = checkout / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    environment = {
        **os.environ,
        "UV_TOOL_DIR": str(tmp_path / "tools"),
        "UV_TOOL_BIN_DIR": str(tmp_path / "bin"),
        "UV_PROJECT_ENVIRONMENT": str(checkout / ".venv"),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "TMPDIR": str(temporary),
        "NO_COLOR": "1",
        "TERM": "dumb",
    }
    for variable in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "GIT_DIR", "GIT_WORK_TREE"):
        environment.pop(variable, None)

    def run(args, *, cwd=checkout, timeout=30):
        result = subprocess.run(
            args,
            cwd=cwd,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
        assert result.returncode == 0, result.stdout
        return result.stdout

    run(["git", "init", "-q"])
    run(["git", "add", "-A"])
    run(
        [
            "git",
            "-c",
            "user.name=Packaging Test",
            "-c",
            "user.email=packaging@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "Installation fixture",
        ]
    )
    run(["git", "-c", "tag.gpgsign=false", "tag", "yt-transcript-dl-v0.0.0"])
    lock_before = (checkout / "uv.lock").read_bytes()
    output = run(["make", "install"], timeout=180)
    assert "listing git files failed" not in output, output
    assert "Installed ytt-dl." in output
    executable = tmp_path / "bin" / "ytt-dl"
    assert "--output-dir" in run([str(executable), "--help"], cwd=tmp_path)
    assert run([str(executable), "--version"], cwd=tmp_path).strip() == "ytt-dl 0.0.0"
    assert (checkout / "uv.lock").read_bytes() == lock_before
    assert not list(temporary.glob("ytt-dl-install.*"))
