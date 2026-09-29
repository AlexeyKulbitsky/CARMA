"""The hand-written answers in fixtures/golden_cpp/expected are consistent with each other and the fixture."""

import json
import re

import pytest

from carma.contracts import validation_errors
from carma.model import yaml_io

SYMBOL_ID = re.compile(r"^cxx \S.*$")
VIRTUAL_COMPONENTS = {"_external", "_unassigned"}


@pytest.fixture(scope="module")
def expected(golden_dir):
    folder = golden_dir / "expected"
    load = lambda name: json.loads((folder / name).read_text(encoding="utf-8"))  # noqa: E731
    return {
        "symbols": load("symbols.json"),
        "refs": load("refs.json"),
        "relations": load("relations.json"),
        "checks": load("checks.json"),
        "model": {
            p.stem: yaml_io.to_plain(yaml_io.load(p)) for p in sorted((folder / "model").glob("*.yaml"))
        },
    }


@pytest.fixture(scope="module")
def symbol_ids(expected):
    return {s["id"] for s in expected["symbols"]["present"]}


def test_symbol_ids_are_well_formed(expected):
    forbidden = expected["symbols"]["absent_substrings"]["values"]
    seen = set()
    for s in expected["symbols"]["present"]:
        assert SYMBOL_ID.match(s["id"]), s["id"]
        assert s["id"] not in seen, f"duplicate {s['id']}"
        seen.add(s["id"])
        for bad in forbidden:
            assert bad not in s["id"], f"{s['id']} contains {bad!r}"


def test_symbol_locations_exist(expected, golden_dir):
    for s in expected["symbols"]["present"]:
        paths = ([s["at"]] if s["at"] else []) + s.get("defs", [])
        for path in paths:
            assert (golden_dir / path).is_file(), f"{s['id']}: {path}"


def test_refs_and_relations_use_known_symbols(expected, symbol_ids, golden_dir):
    for group in ("calls", "references", "not_calls"):
        for ref in expected["refs"][group]:
            assert ref["to"] in symbol_ids, ref
            assert ref["from"] is None or ref["from"] in symbol_ids, ref
            if "at" in ref:
                assert (golden_dir / ref["at"]).is_file(), ref
    for rel in expected["relations"]["relations"]:
        assert rel["from"] in symbol_ids and rel["to"] in symbol_ids, rel


def test_calls_and_not_calls_do_not_overlap(expected):
    calls = {(r["from"], r["to"]) for r in expected["refs"]["calls"]}
    for r in expected["refs"]["not_calls"]:
        assert (r["from"], r["to"]) not in calls, r


def test_model_is_valid_and_owns_every_symbol(expected):
    model = expected["model"]
    for component_id, data in model.items():
        assert validation_errors("model", data) == [], component_id
        for req in data.get("requires", []):
            assert req["component"] in model, f"{component_id} requires unknown {req['component']}"
    for s in expected["symbols"]["present"]:
        owner = s["component"]
        assert owner is None or owner in model or owner in VIRTUAL_COMPONENTS, s


def test_expected_checks_name_known_components(expected):
    model = expected["model"]
    for pairs in expected["checks"]["root"].values():
        for pair in pairs:
            assert all(c in model for c in pair), pair
