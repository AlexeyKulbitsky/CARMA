"""Checks (spec «Ядро», 3): cycles, dependencies, anchors, emptiness and the fingerprint."""

from carma.engine.checks import Issue, dependency_issues, fingerprint, interface, strongly_connected
from carma.engine.membership import Membership
from carma.engine.symbols import SymbolInfo
from carma.engine.tree import ComponentTree
from carma.model.repo import Component
from carma.store.api import ComponentEdge


def component(cid, **extra):
    return Component(cid, {"schema_version": "model/0.1", "id": cid, "name": cid, "members": [], **extra})


def edge(src, dst, refs=1):
    return ComponentEdge(src, dst, refs, refs, 0)


def test_strongly_connected_components():
    edges = [("a", "b"), ("b", "c"), ("c", "a"), ("c", "d"), ("d", "e"), ("e", "d"), ("f", "f"), ("g", "a")]
    assert strongly_connected(edges) == [("a", "b", "c"), ("d", "e")]
    assert strongly_connected([("a", "b"), ("b", "c")]) == []


def test_long_chain_does_not_recurse():
    edges = [(f"n{i}", f"n{i + 1}") for i in range(5000)] + [("n5000", "n0")]
    assert len(strongly_connected(edges)[0]) == 5001


TREE = ComponentTree(["render", "render.backend", "streaming", "streaming.loader", "io", "core"])


def test_undeclared_target_is_named_as_seen_from_the_parent_level():
    edges = [edge("streaming.loader", "render.backend", 3), edge("streaming", "io"), edge("streaming", "_unassigned")]
    issues = dependency_issues(component("streaming", requires=[{"component": "io"}]), TREE, edges)
    assert issues == [Issue("undeclared_dependency", component="streaming", target="render", count=3)]
    issues = dependency_issues(component("streaming.loader", requires=[]), TREE, edges)
    assert issues == [Issue("undeclared_dependency", component="streaming.loader", target="render", count=3)]


def test_requires_covers_descendants_and_ancestor_own_symbols_need_declaring():
    edges = [edge("render", "streaming.loader"), edge("render.backend", "render")]
    assert dependency_issues(component("render", requires=[{"component": "streaming"}]), TREE, edges) == []
    issues = dependency_issues(component("render.backend", requires=[]), TREE, edges)
    assert issues == [Issue("undeclared_dependency", component="render.backend", target="render._self", count=1)]


def test_missing_dependency_and_components_without_requires():
    edges = [edge("render", "streaming")]
    issues = dependency_issues(component("render", requires=[{"component": "streaming"}, {"component": "io"}]), TREE, edges)
    assert issues == [Issue("missing_dependency", component="render", target="io")]
    assert dependency_issues(component("io"), TREE, [edge("io", "render")]) == []  # requires not declared


def symbol(sid, signature, access="public", header=True):
    return SymbolInfo(sid, sid, "method", None, signature, access, False, "src/a.h" if header else "src/a.cpp", header)


def pairs_of(symbols, comp=None):
    by_id = {s.id: s for s in symbols}
    return interface(comp or component("a"), ComponentTree(["a"]), Membership({s.id: "a" for s in symbols}), by_id)


def test_fingerprint_follows_the_public_header_interface_only():
    base = [symbol("A#Get().", "int Get()"), symbol("A#m_x.", "int m_x", access="private"),
            symbol("Helper().", "void Helper()", access=None, header=False)]
    fp = fingerprint(pairs_of(base))
    internals = [base[0], symbol("A#m_x.", "float m_x", access="private"), symbol("Helper().", "int Helper()", None, False)]
    assert fingerprint(pairs_of(internals)) == fp
    assert fingerprint(pairs_of([symbol("A#Get().", "long Get()"), *base[1:]])) != fp
    assert pairs_of(base) == [("A#Get().", "int Get()")]


def test_fingerprint_uses_provides_and_explicit_symbols_first():
    comp = component("a", members=[{"symbol": "cxx A#"}], provides=[{"interface": "I", "symbols": ["cxx Gone#"]}])
    pairs = pairs_of([symbol("cxx A#", ""), symbol("A#Get().", "int Get()")], comp)
    assert pairs == [("cxx A#", ""), ("cxx Gone#", None)]  # a missing anchor still counts, as null
    assert len(fingerprint(pairs)) == 64
