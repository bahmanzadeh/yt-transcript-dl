import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "install.sh"


@pytest.mark.parametrize("arguments,code", [(["--help"], 0), (["-h"], 0), (["--unknown"], 2)])
def test_installer_help_and_invalid_args_need_no_tools(tmp_path, arguments, code):
    result = subprocess.run(
        ["/bin/bash", str(SCRIPT), *arguments],
        cwd=tmp_path,
        env={**os.environ, "PATH": str(tmp_path), "NO_COLOR": "", "TERM": "dumb"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == code
    assert "\x1b[" not in result.stdout + result.stderr
    assert not list(tmp_path.iterdir())
    if code == 0:
        assert "make install" in result.stdout and "--help" in result.stdout
