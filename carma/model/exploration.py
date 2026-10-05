"""Persist exploration independently of a rendering implementation."""

from pathlib import Path

from carma.contracts import validation_errors
from carma.model.json_io import read_json, write_json
from carma.model.repo import ModelValidationError


def load_exploration(carma_dir: Path) -> dict:
    data = read_json(carma_dir / "exploration.json", {"schema_version": "exploration/0.2", "mode": "execution", "entry": None, "views": {}})
    if data.get("schema_version") == "exploration/0.1":
        data = {**data, "schema_version": "exploration/0.2"}
    errors = validation_errors("exploration", data)
    if errors:
        raise ModelValidationError(errors)
    return data


def save_exploration(carma_dir: Path, data: dict) -> dict:
    errors = validation_errors("exploration", data)
    if errors:
        raise ModelValidationError(errors)
    write_json(carma_dir / "exploration.json", data)
    return data
