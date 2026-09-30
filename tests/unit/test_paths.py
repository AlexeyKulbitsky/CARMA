from pathlib import Path

import pytest

from carma.paths import glob_match, relpath


@pytest.mark.parametrize(
    "path,pattern,expected",
    [
        ("thirdparty/fakelib/fakelib.h", "**/thirdparty/**", True),
        ("engine/thirdparty/JoltPhysics/Jolt/Jolt.h", "**/thirdparty/**", True),
        ("engine/source/render/Mesh.cpp", "**/thirdparty/**", False),
        ("build/engine_build/config.h", "build/**", True),
        ("engine/build/x.h", "build/**", False),
        ("src/io/IoQueue.cpp", "src/io/*", True),
        ("src/io/sub/x.cpp", "src/io/*", False),
        ("src/io/sub/x.cpp", "src/io/**", True),
        ("src/io/x.cpp", "src/*/x.cpp", True),
        ("src/io/x.cpp", "src/?o/x.cpp", True),
    ],
)
def test_glob_match(path, pattern, expected):
    assert glob_match(path, pattern) is expected


def test_relpath(tmp_path):
    (tmp_path / "src").mkdir()
    assert relpath(tmp_path / "src" / "a.cpp", tmp_path) == "src/a.cpp"
    assert relpath(tmp_path.parent / "other.cpp", tmp_path) is None
    assert relpath(tmp_path, tmp_path) is None


def test_relpath_ignores_case_on_windows(tmp_path):
    import os

    if os.name != "nt":
        pytest.skip("case-insensitive paths are a Windows thing")
    assert relpath(Path(str(tmp_path).upper()) / "A.cpp", tmp_path) == "A.cpp"
