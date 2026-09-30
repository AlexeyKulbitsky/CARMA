"""Component tree and component card for the View API (spec «Контракт 4»)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from carma.engine.checks import EDGE_CODES, Issue, fingerprint, interface
from carma.engine.state import State
from carma.engine.symbols import SymbolInfo
from carma.engine.tree import ROOT
from carma.engine.views import declared
from carma.model.repo import UnknownComponentError


@dataclass(frozen=True)
class TreeNode:
    id: str
    name: str
    kind: str
    lifecycle: str
    symbols: int  # with descendants
    own_symbols: int
    issues: tuple[str, ...]
    children: tuple[TreeNode, ...]


@dataclass(frozen=True)
class DependencyEdge:
    node: str  # the other end, named as seen from the parent's level
    refs: int
    calls: int
    uses: int
    declared: bool


@dataclass(frozen=True)
class ComponentCard:
    id: str
    parent: str
    children: tuple[str, ...]
    data: dict  # the component file as plain data
    symbols: int
    own_symbols: int
    issues: tuple[Issue, ...]
    interface: tuple[tuple[str, SymbolInfo | None], ...]  # (ID, symbol or None when it is not in the facts)
    fingerprint: str  # current value, the way sync.fingerprint stores it
    edges_out: tuple[DependencyEdge, ...]
    edges_in: tuple[DependencyEdge, ...]


FINGERPRINT_LENGTH = 16  # the core writes the first 16 hex digits (spec «Проверки»)


def component_tree(state: State, parent: str = ROOT) -> tuple[TreeNode, ...]:
    if parent != ROOT and parent not in state.model.components:
        raise UnknownComponentError(parent)

    def node(cid: str) -> TreeNode:
        component = state.model.components[cid]
        codes = sorted({i.code for i in state.issues_of(cid) if i.code not in EDGE_CODES})
        return TreeNode(cid, component.name, component.kind, component.lifecycle, state.subtree_symbols.get(cid, 0),
                        state.membership.own[cid], tuple(codes), tuple(node(c) for c in state.tree.children[cid]))

    return tuple(node(cid) for cid in state.tree.children[parent])


def component_card(state: State, cid: str) -> ComponentCard:
    component = state.model.components.get(cid)
    if component is None:
        raise UnknownComponentError(cid)
    tree = state.tree
    level = tree.parent[cid]
    out: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    into: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for e in state.edges:
        inside_src, inside_dst = tree.within(e.src, cid), tree.within(e.dst, cid)
        if inside_src and not inside_dst:  # state.edges has no _external
            total = out[tree.node_at(level, e.dst)[0]]
        elif inside_dst and not inside_src:
            total = into[tree.node_at(level, e.src)[0]]
        else:
            continue
        total[0] += e.refs
        total[1] += e.calls
        total[2] += e.uses
    pairs = interface(component, tree, state.membership, state.symbols)
    return ComponentCard(
        id=cid,
        parent=level,
        children=tuple(tree.children[cid]),
        data=component.data,
        symbols=state.subtree_symbols.get(cid, 0),
        own_symbols=state.membership.own[cid],
        issues=tuple(state.issues_of(cid)),
        interface=tuple((sid, state.symbols.get(sid)) for sid, _ in pairs),
        fingerprint=fingerprint(pairs)[:FINGERPRINT_LENGTH],
        edges_out=tuple(DependencyEdge(n, *m, declared(state, cid, n)) for n, m in sorted(out.items())),
        edges_in=tuple(DependencyEdge(n, *m, declared(state, n, cid)) for n, m in sorted(into.items())),
    )
