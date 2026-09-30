"""Contract 3: .carma/layout.json, the node positions a person pinned by dragging."""

from __future__ import annotations

import json
from pathlib import Path

from carma.contracts import validation_errors
from carma.model.files import newline_of, write_atomic
from carma.model.repo import ModelValidationError

LAYOUT_FILE = "layout.json"
LAYOUT_VERSION = "0.1"

Positions = dict[str, dict[str, float]]  # node ID -> {"x": .., "y": ..}


def load_layout(carma_dir: Path) -> dict[str, Positions]:
    """Pinned positions per scope; a missing file means nothing is pinned."""
    path = carma_dir / LAYOUT_FILE
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    errors = validation_errors("layout", data)
    if errors:
        raise ModelValidationError([f"{LAYOUT_FILE}: {e}" for e in errors])
    return data["views"]


def save_layout(carma_dir: Path, scope: str, positions: Positions) -> dict[str, Positions]:
    """Replace the pinned positions of one scope; an empty mapping unpins the whole scope."""
    path = carma_dir / LAYOUT_FILE
    views = load_layout(carma_dir)
    if positions:
        views[scope] = positions
    else:
        views.pop(scope, None)
    data = {"layout_version": LAYOUT_VERSION, "views": views}
    errors = validation_errors("layout", data)
    if errors:
        raise ModelValidationError(errors)
    write_atomic(path, json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", newline_of(path))
    return views
