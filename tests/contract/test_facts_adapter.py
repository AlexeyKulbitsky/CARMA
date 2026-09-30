"""Contract 1: the libclang adapter on the reference project gives the hand-written answers."""

import json
import sys

import pytest

from carma.compiledb import from_cmake_build
from carma.config import DEFAULT_IGNORE
from carma.contracts import validation_errors
from carma.indexers.libclang.indexer import index_project, platform_name, select_tus


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(scope="module")
def expected(golden_dir):
    folder = golden_dir / "expected"
    return {name: json.loads((folder / f"{name}.json").read_text(encoding="utf-8")) for name in ("symbols", "refs", "relations")}


def run_adapter(golden_dir, golden_build, libclang_path, out, jobs):
    tus, _ = select_tus(from_cmake_build(golden_build), golden_dir, DEFAULT_IGNORE, False)
    report = index_project(golden_dir, tus, out, libclang=libclang_path, ignore=DEFAULT_IGNORE, jobs=jobs)
    return report, read_jsonl(out)


@pytest.fixture(scope="module")
def adapter_run(golden_dir, golden_build, libclang_path, tmp_path_factory):
    return run_adapter(golden_dir, golden_build, libclang_path, tmp_path_factory.mktemp("facts") / "facts.jsonl", jobs=3)


@pytest.fixture(scope="module")
def facts(adapter_run):
    return adapter_run[1]


@pytest.fixture(scope="module")
def symbols(facts):
    return {r["id"]: r for r in facts if r["type"] == "symbol"}


@pytest.fixture(scope="module")
def refs(facts):
    return [r for r in facts if r["type"] == "ref"]


def applies_here(entry) -> bool:
    return "platforms" not in entry or platform_name() in entry["platforms"]


def membership_path(symbol) -> str | None:
    """Definition with the smallest path, else the first declaration (see «Контракт 2»)."""
    for key in ("defs", "decls"):
        if symbol[key]:
            return sorted(loc["path"] for loc in symbol[key])[0]
    return None


def test_every_record_matches_the_schema(facts):
    assert facts[0]["type"] == "header"
    assert facts[0]["platform"] == platform_name()
    for record in facts:
        assert validation_errors("facts", record) == [], record


def test_no_parse_errors(adapter_run):
    report, _ = adapter_run
    assert [(t.path, t.messages) for t in report.tus_with_errors] == []


def test_expected_symbols(expected, symbols):
    problems = []
    for entry in expected["symbols"]["present"]:
        symbol = symbols.get(entry["id"])
        if not applies_here(entry):
            if symbol is not None:
                problems.append(f"{entry['id']}: exists only on {entry['platforms']}")
            continue
        if symbol is None:
            problems.append(f"missing {entry['id']}")
            continue
        if symbol["kind"] != entry["kind"]:
            problems.append(f"{entry['id']}: kind {symbol['kind']} != {entry['kind']}")
        if membership_path(symbol) != entry["at"]:
            problems.append(f"{entry['id']}: lives in {membership_path(symbol)}, expected {entry['at']}")
        if "defs" in entry and sorted(loc["path"] for loc in symbol["defs"]) != sorted(entry["defs"]):
            problems.append(f"{entry['id']}: defs {[loc['path'] for loc in symbol['defs']]} != {entry['defs']}")
        if "external" in entry and symbol["external"] != entry["external"]:
            problems.append(f"{entry['id']}: external {symbol['external']}")
    assert problems == []


def test_no_local_or_machine_specific_names_in_ids(expected, symbols):
    forbidden = expected["symbols"]["absent_substrings"]["values"]
    leaks = [(sid, bad) for sid, s in symbols.items() if not s["external"] for bad in forbidden if bad in sid]
    assert leaks == []


def has_ref(refs, source, target, role, path=None):
    return any(
        r["symbol"] == target and r["container"] == source and role in r["roles"] and (path is None or r["path"] == path)
        for r in refs
    )


def test_expected_calls(expected, refs):
    missing = [c for c in expected["refs"]["calls"] if not has_ref(refs, c["from"], c["to"], "call", c["at"])]
    assert missing == []


def test_expected_references(expected, refs):
    missing = [c for c in expected["refs"]["references"] if not has_ref(refs, c["from"], c["to"], "reference", c["at"])]
    assert missing == []


def test_calls_that_must_not_exist(expected, refs):
    present = [c for c in expected["refs"]["not_calls"] if has_ref(refs, c["from"], c["to"], "call")]
    assert present == []


def test_expected_relations(expected, facts):
    relations = {(r["from"], r["to"], r["kind"]) for r in facts if r["type"] == "relation"}
    missing = [r for r in expected["relations"]["relations"] if (r["from"], r["to"], r["kind"]) not in relations]
    assert missing == []


def test_every_ref_target_has_a_symbol(symbols, refs):
    assert sorted({r["symbol"] for r in refs} - set(symbols)) == []


def test_ranges_are_inside_files(golden_dir, facts):
    lines = {}
    problems = []
    for record in facts:
        places = []
        if record["type"] == "ref":
            places = [(record["path"], record["range"])]
        elif record["type"] == "symbol":
            places = [(loc["path"], r) for loc in record["defs"] + record["decls"] for r in (loc["range"], loc["extent"])]
        for path, rng in places:
            if path not in lines:
                lines[path] = (golden_dir / path).read_text(encoding="utf-8").count("\n") + 1
            if rng[0] >= lines[path] or rng[2] >= lines[path]:
                problems.append((path, rng))
    assert problems == []


def test_project_ids_match_the_committed_stream(expected, symbols, golden_facts):
    """The same code gives the same IDs on every OS (the committed stream comes from Windows)."""
    platform_only = {e["id"] for e in expected["symbols"]["present"] if "platforms" in e}
    committed = {r["id"] for r in read_jsonl(golden_facts) if r["type"] == "symbol" and not r["external"]}
    fresh = {sid for sid, s in symbols.items() if not s["external"]}
    assert sorted(fresh - platform_only) == sorted(committed - platform_only)


def test_worker_count_does_not_change_the_output(golden_dir, golden_build, libclang_path, tmp_path, adapter_run):
    _, single = run_adapter(golden_dir, golden_build, libclang_path, tmp_path / "facts.jsonl", jobs=1)
    _, parallel = adapter_run
    assert single == parallel


@pytest.mark.skipif(sys.platform != "win32", reason="MSVC-style command lines exist only on Windows")
def test_msvc_commands_parse_in_cl_mode(golden_dir, golden_build):
    tus, _ = select_tus(from_cmake_build(golden_build, reconfigure=False), golden_dir, DEFAULT_IGNORE, False)
    assert tus and all(cmd.cl_mode for cmd in tus)
