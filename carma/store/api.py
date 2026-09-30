"""Contract 2: the fact store as a set of operations.

The core never writes SQL; it talks to a FactStore. Any implementation (SQLite in v0,
DuckDB or an in-memory graph later) must pass the same contract tests.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

CONTRACT_VERSION = "store/0.1"

Range = tuple[int, int, int, int]
Role = Literal["call", "reference", "expansion", "definition", "forward_decl", "read", "write"]
RelationKind = Literal["inherits", "overrides", "type_definition"]
Direction = Literal["in", "out"]


@dataclass(frozen=True)
class FactsHeader:
    facts_version: str
    indexer_name: str
    indexer_version: str
    clang_version: str | None
    platform: Literal["windows", "macos", "linux"]
    project_root: str


@dataclass(frozen=True)
class Loc:
    path: str
    range: Range
    extent: Range


@dataclass(frozen=True)
class Symbol:
    id: str
    display_name: str
    kind: str
    parent_id: str | None
    signature: str | None
    doc: str | None
    access: str | None
    defs: tuple[Loc, ...]
    decls: tuple[Loc, ...]
    external: bool
    usr: str | None = None


@dataclass(frozen=True)
class Ref:
    symbol: str
    path: str
    range: Range
    roles: frozenset[str]
    container: str | None


@dataclass(frozen=True)
class Relation:
    from_id: str
    to_id: str
    kind: RelationKind


@dataclass(frozen=True)
class ComponentEdge:
    src: str
    dst: str
    refs: int
    calls: int
    uses: int


@dataclass(frozen=True)
class CallEdge:
    caller: str
    callee: str
    path: str
    line: int
    depth: int


@dataclass(frozen=True)
class StoreStats:
    files: int
    symbols: int
    refs: int
    relations: int
    facts_version: str | None
    platform: str | None
    loaded_at: str | None


class LoadSession(Protocol):
    """One load of a fact stream; nothing is visible to readers until commit().

    Symbols are upserted by ID and keep the locations of files that are not reloaded.
    Every session receives the complete set of relations, which replaces the stored one.
    """

    def put(self, record: dict) -> None:
        """Add one contract-1 record (file, symbol, ref or relation). A file record may carry `load_hash`."""

    def delete_file(self, path: str) -> None:
        """Drop the file, its refs and the symbol locations in it before it is loaded again."""

    def commit(self) -> None:
        """Make the load visible and remove orphaned symbols."""


@runtime_checkable
class FactStore(Protocol):
    contract_version: str

    # loading
    def begin_load(self, header: FactsHeader) -> LoadSession: ...
    def file_hashes(self) -> dict[str, str]:
        """Per file, the hash the loader recorded: content hash plus a digest of the facts located in it."""
        ...

    # lookup
    def get_symbol(self, id: str) -> Symbol | None: ...
    def search_symbols(self, text: str, kinds: list[str] | None = None, limit: int = 50) -> list[Symbol]: ...
    def symbols_in_file(self, path: str) -> list[Symbol]: ...
    def list_files(self, glob: str | None = None) -> list[str]: ...
    def symbol_at(self, path: str, line: int) -> Symbol | None: ...
    def refs_to(self, id: str, limit: int = 500) -> list[Ref]: ...
    def refs_from(self, container_id: str, limit: int = 500) -> list[Ref]: ...
    def relations(self, id: str, kind: RelationKind | None = None, direction: Direction = "out") -> list[Relation]: ...

    # derived data
    def set_membership(self, mapping: Iterable[tuple[str, str]]) -> None: ...
    def component_edges(self, include_external: bool = False) -> list[ComponentEdge]: ...
    def edge_samples(self, src: str, dst: str, limit: int = 20) -> list[Ref]: ...

    # traversals
    def callers(self, id: str, depth: int = 1) -> list[CallEdge]: ...
    def callees(self, id: str, depth: int = 1) -> list[CallEdge]: ...
    def paths(self, src: str, dst: str, max_depth: int = 6, limit: int = 5) -> list[list[str]]: ...

    def stats(self) -> StoreStats: ...
