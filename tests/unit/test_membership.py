"""Membership resolution (spec «Ядро», 1) on small hand-made facts."""

import pytest

from carma.engine.membership import Ambiguity, path_specificity, resolve_membership
from carma.engine.symbols import SymbolInfo, place_of
from carma.engine.tree import ComponentTree
from carma.model.repo import Component
from carma.store.api import Loc, Symbol

IGNORE = ("**/thirdparty/**",)


def ns(sid, name, parent=None):
    return SymbolInfo(sid, name, "namespace", parent, None, None, False, None, False)


def fn(sid, place="src/other/x.cpp", parent=None, external=False):
    return SymbolInfo(sid, sid, "function", parent, None, None, external, place, False)


def component(cid, *members):
    return Component(cid, {"schema_version": "model/0.1", "id": cid, "name": cid, "members": list(members)})


def resolve(symbols, *components):
    by_id = {s.id: s for s in symbols}
    tree = ComponentTree(c.id for c in components)
    return resolve_membership(by_id, components, tree, IGNORE)


NAMESPACES = [ns("eng", "eng"), ns("eng.render", "render", "eng"), ns("eng.anon", "(anonymous)", "eng.render"),
              ns("engine", "engine")]


@pytest.mark.parametrize("glob, expected", [
    ("src/render/**", 2), ("engine/source/*", 2), ("**/tests/**", 0), ("src/render/Renderer.cpp", 3), ("src/re*/x", 1),
])
def test_path_specificity(glob, expected):
    assert path_specificity(glob) == expected


def test_place_is_the_smallest_definition_else_the_smallest_declaration():
    loc = lambda path: Loc(path, (0, 0, 0, 1), (0, 0, 1, 0))  # noqa: E731
    two_defs = Symbol("cxx main().", "main", "function", None, None, None, None, (loc("b/m.cpp"), loc("a/m.cpp")), (), False)
    decls_only = Symbol("cxx f().", "f", "function", None, None, None, None, (), (loc("z.h"), loc("y.h")), False)
    assert place_of(two_defs) == "a/m.cpp"
    assert place_of(decls_only) == "y.h"


def test_deepest_component_wins_and_parent_keeps_its_own_files():
    m = resolve([fn("draw", "src/render/backend/Mesh.cpp"), fn("scene", "src/render/Renderer.cpp")],
                component("render", {"path": "src/render/**"}), component("render.backend", {"path": "src/render/backend/**"}))
    assert m.component_of == {"draw": "render.backend", "scene": "render"}


def test_explicit_symbol_beats_everything():
    m = resolve([fn("hud", "src/render/Hud.cpp"), fn("vendored", "lib/thirdparty/v.cpp")],
                component("render", {"path": "src/render/**"}),
                component("ui", {"symbol": "hud"}, {"symbol": "vendored"}))
    assert m.component_of == {"hud": "ui", "vendored": "ui"}


def test_exclude_hands_the_symbol_to_the_next_candidate():
    symbols = [fn("test_add", "src/inventory/tests/add.cpp"), fn("add", "src/inventory/add.cpp")]
    inventory = {"path": "src/inventory/**"}
    tests = component("tests", {"path": "**/tests/**"})
    assert resolve(symbols, component("inventory", inventory), tests).component_of["test_add"] == "inventory"
    m = resolve(symbols, component("inventory", inventory, {"exclude": {"path": "src/inventory/tests/**"}}), tests)
    assert m.component_of == {"test_add": "tests", "add": "inventory"}
    m = resolve(symbols, component("inventory", inventory, {"exclude": {"symbol": "add"}}))
    assert m.component_of["add"] == "_unassigned"


def test_descendant_beats_a_more_specific_ancestor():
    symbols = [*NAMESPACES, fn("f", "src/gameplay/inventory/f.cpp", parent="eng.render")]
    m = resolve(symbols, component("gameplay", {"path": "src/gameplay/inventory/**"}),
                component("gameplay.inventory", {"namespace": "eng"}))
    assert m.component_of["f"] == "gameplay.inventory"


def test_most_specific_rule_wins_between_unrelated_components():
    symbols = [*NAMESPACES, fn("f", "src/f.cpp", parent="eng.render")]
    m = resolve(symbols, component("src", {"path": "src/**"}), component("render", {"namespace": "eng::render"}))
    assert m.component_of["f"] == "render" and not m.ambiguities


def test_equal_specificity_is_an_ambiguity_resolved_to_the_smaller_id():
    symbols = [*NAMESPACES, fn("f", "src/render/f.cpp", parent="eng.render"), fn("g", "src/render/g.cpp", parent="eng.render")]
    m = resolve(symbols, component("zeta", {"path": "src/render/**"}), component("alpha", {"namespace": "eng::render"}))
    assert m.component_of == {"f": "alpha", "g": "alpha"}
    assert m.ambiguities == [Ambiguity(("alpha", "zeta"), ("f", "g"))]


def test_namespace_rule_covers_nested_namespaces_and_skips_anonymous_ones():
    symbols = [*NAMESPACES, fn("nested", None, parent="eng.anon"), fn("other", None, parent="engine")]
    m = resolve(symbols, component("eng", {"namespace": "eng"}))
    assert m.component_of == {"nested": "eng", "other": "_external"}  # 'eng' is not a prefix of 'engine'; no place


def test_virtual_components_and_namespaces():
    symbols = [*NAMESPACES, fn("loose", "tools/x.cpp"), fn("std_thing", None, external=True),
               fn("vendored", "lib/thirdparty/v.cpp"), fn("no_place", None)]
    m = resolve(symbols, component("src", {"path": "src/**"}))
    assert m.component_of == {"loose": "_unassigned", "std_thing": "_external", "vendored": "_external",
                              "no_place": "_external"}
    assert m.own["_external"] == 3 and m.members["_unassigned"] == ["loose"]


def test_ignore_beats_path_rules():
    m = resolve([fn("vendored", "engine/thirdparty/v.cpp")], component("engine", {"path": "engine/**"}))
    assert m.component_of == {"vendored": "_external"}
