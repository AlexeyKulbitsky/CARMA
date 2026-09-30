"""Indexer adapter v0: a project's translation units -> contract-1 facts (JSONL) through libclang."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from carma import __version__
from carma.compiledb import CompileCommand
from carma.indexers.libclang import discovery, walker
from carma.indexers.libclang.args import libclang_args
from carma.paths import matches_any, relpath

FACTS_VERSION = "0.1"
INDEXER_NAME = "carma-libclang"


@dataclass
class TuReport:
    path: str
    errors: int
    messages: list[str]
    parse_s: float
    walk_s: float
    stl_workaround: bool
    fatal: bool


@dataclass
class IndexReport:
    libclang: discovery.LibclangInfo
    out_path: Path
    resource_dir: Path | None = None
    sysroot: str | None = None
    tus: list[TuReport] = field(default_factory=list)
    symbols: int = 0
    refs: int = 0
    refs_by_role: dict[str, int] = field(default_factory=dict)
    relations: int = 0
    files: int = 0
    wall_s: float = 0.0

    @property
    def tus_with_errors(self) -> list[TuReport]:
        return [t for t in self.tus if t.errors]


def platform_name() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def select_tus(commands: list[CompileCommand], root: Path, ignore: tuple[str, ...], index_ignored: bool) -> tuple[list[CompileCommand], int]:
    """Translation units inside the project root; those under ignore globs only when asked. Returns (selected, skipped)."""
    selected, skipped = [], 0
    for cmd in commands:
        rel = relpath(cmd.file, root)
        if rel is None or (not index_ignored and matches_any(rel, ignore)):
            skipped += 1
            continue
        selected.append(cmd)
    return selected, skipped


def _merge_symbol(into: dict, rec: dict) -> None:
    for key in ("defs", "decls"):
        for loc in rec[key]:
            if loc not in into[key]:
                into[key].append(loc)
    # the same place seen as a definition in one TU and a declaration in another: definition wins
    into["decls"] = [loc for loc in into["decls"] if loc not in into["defs"]]
    into["external"] = into["external"] and rec["external"]
    for key in ("signature", "doc", "access", "usr", "parent_id"):
        if into.get(key) is None and rec.get(key) is not None:
            into[key] = rec[key]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _loc_key(loc: dict) -> tuple:
    return (loc["path"], loc["range"], loc["extent"])


def index_project(
    root: Path,
    commands: list[CompileCommand],
    out_path: Path,
    *,
    libclang: Path,
    ignore: tuple[str, ...] = (),
    jobs: int | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> IndexReport:
    """Index the given translation units and write the fact stream to out_path.

    With jobs > 1 the workers start with `spawn` on every OS, so a calling script must guard
    its entry point with `if __name__ == "__main__":`, or each worker would rerun it.
    """
    root = root.resolve()
    info = discovery.load(libclang)
    started = time.perf_counter()
    builtin = discovery.resource_dir(info)
    sdk = discovery.macos_sdk()
    tasks = sorted(
        (
            (str(cmd.file), relpath(cmd.file, root) or cmd.file.name,
             libclang_args(cmd, resource_dir=str(builtin) if builtin else None, sysroot=sdk), str(cmd.directory))
            for cmd in commands
        ),
        key=lambda t: t[1],
    )
    jobs = max(1, min(jobs or os.cpu_count() or 1, len(tasks) or 1))

    symbols: dict[str, dict] = {}
    refs: dict[tuple, set[str]] = {}
    relations: set[tuple[str, str, str]] = set()
    files: set[str] = set()
    report = IndexReport(libclang=info, out_path=out_path, resource_dir=builtin, sysroot=sdk)

    def consume(result: dict) -> None:
        report.tus.append(TuReport(result["tu"], result["errors"], result["messages"], result["parse_s"],
                                   result["walk_s"], result["stl_workaround"], result["fatal"]))
        for sid, rec in result["symbols"].items():
            if sid in symbols:
                _merge_symbol(symbols[sid], rec)
            else:
                symbols[sid] = rec
        for tid, path, l0, c0, l1, c1, role, container in result["refs"]:
            refs.setdefault((tid, path, l0, c0, l1, c1, container), set()).add(role)
        relations.update(tuple(r) for r in result["relations"])
        files.update(result["files"])
        if progress:
            progress(len(report.tus), len(tasks), result["tu"])

    initargs = (str(info.path), str(root), tuple(ignore))
    if jobs == 1:
        cwd = os.getcwd()
        try:
            walker.init_worker(*initargs)
            for task in tasks:
                consume(walker.index_tu(task))
        finally:
            os.chdir(cwd)
    else:
        context = multiprocessing.get_context("spawn")
        with context.Pool(jobs, initializer=walker.init_worker, initargs=initargs) as pool:
            for result in pool.imap_unordered(walker.index_tu, tasks, chunksize=1):
                consume(result)

    # file records for every project path that facts point to
    for rec in symbols.values():
        for loc in rec["defs"] + rec["decls"]:
            files.add(loc["path"])
    for key in refs:
        files.add(key[1])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    roles = Counter()
    with tmp.open("w", encoding="utf-8", newline="\n") as out:
        def write(record: dict) -> None:
            out.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            out.write("\n")

        write({
            "type": "header",
            "facts_version": FACTS_VERSION,
            "indexer": {"name": INDEXER_NAME, "version": __version__, "clang": info.number},
            "platform": platform_name(),
            "project_root": root.as_posix(),
        })
        for path in sorted(files):
            file = root / path
            if file.is_file():
                write({"type": "file", "path": path, "sha256": _sha256(file),
                       "language": "c" if path.lower().endswith(".c") else "cpp"})
        for sid in sorted(symbols):
            rec = symbols[sid]
            rec["defs"].sort(key=_loc_key)
            rec["decls"].sort(key=_loc_key)
            write(rec)
        for key in sorted(refs, key=lambda k: (k[1], k[2], k[3], k[0], k[6] or "")):
            tid, path, l0, c0, l1, c1, container = key
            role_list = sorted(refs[key])
            roles.update(role_list)
            write({"type": "ref", "symbol": tid, "path": path, "range": [l0, c0, l1, c1],
                   "roles": role_list, "container": container})
        for src, dst, kind in sorted(relations):
            write({"type": "relation", "from": src, "to": dst, "kind": kind})
    os.replace(tmp, out_path)

    report.tus.sort(key=lambda t: t.path)
    report.symbols = len(symbols)
    report.refs = len(refs)
    report.refs_by_role = dict(sorted(roles.items()))
    report.relations = len(relations)
    report.files = len(files)
    report.wall_s = time.perf_counter() - started
    return report
