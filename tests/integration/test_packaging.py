import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def test_wheel_in_isolated_tool_environment(tmp_path):
    wheels = list((ROOT / "dist").glob("yt_transcript_dl-*.whl"))
    assert wheels, "Run make build before integration tests."
    wheel = max(wheels, key=lambda p: p.stat().st_mtime_ns)
    constraints = tmp_path / "constraints.txt"
    environment = {
        **os.environ,
        "UV_TOOL_DIR": str(tmp_path / "tools"),
        "UV_TOOL_BIN_DIR": str(tmp_path / "bin"),
        "NO_COLOR": "1",
        "TERM": "dumb",
    }
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)

    def run(args, *, cwd=tmp_path):
        result = subprocess.run(
            args,
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        return result

    run(
        [
            "uv",
            "export",
            "--locked",
            "--no-dev",
            "--no-emit-project",
            "--no-hashes",
            "--output-file",
            str(constraints),
        ],
        cwd=ROOT,
    )
    run(
        [
            "uv",
            "tool",
            "install",
            "--python",
            sys.executable,
            "--constraints",
            str(constraints),
            str(wheel),
        ]
    )
    executable = tmp_path / "bin" / "ytt-dl"
    assert "--output-dir" in run([str(executable), "--help"]).stdout
    assert run([str(executable), "--version"]).stdout.startswith("ytt-dl ")
    python = tmp_path / "tools" / "yt-transcript-dl" / "bin" / "python"
    script = """
import json
from pathlib import Path
import yt_transcript_dl
from yt_transcript_dl.captions import parse_json3, render
from yt_transcript_dl.models import Track, Video
from yt_transcript_dl.storage import open_batch
track = Track('en', 'English', 'human', 'https://youtube.com/api/timedtext')
video = Video('abcdefghijk', 'Packaged example', '', (track,))
cues = parse_json3(b'{"events":[{"tStartMs":0,"segs":[{"utf8":"Wheel works."}]}]}')
with open_batch(Path('output'), [video.video_id], video.title) as batch:
    data = render(video, track, cues, timestamps=False)
    result = batch.write(video, track, data, overwrite=False)
    print(json.dumps({'module': yt_transcript_dl.__file__, 'path': result.path}))
"""
    result = json.loads(run([str(python), "-c", script]).stdout)
    assert str(ROOT / "src") not in result["module"]
    assert "site-packages" in result["module"]
    assert Path(result["path"]).read_text().endswith("Wheel works.\n")
