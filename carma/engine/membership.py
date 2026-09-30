"""Membership resolution (spec «Ядро», 1): every symbol of the project gets exactly one component."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from carma.engine.symbols import SymbolInfo, namespace_of
from carma.engine.tree import EXTERNAL, UNASSIGNED, ComponentTree
from carma.model.repo import Component
from carma.paths import glob_match, matches_any

EXPLICIT = 1 << 30  # an explicit symbol rule is more specific than any path or namespace


def path_specificity(glob: str) -> int:
    """Whole path segments before the first wildcard: 'src/render/**' -> 2."""
    count = 0
    for segment in glob.split("/"):
        if "*" in segment or "?" in segment:
            break
        count += 1
    return count


def namespace_specificity(namespace: str) -> int:
    return len(namespace.split("::"))


def namespace_matches(rule: str, namespace: str) -> bool:
    """A rule covers its namespace and the ones nested in it."""
    return namespace == rule or namespace.startswith(rule + "::")


@dataclass(frozen=True)
class Ambiguity:
    components: tuple[str, ...]  # tied candidates, sorted: the first one gets the symbols
    symbols: tuple[str, ...]


@dataclass
class Membership:
    component_of: dict[str, str]  # symbol ID -> component ID, _unassigned or _external; no namespaces
    ambiguities: list[Ambiguity] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.own = Counter(self.component_of.values())
        members: dict[str, list[str]] = defaultdict(list)
        for sid, cid in self.component_of.items():
            members[cid].append(sid)
        self.members = dict(members)


@dataclass(frozen=True)
class _Rules:
    component: str
    paths: tuple[tuple[str, int], ...]
    namespaces: tuple[tuple[str, int], ...]
    exclude_paths: tuple[str, ...]
    exclude_namespaces: tuple[str, ...]
    exclude_symbols: frozenset[str]

    @classmethod
    def of(cls, component: Component) -> _Rules:
        paths, namespaces, ex_paths, ex_namespaces, ex_symbols = [], [], [], [], set()
        for rule in component.members:
            if "path" in rule:
                paths.append((rule["path"], path_specificity(rule["path"])))
            elif "namespace" in rule:
                namespaces.append((rule["namespace"], namespace_specificity(rule["namespace"])))
            elif "exclude" in rule:
                ex = rule["exclude"]
                if "path" in ex:
                    ex_paths.append(ex["path"])
                elif "namespace" in ex:
                    ex_namespaces.append(ex["namespace"])
                else:
                    ex_symbols.add(ex["symbol"])
        return cls(component.id, tuple(paths), tuple(namespaces), tuple(ex_paths), tuple(ex_namespaces),
                   frozenset(ex_symbols))


def pick(candidates: Mapping[str, int], tree: ComponentTree) -> tuple[str, tuple[str, ...] | None]:
    """The winner among candidate components with their specificity, and the tie when there is one."""
    names = [c for c in candidates if not any(tree.is_ancestor(c, other) for other in candidates if other != c)]
    best = max(candidates[c] for c in names)
    tied = sorted(c for c in names if candidates[c] == best)
    return tied[0], (tuple(tied) if len(tied) > 1 else None)


def resolve_membership(symbols: Mapping[str, SymbolInfo], components: Iterable[Component], tree: ComponentTree,
                       ignore: Iterable[str]) -> Membership:
    components = sorted(components, key=lambda c: c.id)
    rules = [_Rules.of(c) for c in components]
    ignore = tuple(ignore)
    explicit: dict[str, list[str]] = defaultdict(list)
    for component in components:
        for sid in component.symbol_rules:
            explicit[sid].append(component.id)

    by_file: dict[str, tuple[dict[str, int], frozenset[str], bool]] = {}

    def file_rules(path: str) -> tuple[dict[str, int], frozenset[str], bool]:
        """Path rules are evaluated per file: files are far fewer than symbols."""
        if path not in by_file:
            matched: dict[str, int] = {}
            for r in rules:
                spec = max((s for glob, s in r.paths if glob_match(path, glob)), default=None)
                if spec is not None:
                    matched[r.component] = spec
            excluded = frozenset(r.component for r in rules if any(glob_match(path, g) for g in r.exclude_paths))
            by_file[path] = (matched, excluded, matches_any(path, ignore))
        return by_file[path]

    by_namespace: dict[str, tuple[dict[str, int], frozenset[str]]] = {}

    def namespace_rules(namespace: str) -> tuple[dict[str, int], frozenset[str]]:
        if namespace not in by_namespace:
            matched: dict[str, int] = {}
            for r in rules:
                spec = max((s for rule, s in r.namespaces if namespace_matches(rule, namespace)), default=None)
                if spec is not None:
                    matched[r.component] = spec
            excluded = frozenset(r.component for r in rules
                                 if any(namespace_matches(rule, namespace) for rule in r.exclude_namespaces))
            by_namespace[namespace] = (matched, excluded)
        return by_namespace[namespace]

    has_namespace_rules = any(r.namespaces or r.exclude_namespaces for r in rules)
    component_of: dict[str, str] = {}
    ties: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for sid in sorted(symbols):
        info = symbols[sid]
        if info.kind == "namespace":
            continue
        tie = None
        if sid in explicit:
            component_of[sid], tie = pick(dict.fromkeys(explicit[sid], EXPLICIT), tree)
        elif info.external:
            component_of[sid] = EXTERNAL
        else:
            candidates: dict[str, int] = {}
            excluded: set[str] = {r.component for r in rules if sid in r.exclude_symbols}
            if info.place is not None:
                matched, ex, ignored = file_rules(info.place)
                if ignored:
                    component_of[sid] = EXTERNAL
                    continue
                candidates.update(matched)
                excluded |= ex
            if has_namespace_rules:
                namespace = namespace_of(sid, symbols)
                if namespace:
                    matched, ex = namespace_rules(namespace)
                    for cid, spec in matched.items():
                        candidates[cid] = max(spec, candidates.get(cid, 0))
                    excluded |= ex
            for cid in excluded:
                candidates.pop(cid, None)
            if candidates:
                component_of[sid], tie = pick(candidates, tree)
            else:
                component_of[sid] = UNASSIGNED if info.place is not None else EXTERNAL
        if tie:
            ties[tie].append(sid)
    ambiguities = [Ambiguity(components, tuple(sids)) for components, sids in sorted(ties.items())]
    return Membership(component_of, ambiguities)
