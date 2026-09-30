"""Contract 2: every FactStore implementation answers the same on the reference facts.

Runs on the committed fixtures/golden_cpp/facts.jsonl, so it needs no LLVM.
"""

import json

import pytest

from carma.store.api import FactStore
from carma.store.loader import iter_records, load_facts
from carma.store.sqlite import SQLiteStore

DRAW_SCENE = "cxx golden/render/Renderer#DrawScene()."
REQUEST_LOAD = "cxx golden/streaming/TextureStreamer#RequestLoad(const std::string&)."
ON_LOADED = "cxx golden/streaming/TextureStreamer#OnLoaded(const std::string&)."
UPLOAD = "cxx golden/render/GpuUploader#Upload(const std::string&)."
MAIN = "cxx main()."

# Membership the core would compute from expected/model (path rules, deepest wins).
COMPONENT_BY_PREFIX = [
    ("src/render/backend/", "render.backend"),
    ("src/render/", "render"),
    ("src/streaming/", "streaming"),
    ("src/io/", "io"),
    ("src/core/", "core"),
    ("apps/", "apps"),
]

IMPLEMENTATIONS = {"sqlite": lambda tmp_path: SQLiteStore(tmp_path / "facts.db")}


@pytest.fixture(params=sorted(IMPLEMENTATIONS))
def store(request, tmp_path, golden_facts):
    s = IMPLEMENTATIONS[request.param](tmp_path)
    load_facts(s, golden_facts)
    yield s
    s.close()


def membership(store, golden_facts):
    mapping = []
    for record in iter_records(golden_facts):
        if record["type"] != "symbol" or record["kind"] == "namespace":
            continue
        places = [loc["path"] for loc in record["defs"]] or [loc["path"] for loc in record["decls"]]
        component = "_external"
        if places:
            path = sorted(places)[0]
            component = next((c for prefix, c in COMPONENT_BY_PREFIX if path.startswith(prefix)), "_external")
        mapping.append((record["id"], component))
    return mapping


def test_is_a_fact_store(store):
    assert isinstance(store, FactStore)
    assert store.contract_version == "store/0.1"


def test_stats(store):
    stats = store.stats()
    assert stats.files > 0 and stats.symbols > 0 and stats.refs > 0 and stats.relations == 6
    assert stats.facts_version == "0.1" and stats.platform in ("windows", "macos", "linux")


def test_get_symbol(store):
    symbol = store.get_symbol(DRAW_SCENE)
    assert symbol.kind == "method" and symbol.parent_id == "cxx golden/render/Renderer#"
    assert [loc.path for loc in symbol.defs] == ["src/render/Renderer.cpp"]
    assert [loc.path for loc in symbol.decls] == ["src/render/Renderer.h"]
    assert store.get_symbol("cxx no/Such#") is None


def test_two_definitions_of_main(store):
    assert sorted(loc.path for loc in store.get_symbol(MAIN).defs) == ["apps/app_main.cpp", "apps/tool_main.cpp"]


def test_search_symbols(store):
    found = [s.id for s in store.search_symbols("DrawScene")]
    assert found[0] == DRAW_SCENE
    classes = store.search_symbols("Renderer", kinds=["class"])
    assert classes and all(s.kind == "class" for s in classes)


def test_symbols_in_file_and_list_files(store):
    ids = [s.id for s in store.symbols_in_file("src/render/Renderer.h")]
    assert "cxx golden/render/Renderer#" in ids
    assert store.list_files("src/io/*") == ["src/io/Handles.h", "src/io/IoQueue.cpp", "src/io/IoQueue.h",
                                            "src/io/Platform.cpp", "src/io/Platform.h", "src/io/RingBuffer.h"]


def test_symbol_at_picks_the_innermost(store):
    body_line = store.get_symbol(DRAW_SCENE).defs[0].extent[0] + 2
    assert store.symbol_at("src/render/Renderer.cpp", body_line).id == DRAW_SCENE


def test_refs_to_and_from(store):
    callers = {r.container for r in store.refs_to(ON_LOADED) if "call" in r.roles}
    assert callers == {REQUEST_LOAD}
    outgoing = {(r.symbol, frozenset(r.roles)) for r in store.refs_from(DRAW_SCENE)}
    assert (REQUEST_LOAD, frozenset({"call"})) in outgoing
    assert ("cxx golden/render/OnShutdown().", frozenset({"reference"})) in outgoing


