import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# CI sets this so tests that need LLVM fail instead of silently skipping.
REQUIRE_LIBCLANG = os.environ.get("CARMA_REQUIRE_LIBCLANG") == "1"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def golden_dir() -> Path:
    return REPO_ROOT / "fixtures" / "golden_cpp"


@pytest.fixture(scope="session")
def samples_dir() -> Path:
    return REPO_ROOT / "tests" / "contract" / "samples"


@pytest.fixture(scope="session")
def golden_facts(golden_dir) -> Path:
    return golden_dir / "facts.jsonl"


@pytest.fixture(scope="session")
def libclang_path() -> Path:
    from carma.indexers.libclang import discovery

    try:
        return discovery.find_libclang()
    except discovery.LibclangError as exc:
        if REQUIRE_LIBCLANG:
            pytest.fail(str(exc))
        pytest.skip(str(exc))


@pytest.fixture(scope="session")
def cmake() -> str:
    path = shutil.which("cmake")
    if path is None:
        if REQUIRE_LIBCLANG:
            pytest.fail("cmake is not installed")
        pytest.skip("cmake is not installed")
    return path


@pytest.fixture(scope="session")
def golden_build(cmake, golden_dir, tmp_path_factory) -> Path:
    """The reference project configured with CMake's default generator on this OS."""
    build = tmp_path_factory.mktemp("golden") / "build"
    result = subprocess.run([cmake, "-S", str(golden_dir), "-B", str(build)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    return build
