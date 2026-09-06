import json
import selectors
import subprocess
import sys

import pytest

from yt_transcript_dl.models import Failure
from yt_transcript_dl.storage import open_batch

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("boundary", ["manifest", "before_publish", "after_publish"])
@pytest.mark.parametrize("ids", [["abcdefghijk"], ["abcdefghijk", "lmnopqrstuv"]])
def test_process_death_during_initialization_allows_rerun(tmp_path, boundary, ids):
    script = """
import json
import sys
from pathlib import Path
from yt_transcript_dl.storage import Batch, Directory, open_batch

boundary = sys.argv[2]
def barrier():
    print('ready', flush=True)
    sys.stdin.read(1)

save = Batch.save
def paused_save(self, *, new=False):
    if new and boundary == 'manifest':
        barrier()
    return save(self, new=new)

publish = Directory.publish_directory
def paused_publish(self, source, name):
    if boundary == 'before_publish':
        barrier()
    publish(self, source, name)
    if boundary == 'after_publish':
        barrier()

Batch.save = paused_save
Directory.publish_directory = paused_publish
with open_batch(Path(sys.argv[1]), json.loads(sys.argv[3]), 'Original title'):
    raise AssertionError('parent should kill this process at the requested boundary')
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path), boundary, json.dumps(ids)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        with selectors.DefaultSelector() as ready:
            ready.register(process.stdout, selectors.EVENT_READ)
            assert ready.select(timeout=10), "writer did not reach the initialization boundary"
        assert process.stdout.readline().strip() == "ready"
        process.kill()
        process.communicate(timeout=10)
        assert process.returncode < 0
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
    published = [p for p in tmp_path.iterdir() if p.is_dir() and not p.name.startswith(".")]
    assert len(published) == (1 if boundary == "after_publish" else 0)
    if published:
        assert json.loads((published[0] / "manifest.json").read_text())["video_ids"] == ids
    with open_batch(tmp_path, ids, "Original title") as batch:
        assert batch.manifest["video_ids"] == ids
        assert (batch.path / "text-files").is_dir()
        if published:
            assert batch.path == published[0]


def test_separate_process_holds_batch_lock(tmp_path):
    script = """
import sys
from pathlib import Path
from yt_transcript_dl.storage import open_batch
with open_batch(Path(sys.argv[1]), ['abcdefghijk', 'lmnopqrstuv'], 'Original title'):
    print('locked', flush=True)
    sys.stdin.readline()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "locked"
        with (
            pytest.raises(Failure, match="Another ytt-dl"),
            open_batch(tmp_path, ["abcdefghijk", "lmnopqrstuv"], "Different title"),
        ):
            pytest.fail("second writer admitted")
        process.communicate("done\n", timeout=10)
        assert process.returncode == 0
    finally:
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=10)
    with open_batch(tmp_path, ["abcdefghijk", "lmnopqrstuv"], "New title") as batch:
        assert batch.path.name.startswith("original-tit--")
