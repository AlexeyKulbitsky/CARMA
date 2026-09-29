from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def golden_dir() -> Path:
    return REPO_ROOT / "fixtures" / "golden_cpp"


@pytest.fixture(scope="session")
def samples_dir() -> Path:
    return REPO_ROOT / "tests" / "contract" / "samples"
