"""Plain viewing state. No renderer-specific objects or browser storage."""

from pathlib import Path

from carma.model.json_io import read_json, write_json
from carma.contracts import validation_errors
from carma.model.repo import ModelValidationError

VERSION = "workspace/0.1"


def load_workspace(carma_dir: Path) -> dict:
    data = read_json(carma_dir / "workspace.json", {"schema_version": VERSION, "scope": "root", "views": {}})
    errors = validation_errors("workspace", data)
    if errors:
        raise ModelValidationError(errors)
    return data


def save_workspace(carma_dir: Path, data: dict) -> dict:
    errors = validation_errors("workspace", data)
    if errors:
        raise ModelValidationError(errors)
    write_json(carma_dir / "workspace.json", data)
    return data