def test_relations(store):
    out = store.relations("cxx golden/render/Mesh#", kind="inherits")
    assert {r.to_id for r in out} == {"cxx golden/core/Component#", "cxx golden/render/IRenderable#"}
    incoming = store.relations("cxx golden/core/Component#GetTypeId()const.", direction="in")
    assert {r.from_id for r in incoming} == {"cxx golden/render/Mesh#GetTypeId()const.",
                                             "cxx golden/streaming/TextureStreamer#GetTypeId()const."}


def test_callers_and_callees(store):
    assert {(e.caller, e.depth) for e in store.callers(ON_LOADED, depth=2)} == {(REQUEST_LOAD, 1), (DRAW_SCENE, 2)}
    assert (ON_LOADED, 1) in {(e.callee, e.depth) for e in store.callees(REQUEST_LOAD)}
    edge = store.callers(UPLOAD)[0]
    assert edge.caller == ON_LOADED and edge.path == "src/streaming/TextureStreamer.cpp"


def test_paths(store):
    assert store.paths(MAIN, UPLOAD) == [[MAIN, DRAW_SCENE, REQUEST_LOAD, ON_LOADED, UPLOAD]]
    assert store.paths(MAIN, UPLOAD, max_depth=2) == []
    assert store.paths(UPLOAD, MAIN) == []


def test_component_edges(store, golden_facts):
    store.set_membership(membership(store, golden_facts))
    edges = {(e.src, e.dst): e for e in store.component_edges()}
    assert edges[("render", "streaming")].calls > 0
    assert edges[("streaming", "render.backend")].calls > 0  # the undeclared dependency
    assert edges[("render", "streaming")].uses > 0  # field of type TextureStreamer
    assert not any("_external" in key for key in edges)
    assert any(e.dst == "_external" for e in store.component_edges(include_external=True))
    samples = store.edge_samples("streaming", "render.backend")
    assert UPLOAD in [s.symbol for s in samples]
    assert {s.path for s in samples} == {"src/streaming/TextureStreamer.cpp"}


def dump(store) -> dict:
    """Everything a reader can see, independent of internal keys."""
    symbols = {}
    for record in iter_records(store._golden):
        if record["type"] == "symbol":
            symbols[record["id"]] = store.get_symbol(record["id"])
    return {
        "stats": (store.stats().files, store.stats().symbols, store.stats().refs, store.stats().relations),
        "symbols": symbols,
        "refs": {sid: store.refs_to(sid) for sid in symbols},
        "relations": {sid: store.relations(sid) for sid in symbols},
        "files": store.list_files(),
    }


def edited(golden_facts, tmp_path):
    """The reference facts after an edit: one file changed, one file gone."""
    changed, removed = "src/render/Renderer.cpp", "src/io/Platform.cpp"
    out = []
    for record in iter_records(golden_facts):
        t = record["type"]
        if t == "file" and record["path"] == removed:
            continue
        if t == "file" and record["path"] == changed:
            record = {**record, "sha256": "0" * 64}
        if t == "ref" and record["path"] in (changed, removed) and record["symbol"] == REQUEST_LOAD:
            continue  # DrawScene no longer requests a texture
        if t == "ref" and record["path"] == removed:
            continue
        if t == "symbol":
            record = {**record, "defs": [l for l in record["defs"] if l["path"] != removed],
                      "decls": [l for l in record["decls"] if l["path"] != removed]}
        if t == "relation" and record["kind"] == "overrides" and "TextureStreamer" in record["from"]:
            continue
        out.append(record)
    out.append({"type": "symbol", "id": "cxx golden/render/NewHelper().", "display_name": "NewHelper", "kind": "function",
                "parent_id": "cxx golden/render/", "defs": [{"path": changed, "range": [60, 0, 60, 9], "extent": [60, 0, 62, 1]}],
                "decls": [], "external": False})
    path = tmp_path / "edited.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in out) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("name", sorted(IMPLEMENTATIONS))
def test_incremental_load_equals_full_load(name, tmp_path, golden_facts):
    new_facts = edited(golden_facts, tmp_path)

    (tmp_path / "a").mkdir()
    incremental = IMPLEMENTATIONS[name](tmp_path / "a")
    load_facts(incremental, golden_facts)
    report = load_facts(incremental, new_facts)
    assert not report.full and 0 < report.files_loaded < report.files_total and report.files_removed == 1

    (tmp_path / "b").mkdir()
    full = IMPLEMENTATIONS[name](tmp_path / "b")
    load_facts(full, new_facts)

    incremental._golden = full._golden = new_facts
    assert dump(incremental) == dump(full)
    assert incremental.get_symbol("cxx golden/io/PlatformRoot().").defs == ()
    assert not any("call" in r.roles for r in incremental.refs_to(REQUEST_LOAD) if r.container == DRAW_SCENE)
    incremental.close()
    full.close()
