"""Checks (spec «Ядро», 3): the model against the facts."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from carma.engine.aggregation import level_edges
from carma.engine.membership import Membership
from carma.engine.symbols import SymbolInfo
from carma.engine.tree import VIRTUAL, ComponentTree
from carma.model.repo import Component, ModelSnapshot
from carma.store.api import ComponentEdge

CODES = ("invalid_model", "broken_anchor", "ambiguous_membership", "empty", "stale", "missing_dependency",
         "undeclared_dependency", "cycle")
EDGE_CODES = frozenset({"undeclared_dependency", "cycle"})  # shown on edges, the rest on nodes


@dataclass(frozen=True)
class Issue:
    code: str
    component: str | None = None  # the component it belongs to; None for cycles and ambiguities
    target: str | None = None  # dependency issues: the other node; invalid_model: the file
    members: tuple[str, ...] = ()  # cycle: nodes of the level; ambiguous_membership: tied components
    scope: str | None = None  # cycle: the level it was found on
    symbols: tuple[str, ...] = ()  # broken_anchor: missing IDs; ambiguous_membership: the symbols
    count: int = 0  # refs behind an undeclared dependency, symbols behind an ambiguity
    message: str = ""

    def concerns(self, component_id: str) -> bool:
        return self.component == component_id or (self.code == "ambiguous_membership" and component_id in self.members)

    def describe(self) -> str:
        if self.code == "undeclared_dependency":
            return f"{self.component} -> {self.target}: not in requires ({self.count} refs)"
        if self.code == "missing_dependency":
            return f"{self.component} -> {self.target}: in requires, but nothing refers to it"
        if self.code == "cycle":
            return f"{' <-> '.join(self.members)} (level {self.scope})"
        if self.code == "broken_anchor":
            return f"{self.component}: not in the facts: {', '.join(self.symbols)}"
        if self.code == "ambiguous_membership":
            return (f"{', '.join(self.members)}: {self.count} symbols match with equal specificity and go to "
                    f"{self.members[0]}, e.g. {self.symbols[0]}")
        if self.code == "empty":
            return f"{self.component}: lifecycle current, but no symbols"
        return f"{self.component or self.target}: {self.message}"


def sort_key(issue: Issue) -> tuple:
    return (CODES.index(issue.code), issue.component or "", issue.scope or "", issue.target or "", issue.members)


# ---------------------------------------------------------------- cycles


def strongly_connected(edges: Iterable[tuple[str, str]]) -> list[tuple[str, ...]]:
    """Strongly connected components with more than one node (Tarjan), each sorted, in sorted order."""
    graph: dict[str, list[str]] = defaultdict(list)
    for a, b in edges:
        graph[a].append(b)
        graph.setdefault(b, [])
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    found: list[tuple[str, ...]] = []
    for start in sorted(graph):
        if start in index:
            continue
        work = [(start, iter(sorted(graph[start])))]
        index[start] = low[start] = len(index)
        stack.append(start)
        on_stack.add(start)
        while work:
            node, successors = work[-1]
            advanced = False
            for succ in successors:
                if succ not in index:
                    index[succ] = low[succ] = len(index)
                    stack.append(succ)
                    on_stack.add(succ)
                    work.append((succ, iter(sorted(graph[succ]))))
                    advanced = True
                    break
                if succ in on_stack:
                    low[node] = min(low[node], index[succ])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                scc = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    scc.append(member)
                    if member == node:
                        break
                if len(scc) > 1:
                    found.append(tuple(sorted(scc)))
    return sorted(found)


def cycle_issues(tree: ComponentTree, edges: list[ComponentEdge]) -> list[Issue]:
    issues = []
    for scope in tree.levels():
        internal = [(e.src, e.dst) for e in level_edges(edges, tree, scope)
                    if not (e.src_boundary or e.dst_boundary or e.src in VIRTUAL or e.dst in VIRTUAL)]
        issues += [Issue("cycle", scope=scope, members=scc) for scc in strongly_connected(internal)]
    return issues


# ---------------------------------------------------------------- dependencies


def covers(requires: Iterable[str], target: str, tree: ComponentTree) -> bool:
    """`requires: B` covers B and all its descendants."""
    return any(r == target or tree.is_ancestor(r, target) for r in requires if r in tree)


def dependency_issues(component: Component, tree: ComponentTree, edges: list[ComponentEdge]) -> list[Issue]:
    cid = component.id
    outgoing: dict[str, int] = defaultdict(int)
    for e in edges:
        if e.dst not in VIRTUAL and tree.within(e.src, cid) and not tree.within(e.dst, cid):
            outgoing[e.dst] += e.refs
    issues = []
    if component.declares_requires:
        undeclared: dict[str, int] = defaultdict(int)
        for target, refs in outgoing.items():
            if not covers(component.requires, target, tree):
                undeclared[tree.node_at(tree.parent[cid], target)[0]] += refs
        issues += [Issue("undeclared_dependency", component=cid, target=node, count=refs)
                   for node, refs in sorted(undeclared.items())]
    for required in component.requires:
        if not any(target == required or tree.is_ancestor(required, target) for target in outgoing):
            issues.append(Issue("missing_dependency", component=cid, target=required))
    return issues


# ---------------------------------------------------------------- fingerprint


def interface(component: Component, tree: ComponentTree, membership: Membership,
              symbols: Mapping[str, SymbolInfo]) -> list[tuple[str, str | None]]:
    """(ID, signature) pairs: provides and explicit symbols, else the public header symbols of the subtree."""
    explicit = sorted(set(component.symbol_rules + component.provided_symbols))
    if explicit:
        return [(sid, (symbols[sid].signature or "") if sid in symbols else None) for sid in explicit]
    pairs = []
    for cid in tree.subtree(component.id):
        for sid in membership.members.get(cid, ()):
            info = symbols[sid]
            if info.in_header and info.access in (None, "public"):
                pairs.append((sid, info.signature or ""))
    return sorted(pairs)


def fingerprint(pairs: list[tuple[str, str | None]]) -> str:
    text = json.dumps(pairs, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- all checks


def run_checks(model: ModelSnapshot, tree: ComponentTree, membership: Membership, symbols: Mapping[str, SymbolInfo],
               edges: list[ComponentEdge], subtree_symbols: Mapping[str, int]) -> list[Issue]:
    """Every issue of every component and every level, in a stable order."""
    issues = [Issue("invalid_model", target=name, message="; ".join(errors)) for name, errors in model.invalid.items()]
    for cid, component in model.components.items():
        missing = sorted({sid for sid in component.anchors if sid not in symbols})
        if missing:
            issues.append(Issue("broken_anchor", component=cid, symbols=tuple(missing)))
        if component.lifecycle == "current" and not subtree_symbols.get(cid):
            issues.append(Issue("empty", component=cid))
        stored = component.fingerprint
        if stored:
            current = fingerprint(interface(component, tree, membership, symbols))
            if not current.startswith(stored):
                issues.append(Issue("stale", component=cid,
                                    message=f"interface changed: sync.fingerprint {stored}, now {current[:len(stored)]}"))
        issues += dependency_issues(component, tree, edges)
    for amb in membership.ambiguities:
        issues.append(Issue("ambiguous_membership", members=amb.components, symbols=amb.symbols, count=len(amb.symbols)))
    issues += cycle_issues(tree, edges)
    return sorted(issues, key=sort_key)
