"""YAML loading for model and config files.

Round-trip mode keeps comments and key order a person added. to_plain() turns the loaded
tree into plain JSON-compatible data for schema validation.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
import io
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML


def _yaml() -> YAML:
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.width = 4096  # never re-wrap long lines a person wrote
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def load(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return _yaml().load(f)


def loads(text: str) -> Any:
    return _yaml().load(text)


def dumps(data: Any) -> str:
    buffer = io.StringIO()
    _yaml().dump(data, buffer)
    return buffer.getvalue()


def to_plain(value: Any) -> Any:
    """Convert ruamel containers and YAML dates to plain dict/list/str values."""
    if isinstance(value, Mapping):
        return {str(k): to_plain(v) for k, v in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [to_plain(v) for v in value]
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value
