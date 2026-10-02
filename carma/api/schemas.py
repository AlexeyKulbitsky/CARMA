"""Contract 4: the shapes of View API responses. contracts/openapi.yaml is generated from them."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

API_VERSION = "api/0.2"

IssueCode = Literal["invalid_model", "broken_anchor", "ambiguous_membership", "empty", "stale", "missing_dependency",
                    "undeclared_dependency", "cycle"]
Lifecycle = Literal["current", "planned", "deprecated"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorBody(Model):
    code: str = Field(description="not_found, validation_failed or another machine-readable code")
    message: str
    details: list[Any] = []


class ErrorResponse(Model):
    error: ErrorBody


# ---------------------------------------------------------------- status


class Contracts(Model):
    api: str
    facts: str | None = Field(description="facts_version of the loaded fact stream")
    store: str
    model: str
    config: str
    layout: str


class FactsStatus(Model):
    files: int
    symbols: int
    refs: int
    relations: int
    facts_version: str | None
    platform: str | None = Field(description="OS the facts were indexed on: code under #ifdef for other OSes is not in them")
    loaded_at: str | None


class Status(Model):
    version: str = Field(description="carma package version")
    contracts: Contracts
    project_root: str
    project_name: str
    facts: FactsStatus
    components: int
    invalid_files: list[str]
    issues: int
    highlight: bool


# ---------------------------------------------------------------- views


class Position(Model):
    x: float
    y: float


class ViewMember(Model):
    id: str
    name: str
    kind: str = Field(description="field, variable, method, constructor, destructor or function")
    signature: str | None
    access: str | None


class ViewNode(Model):
    id: str = Field(description="component ID, '<id>._self', '_unassigned', symbol ID, 'file:<path>' or 'folder:<path>'")
    name: str
    type: Literal["component", "self", "unassigned", "symbol", "file", "folder"]
    kind: str | None = Field(description="system, subsystem or component; for symbol nodes the symbol kind")
    lifecycle: Lifecycle | None
    intent_short: str
    symbols: int = Field(description="symbols inside the node, descendants included")
    children: int = Field(description="child components")
    file: str | None = Field(description="symbol nodes and file groups: the file the node belongs to")
    issues: list[IssueCode]
    pos: Position | None = Field(description="position pinned in layout.json, else null")
    metrics: dict[str, float] = Field(description="runtime metrics; empty in v0")
    members: list[ViewMember] = Field(description="direct fields and methods of a class, struct or union; empty otherwise")


class ViewEdge(Model):
    src: str
    dst: str
    refs: int
    calls: int
    uses: int
    declared: bool = Field(description="the target is in requires of the source or of one of its ancestors")
    issues: list[IssueCode]
    metrics: dict[str, float]


class Crumb(Model):
    scope: str
    name: str


class View(Model):
    scope: str
    level: Literal["components", "symbols"]
    component: str = Field(description="'root' or the component whose children or symbols the level shows")
    trail: list[Crumb] = Field(description="breadcrumbs from the root down to this level")
    nodes: list[ViewNode]
    edges: list[ViewEdge]
    boundary: list[ViewNode] = Field(description="neighbors outside the level that edges lead to, drawn pale")
    grouped_by: Literal["file", "folder"] | None = Field(description="set when the level had more than max_nodes nodes")


# ---------------------------------------------------------------- components


class TreeNode(Model):
    id: str
    name: str
    kind: Literal["system", "subsystem", "component"]
    lifecycle: Lifecycle
    symbols: int
    own_symbols: int
    issues: list[IssueCode]
    children: list[TreeNode]


class ComponentTree(Model):
    parent: str
    components: list[TreeNode]
    unassigned: int = Field(description="symbols in no component, shown as the _unassigned node at the top level")


class Issue(Model):
    code: IssueCode
    component: str | None
    target: str | None
    members: list[str]
    scope: str | None
    symbols: list[str]
    count: int
    message: str
    text: str = Field(description="one line for people")


class InterfaceSymbol(Model):
    id: str
    present: bool = Field(description="false when the anchor is not in the facts")
    name: str | None
    kind: str | None
    signature: str | None
    path: str | None


class DependencyEdge(Model):
    node: str = Field(description="the other end, named as seen from the component's parent level")
    refs: int
    calls: int
    uses: int
    declared: bool


class ComponentCard(Model):
    id: str
    parent: str
    children: list[str]
    model: dict[str, Any] = Field(description="the component file (contract 3) as JSON")
    symbols: int
    own_symbols: int
    issues: list[Issue]
    interface: list[InterfaceSymbol] = Field(description="provides and explicit symbols, else public header symbols")
    fingerprint: str = Field(description="current interface fingerprint, as sync.fingerprint stores it")
    edges_out: list[DependencyEdge]
    edges_in: list[DependencyEdge]


# ---------------------------------------------------------------- symbols


class Location(Model):
    path: str
    line: int = Field(description="1-based line of the name")
    column: int = Field(description="1-based column of the name, in UTF-8 bytes")
    end_line: int = Field(description="1-based last line of the whole declaration")


class SymbolBrief(Model):
    id: str
    name: str
    kind: str
    signature: str | None
    component: str | None = Field(description="component ID, _unassigned or _external; null for namespaces")
    path: str | None = Field(description="the file that decides membership")
    line: int | None
    external: bool


class SymbolList(Model):
    items: list[SymbolBrief]
    more: bool = Field(description="true when the list was cut at limit")


class Place(Model):
    scope: str
    node: str


class SymbolCard(Model):
    id: str
    name: str
    kind: str
    signature: str | None
    doc: str | None
    access: str | None
    parent: str | None
    external: bool
    component: str | None
    defs: list[Location]
    decls: list[Location]
    place: Place | None = Field(description="the level and node that draw this symbol on the map")
    editor_uri: str | None = Field(description="editor_uri from config.yaml filled with the definition")


class CallEdge(Model):
    caller: str
    callee: str
    caller_name: str
    callee_name: str
    path: str
    line: int = Field(description="1-based line of the first call")
    depth: int


class CallList(Model):
    items: list[CallEdge]
    more: bool


class PathList(Model):
    paths: list[list[str]]


class RefSample(Model):
    symbol: str
    container: str | None
    path: str
    line: int
    column: int
    roles: list[str]


class RefList(Model):
    items: list[RefSample]
    more: bool


class LayoutBody(Model):
    positions: dict[str, Position] = Field(description="node ID -> pinned position; an empty object unpins the level")


class LayoutResult(Model):
    scope: str
    positions: dict[str, Position]
