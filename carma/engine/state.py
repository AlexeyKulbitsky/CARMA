"""Everything the core computes from one model and one set of facts (spec «Конвейер пересчёта»)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from carma.engine.checks import Issue, run_checks
from carma.engine.membership import Membership, resolve_membership
from carma.engine.symbols import SymbolInfo
from carma.engine.tree import UNASSIGNED, ComponentTree
from carma.model.layout import Positions
from carma.model.repo import ModelSnapshot
from carma.store.api import ComponentEdge, FactStore


@dataclass(frozen=True)
class State:
    model: ModelSnapshot
    tree: ComponentTree
    symbols: Mapping[str, SymbolInfo]
    membership: Membership
    edges: list[ComponentEdge]  # between assigned components, _external left out
    subtree_symbols: Mapping[str, int]  # component -> symbols of the component and its descendants
    issues: list[Issue]
    layout: Mapping[str, Positions]
    max_nodes: int

    def issues_of(self, component_id: str) -> list[Issue]:
        return [i for i in self.issues if i.concerns(component_id)]


def build_state(model: ModelSnapshot, symbols: Mapping[str, SymbolInfo], store: FactStore, *, ignore: tuple[str, ...],
                layout: Mapping[str, Positions], max_nodes: int) -> State:
    """Membership -> store edges -> checks. The store keeps the membership for its edge queries."""
    tree = ComponentTree(model.components)
    membership = resolve_membership(symbols, model.components.values(), tree, ignore)
    store.set_membership(sorted(membership.component_of.items()))
    edges = store.component_edges()
    subtree = {cid: sum(membership.own[c] for c in tree.subtree(cid)) for cid in tree.ids}
    subtree[UNASSIGNED] = membership.own[UNASSIGNED]
    issues = run_checks(model, tree, membership, symbols, edges, subtree)
    return State(model=model, tree=tree, symbols=symbols, membership=membership, edges=edges, subtree_symbols=subtree,
                 issues=issues, layout=layout, max_nodes=max_nodes)
