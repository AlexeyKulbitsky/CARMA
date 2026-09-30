"""The slice of a fact-store symbol the core keeps in memory for every symbol."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from carma.store.api import Symbol

HEADER_SUFFIXES = (".h", ".hh", ".hpp", ".hxx", ".h++", ".inl", ".ipp", ".tpp", ".inc")
TYPE_KINDS = frozenset({"class", "struct", "union", "enum", "type_alias", "concept"})


def is_header(path: str) -> bool:
    return path.lower().endswith(HEADER_SUFFIXES)


@dataclass(frozen=True, slots=True)
class SymbolInfo:
    id: str
    name: str
    kind: str
    parent: str | None
    signature: str | None
    access: str | None
    external: bool
    place: str | None  # the file that decides membership (spec «Контракт 2», «Место символа»)
    in_header: bool  # declared or defined in a header file

    @classmethod
    def from_symbol(cls, s: Symbol) -> SymbolInfo:
        return cls(id=s.id, name=s.display_name, kind=s.kind, parent=s.parent_id, signature=s.signature,
                   access=s.access, external=s.external, place=place_of(s),
                   in_header=any(is_header(loc.path) for loc in (*s.defs, *s.decls)))


def place_of(s: Symbol) -> str | None:
    """The definition with the smallest path; without definitions, the declaration with the smallest path."""
    locs = s.defs or s.decls
    return min(loc.path for loc in locs) if locs else None


def top_symbol(sid: str, symbols: Mapping[str, SymbolInfo]) -> str:
    """The outermost enclosing symbol below a namespace: method and field -> class, nested type -> outer type."""
    current = sid
    while True:
        parent = symbols.get(symbols[current].parent) if symbols[current].parent else None
        if parent is None or parent.kind == "namespace":
            return current
        current = parent.id


def namespace_of(sid: str, symbols: Mapping[str, SymbolInfo]) -> str:
    """Qualified name of the enclosing namespaces, anonymous ones skipped: 'eng::render' or ''."""
    names = []
    parent = symbols[sid].parent
    while parent is not None and parent in symbols:
        info = symbols[parent]
        if info.kind == "namespace" and not info.name.startswith("("):
            names.append(info.name)
        parent = info.parent
    return "::".join(reversed(names))
