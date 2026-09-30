"""Model skeleton from the folders of indexed files (spec «Скелет»): what `carma init` writes."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from carma.model.repo import SCHEMA_VERSION
from carma.paths import CASE_INSENSITIVE, matches_any


@dataclass(frozen=True)
class SkeletonComponent:
    id: str
    name: str
    kind: str
    path: str  # the path rule
    files: int

    def data(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "id": self.id, "name": self.name, "kind": self.kind, "intent": "",
                "members": [{"path": self.path}]}


@dataclass
class _Folder:
    path: str  # relative to the project root
    files: int = 0
    children: dict[str, _Folder] = field(default_factory=dict)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("_-")


def _title(name: str) -> str:
    return name[:1].upper() + name[1:]


def _unique(slugs: Iterable[str], taken: Iterable[str] = ()) -> list[str]:
    used = set(taken)
    result = []
    for slug in slugs:
        candidate, n = slug, 2
        while candidate in used:
            candidate, n = f"{slug}-{n}", n + 1
        used.add(candidate)
        result.append(candidate)
    return result


def build_skeleton(files: Iterable[str], source_roots: Sequence[str], ignore: Sequence[str], depth: int,
                   project_name: str) -> list[SkeletonComponent]:
    fold = str.casefold if CASE_INSENSITIVE else (lambda s: s)
    files = [f for f in files if not matches_any(f, ignore)]
    entries = []  # (slug, root slug, name, path rule, file count, folder)
    for root in [r.strip("/") for r in source_roots] or [""]:
        prefix = f"{root}/" if root else ""
        root_slug = slugify(root.replace("/", "-") if root else project_name) or "project"
        tree = _Folder(root)
        direct = 0
        for f in files:
            if not fold(f).startswith(fold(prefix)):
                continue
            parts = f[len(prefix):].split("/")
            if len(parts) == 1:
                direct += 1
            node = tree
            for name in parts[:-1][:depth]:
                node = node.children.setdefault(name, _Folder(f"{node.path}/{name}" if node.path else name))
                node.files += 1
        if direct:
            entries.append((root_slug, root_slug, root or project_name, f"{prefix}*", direct, None))
        for name, folder in sorted(tree.children.items()):
            entries.append((slugify(name) or "folder", root_slug, _title(name), f"{folder.path}/**", folder.files, folder))

    roots_of: dict[str, set[str]] = {}
    for slug, root_slug, *_ in entries:
        roots_of.setdefault(slug, set()).add(root_slug)
    slugs = [f"{root_slug}-{slug}" if len(roots_of[slug]) > 1 else slug for slug, root_slug, *_ in entries]

    result: list[SkeletonComponent] = []

    def nested(folder: _Folder, parent_id: str) -> None:
        children = sorted(folder.children.items())
        for (name, child), slug in zip(children, _unique(slugify(n) or "folder" for n, _ in children)):
            cid = f"{parent_id}.{slug}"
            result.append(SkeletonComponent(cid, _title(name), "component", f"{child.path}/**", child.files))
            nested(child, cid)

    for (_, _, name, rule, count, folder), cid in zip(entries, _unique(slugs, taken={"root"})):
        result.append(SkeletonComponent(cid, name, "subsystem", rule, count))
        if folder is not None:
            nested(folder, cid)
    return sorted(result, key=lambda c: c.id)
