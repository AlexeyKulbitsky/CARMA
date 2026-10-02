"""Atomic JSON documents without a dependency on any client or application service."""

import json
from pathlib import Path

from carma.model.files import write_atomic


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    write_atomic(path, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
