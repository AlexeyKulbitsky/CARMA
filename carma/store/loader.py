"""Loading a contract-1 fact stream into any FactStore, fully or incrementally.

A file is reloaded when its content hash or the facts located in it changed: a header edit
can change IDs that an untouched .cpp refers to. Relations are small and always replaced.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from carma.store.api import FactsHeader, FactStore

_MASK = (1 << 64) - 1


class FactsError(Exception):
    pass


@dataclass(frozen=True)
class LoadReport:
    full: bool
    files_total: int
    files_loaded: int
    files_removed: int
    seconds: float


def iter_records(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except ValueError as exc:
                    raise FactsError(f"{path}:{number}: {exc}") from exc


def read_header(path: Path) -> FactsHeader:
    first = next(iter_records(path), None)
    if not first or first.get("type") != "header":
        raise FactsError(f"{path} does not start with a header record")
    indexer = first["indexer"]
    return FactsHeader(
        facts_version=first["facts_version"],
        indexer_name=indexer["name"],
        indexer_version=indexer["version"],
        clang_version=indexer.get("clang"),
        platform=first["platform"],
        project_root=first["project_root"],
    )


def _item_hash(item: object) -> int:
    text = json.dumps(item, sort_keys=True, separators=(",", ":"))
    return int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "little")


def _load_hashes(path: Path) -> tuple[dict[str, dict], dict[str, str]]:
    """File records by path, and the load hash per path: content hash plus a digest of its facts."""
    files: dict[str, dict] = {}
    digest: dict[str, int] = {}

    def add(p: str, item: object) -> None:
        digest[p] = (digest.get(p, 0) + _item_hash(item)) & _MASK

    for record in iter_records(path):
        kind = record.get("type")
        if kind == "file":
            files[record["path"]] = record
        elif kind == "symbol":
            for is_def, locs in ((1, record["defs"]), (0, record["decls"])):
                for loc in locs:
                    add(loc["path"], [record["id"], is_def, loc])
        elif kind == "ref":
            add(record["path"], record)
    hashes = {p: f"{rec['sha256']}:{digest.get(p, 0):016x}" for p, rec in files.items()}
    return files, hashes


def load_facts(store: FactStore, facts_path: Path, *, full: bool = False) -> LoadReport:
    started = time.perf_counter()
    header = read_header(facts_path)
    files, hashes = _load_hashes(facts_path)
    old = store.file_hashes()
    meta = store.meta() if hasattr(store, "meta") else {}
    if meta and (meta.get("platform") != header.platform or meta.get("facts_version") != header.facts_version):
        full = True  # facts of another platform or format cannot be merged
    if not old:
        full = True  # an empty store: the first load is a full one
    if full:
        changed = set(files)
        to_delete = set(old)
    else:
        changed = {p for p, h in hashes.items() if old.get(p) != h}
        to_delete = (changed & set(old)) | (set(old) - set(files))

    session = store.begin_load(header)
    for p in sorted(to_delete):
        session.delete_file(p)
    for record in iter_records(facts_path):
        kind = record.get("type")
        if kind == "file":
            if record["path"] in changed:
                session.put({**record, "load_hash": hashes[record["path"]]})
        elif kind == "symbol":
            session.put({
                **record,
                "defs": [loc for loc in record["defs"] if loc["path"] in changed],
                "decls": [loc for loc in record["decls"] if loc["path"] in changed],
            })
        elif kind == "ref":
            if record["path"] in changed:
                session.put(record)
        elif kind == "relation":
            session.put(record)
    session.commit()
    return LoadReport(
        full=full,
        files_total=len(files),
        files_loaded=len(changed),
        files_removed=len(set(old) - set(files)),
        seconds=time.perf_counter() - started,
    )
