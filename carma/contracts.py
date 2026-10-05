"""Access to the contract files: JSON schemas and the MCP tool list.

The source of truth is contracts/ at the repository root; installed builds carry a copy
in carma/_contracts (see pyproject.toml).
"""

from __future__ import annotations

import json
import re
from functools import cache
from importlib import resources
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMAS = ("facts", "model", "config", "layout", "workspace", "execution", "exploration")


def contracts_dir() -> Path:
    packaged = resources.files("carma") / "_contracts"
    if packaged.is_dir():
        return Path(str(packaged))
    return Path(__file__).resolve().parent.parent / "contracts"


@cache
def load_schema(name: str) -> dict:
    if name not in SCHEMAS:
        raise KeyError(f"unknown contract schema: {name}")
    path = contracts_dir() / f"{name}.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


@cache
def validator(name: str) -> Draft202012Validator:
    schema = load_schema(name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validation_errors(name: str, instance: object) -> list[str]:
    """Human-readable validation errors, empty when the instance is valid."""
    errors = sorted(validator(name).iter_errors(instance), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in errors]


@cache
def load_openapi() -> dict:
    """Contract 4: contracts/openapi.yaml, generated from carma/api and committed."""
    from carma.model import yaml_io

    return yaml_io.to_plain(yaml_io.load(contracts_dir() / "openapi.yaml"))


_TOOL_ROW = re.compile(r"^\|\s*`([a-z_]+)`\s*\|")


def mcp_tool_names() -> list[str]:
    """Tool names from the first column of the table in contracts/mcp-tools.md."""
    text = (contracts_dir() / "mcp-tools.md").read_text(encoding="utf-8")
    return [m.group(1) for line in text.splitlines() if (m := _TOOL_ROW.match(line))]
