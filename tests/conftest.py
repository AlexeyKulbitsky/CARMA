import os
import shutil
import socket
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


def make_golden_project(root: Path, golden_dir: Path, *, model: bool = True) -> Path:
    """The reference project as the core sees it: config, facts loaded into .carma/cache, the expected model."""
    from carma.store.loader import load_facts
    from carma.store.sqlite import SQLiteStore

    carma_dir = root / ".carma"
    carma_dir.mkdir(parents=True)
    shutil.copy(golden_dir / "expected" / "config.yaml", carma_dir / "config.yaml")
    if model:
        shutil.copytree(golden_dir / "expected" / "model", carma_dir / "model")
    with SQLiteStore(carma_dir / "cache" / "facts.db") as store:
        load_facts(store, golden_dir / "facts.jsonl")
    return root


@pytest.fixture
def make_golden(tmp_path, golden_dir):
    """make_golden(model=False) gives the reference project without .carma/model/."""
    return lambda model=True: make_golden_project(tmp_path / "golden", golden_dir, model=model)


@pytest.fixture
def golden_project(make_golden) -> Path:
    return make_golden()


@pytest.fixture
def golden_core(golden_project):
    """A loaded core over the reference facts and the expected model."""
    from carma.config import load_config
    from carma.engine.core import Core
    from carma.store.sqlite import SQLiteStore

    store = SQLiteStore(golden_project / ".carma" / "cache" / "facts.db")
    core = Core(load_config(golden_project), store)
    core.load()
    yield core
    core.close()
    store.close()


@pytest.fixture
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
