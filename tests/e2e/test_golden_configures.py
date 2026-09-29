"""M0: the reference project configures with CMake's default generator on this OS."""

import shutil
import subprocess

import pytest

pytestmark = pytest.mark.e2e


@pytest.mark.skipif(shutil.which("cmake") is None, reason="cmake is not installed")
def test_golden_configures(golden_dir, tmp_path):
    result = subprocess.run(
        ["cmake", "-S", str(golden_dir), "-B", str(tmp_path / "build")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
