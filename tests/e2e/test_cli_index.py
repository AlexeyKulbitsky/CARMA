"""M1: `carma index` on a copy of the reference project, the way a user runs it."""

import shutil
import subprocess

import pytest

from carma.cli import main
from carma.store.sqlite import SQLiteStore

pytestmark = pytest.mark.e2e


@pytest.fixture
def project(golden_dir, tmp_path, cmake, libclang_path):
    root = tmp_path / "golden"
    shutil.copytree(golden_dir, root, ignore=shutil.ignore_patterns("expected", "facts.jsonl"))
    result = subprocess.run([cmake, "-S", str(root), "-B", str(root / "build")], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    (root / ".carma").mkdir()
    shutil.copy(golden_dir / "expected" / "config.yaml", root / ".carma" / "config.yaml")
    return root


def test_index_then_reindex(project, capsys):
    assert main(["index", "--project", str(project), "--jobs", "2"]) == 0
    out = capsys.readouterr().out
    assert "9 TUs" in out and "0 with parse errors" in out and "(full load)" in out

    with SQLiteStore(project / ".carma" / "cache" / "facts.db") as store:
        callers = {e.caller for e in store.callers("cxx golden/render/GpuUploader#Upload(const std::string&).")}
        assert callers == {"cxx golden/streaming/TextureStreamer#OnLoaded(const std::string&)."}

    # nothing changed: nothing is reloaded
    assert main(["index", "--project", str(project), "--jobs", "2"]) == 0
    assert "0 of" in capsys.readouterr().out
