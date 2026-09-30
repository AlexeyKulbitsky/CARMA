"""The component hierarchy and the node that stands for a component on a given level."""

from __future__ import annotations

from collections.abc import Iterable

ROOT = "root"
UNASSIGNED = "_unassigned"
EXTERNAL = "_external"
VIRTUAL = frozenset({UNASSIGNED, EXTERNAL})
SELF_SUFFIX = "._self"


def self_node(component_id: str) -> str:
    return component_id + SELF_SUFFIX


def is_self_node(node_id: str) -> bool:
    return node_id.endswith(SELF_SUFFIX)


def owner(node_id: str) -> str:
    """The component a level node belongs to: 'render._self' -> 'render'."""
    return node_id[: -len(SELF_SUFFIX)] if is_self_node(node_id) else node_id


class ComponentTree:
    """Parents by ID prefix: the closest existing component, otherwise the root.

    `_unassigned` hangs under the root like a top-level component; `_external` is not in the tree.
    """

    def __init__(self, component_ids: Iterable[str]):
        ids = sorted(set(component_ids))
        known = set(ids)
        self.parent: dict[str, str] = {UNASSIGNED: ROOT}
        for cid in ids:
            parts = cid.split(".")
            self.parent[cid] = next((p for p in (".".join(parts[:n]) for n in range(len(parts) - 1, 0, -1)) if p in known),
                                    ROOT)
        self.children: dict[str, list[str]] = {ROOT: []}
        for cid in ids:
            self.children.setdefault(cid, [])
            self.children.setdefault(self.parent[cid], []).append(cid)
        self.ids = ids

    def __contains__(self, component_id: str) -> bool:
        return component_id in self.parent

    def has_children(self, component_id: str) -> bool:
        return bool(self.children.get(component_id))

    def chain(self, component_id: str) -> list[str]:
        """The component and its ancestors up to the top level, the root not included."""
        chain = [component_id]
        while self.parent[chain[-1]] != ROOT:
            chain.append(self.parent[chain[-1]])
        return chain

    def is_ancestor(self, ancestor: str, component_id: str) -> bool:
        """True when ancestor is a proper ancestor of component_id; the root is everyone's ancestor."""
        if ancestor == ROOT:
            return component_id != ROOT
        return component_id in self.parent and ancestor in self.chain(component_id)[1:]

    def within(self, component_id: str, scope: str) -> bool:
        """component_id is scope or lies below it."""
        return component_id == scope or self.is_ancestor(scope, component_id)

    def subtree(self, component_id: str) -> list[str]:
        """The component and all its descendants."""
        result, stack = [], [component_id]
        while stack:
            cid = stack.pop()
            result.append(cid)
            stack.extend(self.children.get(cid, ()))
        return sorted(result)

    def levels(self) -> list[str]:
        """Scopes that show components: the root and every component with children."""
        return [ROOT] + [cid for cid in self.ids if self.has_children(cid)]

    def node_at(self, scope: str, component_id: str) -> tuple[str, bool] | None:
        """The node that holds component_id on the level of scope, and whether it is a boundary node.

        Inside scope: the child of scope on the way down, or '<scope>._self'. Outside: the highest node
        that holds the component and is not an ancestor of scope (spec «Представления»).
        """
        if component_id not in self.parent:
            return None
        chain = self.chain(component_id)
        if scope == ROOT:
            return chain[-1], False
        if component_id == scope:
            return self_node(scope), False
        if scope in chain:
            return chain[chain.index(scope) - 1], False
        scope_chain = set(self.chain(scope)) if scope in self.parent else set()
        for i, cid in enumerate(chain):
            if cid in scope_chain:  # the lowest common ancestor
                return (chain[i - 1] if i else self_node(cid)), True
        return chain[-1], True
