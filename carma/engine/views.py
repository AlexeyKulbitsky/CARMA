"""Views (spec «Ядро», 4): the content of one level of the map."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from carma.engine.aggregation import level_edges
from carma.engine.checks import EDGE_CODES, covers
from carma.engine.state import State
from carma.engine.symbols import TYPE_KINDS, top_symbol
from carma.engine.tree import EXTERNAL, ROOT, UNASSIGNED, VIRTUAL, is_self_node, owner, self_node
from carma.store.api import FactStore

ALL_REFS = 1 << 62  # refs_from / refs_to limit: a view needs every ref of its symbols
DECLARATION_ROLES = frozenset({"definition", "forward_decl"})
INTENT_SHORT = 120


class UnknownScope(KeyError):
    pass


@dataclass(frozen=True)
class Node:
    id: str
    name: str
    type: str  # component | self | unassigned | symbol | file | folder
    kind: str | None = None  # component kind, or symbol kind
    lifecycle: str | None = None
    intent_short: str = ""
    symbols: int = 0
    children: int = 0
    file: str | None = None  # symbol nodes and file groups
    issues: tuple[str, ...] = ()
    pos: tuple[float, float] | None = None
    metrics: Mapping[str, float] = field(default_factory=dict)  # filled by the runtime layer (stage 3)


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    refs: int
    calls: int
    uses: int
    declared: bool = False
    issues: tuple[str, ...] = ()
    metrics: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class View:
    scope: str
    component: str  # ROOT or the component whose children or symbols the level shows
    level: str  # "components" | "symbols"
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    boundary: tuple[Node, ...]
    grouped_by: str | None = None  # "file" | "folder" when there were more than max_nodes symbol nodes
    node_of: Mapping[str, str] = field(default_factory=dict, repr=False)  # symbol level: top symbol -> node


def intent_short(intent: str) -> str:
    line = next((text.strip() for text in intent.splitlines() if text.strip()), "")
    return line if len(line) <= INTENT_SHORT else line[: INTENT_SHORT - 1].rstrip() + "…"


def view(state: State, store: FactStore, scope: str) -> View:
    tree = state.tree
    if scope == ROOT or (scope in state.model.components and tree.has_children(scope)):
        return _component_level(state, scope)
    component = owner(scope)
    if component in state.model.components or component == UNASSIGNED:
        return _symbol_level(state, store, scope, component)
    raise UnknownScope(scope)


# ---------------------------------------------------------------- nodes


def _positions(state: State, scope: str, nodes: list[Node]) -> list[Node]:
    pinned = state.layout.get(scope, {})
    return [replace(n, pos=(pinned[n.id]["x"], pinned[n.id]["y"])) if n.id in pinned else n for n in nodes]


def level_node(state: State, node_id: str) -> Node:
    """A component, '<id>._self' or '_unassigned' as a node."""
    if node_id == UNASSIGNED:
        return Node(id=UNASSIGNED, name="Unassigned", type="unassigned", symbols=state.membership.own[UNASSIGNED])
    component = state.model.components[owner(node_id)]
    if is_self_node(node_id):
        return Node(id=node_id, name=component.name, type="self", kind=component.kind, lifecycle=component.lifecycle,
                    symbols=state.membership.own[component.id])
    codes = sorted({i.code for i in state.issues_of(component.id) if i.code not in EDGE_CODES})
    return Node(id=component.id, name=component.name, type="component", kind=component.kind,
                lifecycle=component.lifecycle, intent_short=intent_short(component.intent),
                symbols=state.subtree_symbols.get(component.id, 0), children=len(state.tree.children[component.id]),
                issues=tuple(codes))


def _declared(state: State, src: str, dst: str) -> bool:
    """The dependency is in `requires` of the source component or of one of its ancestors."""
    source, target = owner(src), owner(dst)
    if source not in state.model.components or target in VIRTUAL:
        return False
    return any(covers(state.model.components[cid].requires, target, state.tree) for cid in state.tree.chain(source))


# ---------------------------------------------------------------- component levels


def _component_level(state: State, scope: str) -> View:
    ids = list(state.tree.children[scope])
    if scope == ROOT and state.membership.own[UNASSIGNED]:
        ids.append(UNASSIGNED)
    if scope != ROOT and state.membership.own[scope]:
        ids.append(self_node(scope))
    undeclared = {(i.component, i.target) for i in state.issues if i.code == "undeclared_dependency"}
    cycle_of = {m: n for n, i in enumerate(state.issues) if i.code == "cycle" and i.scope == scope for m in i.members}
    edges, boundary = [], set()
    for e in level_edges(state.edges, state.tree, scope):
        boundary |= {n for n, b in ((e.src, e.src_boundary), (e.dst, e.dst_boundary)) if b}
        issues = []
        if (e.src, e.dst) in undeclared:
            issues.append("undeclared_dependency")
        if not (e.src_boundary or e.dst_boundary) and e.src in cycle_of and cycle_of[e.src] == cycle_of.get(e.dst):
            issues.append("cycle")
        edges.append(Edge(e.src, e.dst, e.refs, e.calls, e.uses, _declared(state, e.src, e.dst), tuple(issues)))
    return View(scope=scope, component=scope, level="components",
                nodes=tuple(_positions(state, scope, [level_node(state, n) for n in ids])), edges=tuple(edges),
                boundary=tuple(_positions(state, scope, [level_node(state, n) for n in sorted(boundary)])))


# ---------------------------------------------------------------- symbol levels


def _group(tops: Mapping[str, str | None], max_nodes: int) -> tuple[dict[str, str], str | None]:
    """Node per top symbol; above max_nodes, groups by file, then by ever higher folders."""
    if len(tops) <= max_nodes:
        return {t: t for t in tops}, None
    files = {t: path or "" for t, path in tops.items()}
    if len(set(files.values())) <= max_nodes:
        return {t: f"file:{path}" for t, path in files.items()}, "file"
    folders = {t: path.split("/")[:-1] for t, path in files.items()}
    depth = max(len(parts) for parts in folders.values())
    while depth > 0 and len({tuple(p[:depth]) for p in folders.values()}) > max_nodes:
        depth -= 1
    return {t: "folder:" + "/".join(parts[:depth]) for t, parts in folders.items()}, "folder"


def _symbol_level(state: State, store: FactStore, scope: str, component: str) -> View:
    tree, symbols, component_of = state.tree, state.symbols, state.membership.component_of
    own = state.membership.members.get(component, [])
    top_of = {sid: top_symbol(sid, symbols) for sid in own}
    counts = Counter(top_of.values())
    node_of, grouped_by = _group({t: symbols[t].place for t in counts}, state.max_nodes)

    def endpoint(sid: str | None) -> tuple[str, bool] | None:
        cid = component_of.get(sid) if sid else None
        if cid is None or cid == EXTERNAL:
            return None
        if cid == component:
            return node_of[top_of[sid]], False
        return tree.node_at(component, cid)[0], True

    sums: dict[tuple[str, str], list[int]] = {}
    boundary: set[str] = set()

    def add(src, dst, ref) -> None:
        if src is None or dst is None or src[0] == dst[0] or (src[1] and dst[1]) or ref.roles & DECLARATION_ROLES:
            return
        boundary.update(n for n, b in (src, dst) if b)
        total = sums.setdefault((src[0], dst[0]), [0, 0, 0])
        total[0] += 1
        total[1] += "call" in ref.roles
        target = symbols.get(ref.symbol)
        total[2] += "reference" in ref.roles and target is not None and target.kind in TYPE_KINDS

    for sid in own:
        for ref in store.refs_from(sid, limit=ALL_REFS):
            add(endpoint(sid), endpoint(ref.symbol), ref)
        for ref in store.refs_to(sid, limit=ALL_REFS):
            if component_of.get(ref.container) != component:  # refs from own symbols came through refs_from
                add(endpoint(ref.container), endpoint(sid), ref)

    model_component = state.model.components.get(component)
    edges = []
    for (src, dst), (refs, calls, uses) in sorted(sums.items()):
        declared, issues = False, ()
        outgoing = dst in boundary and src not in boundary and owner(dst) not in VIRTUAL
        if model_component is not None and outgoing and not tree.within(owner(dst), component):
            declared = _declared(state, component, dst)
            if model_component.declares_requires and not covers(model_component.requires, owner(dst), tree):
                issues = ("undeclared_dependency",)
        edges.append(Edge(src, dst, refs, calls, uses, declared, issues))

    nodes = []
    if grouped_by is None:
        for top in counts:
            info = symbols[top]
            nodes.append(Node(id=top, name=info.name, type="symbol", kind=info.kind, symbols=counts[top], file=info.place))
    else:
        groups = Counter()
        for top, n in counts.items():
            groups[node_of[top]] += n
        for gid, n in groups.items():
            path = gid.split(":", 1)[1]
            name = path.rsplit("/", 1)[-1] or ("(no file)" if grouped_by == "file" else "(project root)")
            nodes.append(Node(id=gid, name=name, type=grouped_by, symbols=n, file=path if grouped_by == "file" else None))
    nodes.sort(key=lambda n: (n.file or "", n.name, n.id))
    return View(scope=scope, component=component, level="symbols", nodes=tuple(_positions(state, scope, nodes)),
                edges=tuple(edges), boundary=tuple(_positions(state, scope, [level_node(state, n) for n in sorted(boundary)])),
                grouped_by=grouped_by, node_of=node_of)
