"""The core on the reference project: membership, checks, views and highlight against expected/.

Runs on the committed facts.jsonl, so it needs no LLVM.
"""

import dataclasses
import json

import pytest

from carma.engine.core import Core
from carma.engine.highlight import HighlightError
from carma.engine.views import UnknownScope
from carma.store.loader import read_header

DRAW_SCENE = "cxx golden/render/Renderer#DrawScene()."
REQUEST_LOAD = "cxx golden/streaming/TextureStreamer#RequestLoad(const std::string&)."
UPLOAD = "cxx golden/render/GpuUploader#Upload(const std::string&)."


@pytest.fixture(scope="module")
def expected(golden_dir):
    load = lambda name: json.loads((golden_dir / "expected" / name).read_text(encoding="utf-8"))  # noqa: E731
    return {"symbols": load("symbols.json"), "checks": load("checks.json")}


def test_membership_matches_expected_owners(golden_core, expected, golden_facts):
    platform = read_header(golden_facts).platform
    component_of = golden_core.state.membership.component_of
    for entry in expected["symbols"]["present"]:
        if platform not in entry.get("platforms", [platform]):
            continue
        assert component_of.get(entry["id"]) == entry["component"], entry["id"]
    assert golden_core.state.membership.own["_unassigned"] == 0


def test_checks_find_exactly_the_planted_issues(golden_core, expected):
    root = expected["checks"]["root"]
    found = {}
    for issue in golden_core.issues():
        if issue.code == "undeclared_dependency":
            found.setdefault(issue.code, []).append([issue.component, issue.target])
        elif issue.code == "cycle" and issue.scope == "root":
            found.setdefault(issue.code, []).append(list(issue.members))
        else:
            pytest.fail(f"unexpected issue: {issue.describe()}")
    assert found == {k: v for k, v in root.items() if not k.startswith("$")}


def test_declaring_the_dependency_leaves_only_the_cycle(golden_core):
    golden_core.patch_component("streaming", {"requires": [{"component": "io"}, {"component": "core"},
                                                           {"component": "render"}]})
    assert [(i.code, i.members) for i in golden_core.issues()] == [("cycle", ("render", "streaming"))]


def test_root_view(golden_core):
    view = golden_core.view("root")
    assert [n.id for n in view.nodes] == ["apps", "core", "io", "render", "streaming"]
    render = next(n for n in view.nodes if n.id == "render")
    assert (render.kind, render.children, render.intent_short) == ("subsystem", 1, "Draws the scene and requests textures.")
    assert render.symbols == 24  # its own 14 and render.backend's 10
    edges = {(e.src, e.dst): e for e in view.edges}
    assert set(edges["streaming", "render"].issues) == {"undeclared_dependency", "cycle"}
    assert not edges["streaming", "render"].declared
    assert edges["render", "streaming"].declared and edges["render", "streaming"].issues == ("cycle",)
    assert edges["render", "streaming"].uses > 0  # the field of type TextureStreamer
    assert edges["streaming", "io"].issues == () and view.boundary == ()


def test_parent_level_shows_children_and_self(golden_core, expected):
    view = golden_core.view("render")
    assert sorted(n.id for n in view.nodes) == expected["checks"]["render"]["nodes"]
    assert next(n for n in view.nodes if n.type == "self").symbols == 14
    assert {n.id for n in view.boundary} == {"apps", "core", "streaming"}
    edges = {(e.src, e.dst) for e in view.edges}
    assert ("streaming", "render.backend") in edges and ("render.backend", "render._self") in edges
    backend_to_core = next(e for e in view.edges if (e.src, e.dst) == ("render.backend", "core"))
    assert backend_to_core.declared  # through render's requires


def test_leaf_level_shows_symbols_by_file(golden_core):
    view = golden_core.view("render._self")
    assert view.level == "symbols"
    nodes = {n.id: n for n in view.nodes}
    renderer = nodes["cxx golden/render/Renderer#"]
    assert renderer.file == "src/render/Renderer.h" and renderer.symbols == 8  # the class, its methods and fields
    assert DRAW_SCENE not in nodes  # methods rise to their class
    assert {n.id for n in view.boundary} == {"apps", "core", "render.backend", "streaming"}
    edges = {(e.src, e.dst): e for e in view.edges}
    assert edges["cxx golden/render/Renderer#", "streaming"].declared
    assert edges["cxx golden/render/Renderer#", "cxx golden/render/OnShutdown()."].calls == 0  # address taken only


def test_large_levels_are_grouped(golden_core):
    def io_view(max_nodes):
        core = Core(dataclasses.replace(golden_core.config, max_nodes=max_nodes), golden_core.store)
        return core.view("io")

    view = io_view(3)
    assert view.grouped_by == "folder" and [n.id for n in view.nodes] == ["folder:src/io"]
    assert view.nodes[0].symbols == golden_core.state.membership.own["io"]
    view = io_view(6)
    assert view.grouped_by == "file" and "file:src/io/IoQueue.h" in {n.id for n in view.nodes}
    edges = {(e.src, e.dst) for e in view.edges}
    assert ("streaming", "file:src/io/IoQueue.h") in edges


def test_unassigned_symbols_show_up(golden_core):
    golden_core.delete_component("apps")
    root = golden_core.view("root")
    assert root.nodes[-1].id == "_unassigned" and root.nodes[-1].symbols == 1
    assert [n.id for n in golden_core.view("_unassigned").nodes] == ["cxx main()."]


def test_unknown_scope(golden_core):
    for scope in ("nope", "_external", "nope._self"):
        with pytest.raises(UnknownScope):
            golden_core.view(scope)


HIGHLIGHT = {
    "title": "Texture request",
    "steps": [
        {"symbols": [DRAW_SCENE], "caption": "The renderer asks for a texture"},
        {"symbols": [REQUEST_LOAD], "caption": "The request is queued"},
        {"components": ["io"], "caption": "IO reads the file"},
        {"symbols": [UPLOAD, "cxx no/Such#"], "components": ["nope"], "caption": "Upload"},
    ],
}


@pytest.mark.parametrize("scope, nodes", [
    ("root", [["render"], ["streaming"], ["io"], ["render"]]),
    ("render", [["render._self"], ["streaming"], [], ["render.backend"]]),
    ("render._self", [["cxx golden/render/Renderer#"], ["streaming"], [], ["render.backend"]]),
    # render._self is a boundary node here: Mesh implements IRenderable
    ("render.backend", [["render._self"], ["streaming"], [], ["cxx golden/render/GpuUploader#"]]),
])
def test_highlight_rises_to_the_open_level(golden_core, scope, nodes):
    golden_core.set_highlight(HIGHLIGHT)
    lifted = golden_core.highlight(scope)
    assert [list(step.nodes) for step in lifted.steps] == nodes
    assert lifted.steps[3].unresolved == ("cxx no/Such#", "nope")


def test_highlight_component_containing_the_level_gives_no_node(golden_core):
    golden_core.set_highlight({"title": "t", "steps": [{"components": ["render"], "caption": "all of render"}]})
    assert golden_core.highlight("root").steps[0].nodes == ("render",)
    assert golden_core.highlight("render.backend").steps[0].nodes == ()


def test_highlight_validation_and_events(golden_core):
    events = []
    golden_core.subscribe(events.append)
    with pytest.raises(HighlightError) as info:
        golden_core.set_highlight({"title": "", "steps": [{"caption": "x"}], "extra": 1})
    assert len(info.value.errors) == 3
    golden_core.set_highlight(HIGHLIGHT)
    golden_core.clear_highlight()
    assert golden_core.highlight("root") is None and events == ["highlight_changed", "highlight_changed"]
