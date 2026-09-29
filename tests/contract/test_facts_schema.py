"""Contract 1: every record of a fact stream matches facts.schema.json."""

import copy
import json

import pytest

from carma.contracts import validation_errors


@pytest.fixture(scope="module")
def records(samples_dir):
    lines = (samples_dir / "facts_valid.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def first(records, record_type):
    candidates = [r for r in records if r["type"] == record_type]
    if record_type == "symbol":
        candidates = [r for r in candidates if r["defs"]]
    return copy.deepcopy(candidates[0])


def test_stream_starts_with_header(records):
    assert records[0]["type"] == "header"


def test_valid_records(records):
    for record in records:
        assert validation_errors("facts", record) == [], record


INVALID = [
    ("header without platform", "header", lambda r: r.pop("platform")),
    ("unknown platform", "header", lambda r: r.update(platform="wsl")),
    ("absolute path", "file", lambda r: r.update(path="C:/src/a.cpp")),
    ("posix absolute path", "file", lambda r: r.update(path="/src/a.cpp")),
    ("backslash in path", "file", lambda r: r.update(path="src\\a.cpp")),
    ("parent segment in path", "file", lambda r: r.update(path="src/../a.cpp")),
    ("short sha256", "file", lambda r: r.update(sha256="abc")),
    ("id without scheme", "symbol", lambda r: r.update(id="golden/render/Renderer#")),
    ("unknown kind", "symbol", lambda r: r.update(kind="klass")),
    ("v0 single def field", "symbol", lambda r: r.update({"def": {"path": "a.cpp", "range": [0, 0, 0, 1]}})),
    ("location without extent", "symbol", lambda r: r["defs"][0].pop("extent")),
    ("unknown access", "symbol", lambda r: r.update(access="internal")),
    ("doc over 2 KB", "symbol", lambda r: r.update(doc="x" * 2049)),
    ("range of three numbers", "ref", lambda r: r.update(range=[0, 0, 1])),
    ("negative line", "ref", lambda r: r.update(range=[-1, 0, 0, 1])),
    ("unknown role", "ref", lambda r: r.update(roles=["calls"])),
    ("empty roles", "ref", lambda r: r.update(roles=[])),
    ("duplicate roles", "ref", lambda r: r.update(roles=["call", "call"])),
    ("missing container key", "ref", lambda r: r.pop("container")),
    ("unknown relation kind", "relation", lambda r: r.update(kind="implements")),
    ("unknown record type", "relation", lambda r: r.update(type="edge")),
]


@pytest.mark.parametrize("record_type,mutate", [c[1:] for c in INVALID], ids=[c[0] for c in INVALID])
def test_invalid_record(records, record_type, mutate):
    record = first(records, record_type)
    mutate(record)
    assert validation_errors("facts", record)
