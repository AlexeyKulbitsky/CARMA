"""Discover and prepare C++ projects without depending on a CLI or a renderer."""

from __future__ import annotations

import hashlib
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path
from collections.abc import Callable

from carma.compiledb import load_for_config
from carma.compiledb.sources import write_query
from carma.config import CARMA_DIR, CONFIG_FILE, load_config, write_config
from carma.engine.skeleton import build_skeleton
from carma.indexers.libclang import discovery
from carma.indexers.libclang.indexer import index_project, select_tus
from carma.model.repo import ModelRepo
from carma.store.loader import load_facts
from carma.store.sqlite import SQLiteStore


class ApplicationError(Exception):
    def __init__(self, message: str, code: str = "project_error"):
        super().__init__(message)
        self.code = code


def project_path(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise ApplicationError("The project folder was moved or is unavailable. Choose its new location.", "folder_missing")
    return root


def project_id(root: Path) -> str:
    # Resolve links and normalize case on Windows, so aliases do not duplicate recents.
    import os
    return hashlib.sha256(os.path.normcase(str(root.resolve())).encode()).hexdigest()[:24]


def ready(root: Path) -> bool:
    return ((root / CARMA_DIR / CONFIG_FILE).is_file()
            and any((root / CARMA_DIR / "model").glob("*.yaml"))
            and has_facts(root / CARMA_DIR / "cache" / "facts.db"))


def has_facts(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with SQLiteStore(path) as store:
            return store.stats().files > 0
    except (OSError, sqlite3.Error):
        return False


def run_cmake(arguments: list[str], root: Path) -> str:
    cmake = shutil.which("cmake")
    if cmake is None:
        raise ApplicationError("CMake is unavailable. Install CMake, then retry opening the project.", "cmake_missing")
    result = subprocess.run([cmake, *arguments], cwd=root, capture_output=True, text=True, errors="replace",
                            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)
    if result.returncode:
        raise ApplicationError("Project setup failed. Check the C++ SDK and project dependencies.\n\n"
                               + result.stdout[-6000:] + result.stderr[-6000:], "configure_failed")
    return result.stdout


def discover(root: Path) -> list[dict]:
    if (root / CARMA_DIR / CONFIG_FILE).is_file():
        load_config(root)  # report a broken configuration rather than overwrite it
        return [{"id": "saved", "name": "Saved project configuration", "kind": "saved", "path": "", "configuration": None}]
    directories = [root]
    for p in sorted(root.iterdir()):
        if p.is_dir() and (p.name in {"build", "out"} or p.name.startswith("cmake-build")):
            directories.append(p)
            for child in sorted(p.iterdir()):
                if child.is_dir():
                    directories.append(child)
                    if child.name == "build":
                        directories.extend(c for c in sorted(child.iterdir()) if c.is_dir())
    options = []
    for folder in directories:
        relative = folder.relative_to(root).as_posix()
        if (folder / "compile_commands.json").is_file():
            path = (folder / "compile_commands.json").relative_to(root).as_posix()
            options.append({"id": path, "name": f"Existing build · {relative}", "kind": "commands", "path": path,
                            "configuration": None})
        elif (folder / "CMakeCache.txt").is_file():
            text = (folder / "CMakeCache.txt").read_text(encoding="utf-8", errors="replace")
            match = re.search(r"^CMAKE_CONFIGURATION_TYPES:[^=]*=(.*)$", text, re.M)
            configurations = match.group(1).split(";") if match else [None]
            for configuration in configurations:
                options.append({"id": f"build:{relative}:{configuration or ''}",
                                "name": f"Existing build · {relative}" + (f" · {configuration}" if configuration else ""),
                                "kind": "build", "path": relative, "configuration": configuration})
    if (root / "CMakePresets.json").is_file() or (root / "CMakeUserPresets.json").is_file():
        text = run_cmake(["--list-presets"], root)
        for name, display in re.findall(r'^\s*"([^"]+)"(?:\s+-\s+(.+))?\s*$', text, re.M):
            options.append({"id": f"preset:{name}", "name": display or name, "kind": "preset", "path": name,
                            "configuration": "Debug"})
    if not options and (root / "CMakeLists.txt").is_file():
        options.append({"id": "automatic", "name": "Automatic CMake setup", "kind": "cmake", "path": ".carma/cache/build",
                        "configuration": "Debug"})
    return options


def configure(root: Path, choice: dict, progress: Callable[..., None]) -> None:
    kind = choice["kind"]
    if kind == "saved":
        return
    progress("configuring", "Preparing the project build settings")
    if kind == "commands":
        compile_db = {"compile_commands": choice["path"]}
    elif kind == "build":
        compile_db = {"cmake_build_dir": choice["path"], "configuration": choice["configuration"] or "Debug"}
    else:
        # A preset chooses its own binary directory. The CMake cache identifies it afterwards.
        if kind == "preset":
            out = run_cmake(["--preset", choice["path"]], root)
            match = re.search(r"Build files have been written to:\s*(.+)", out)
            if match is None:
                raise ApplicationError("CMake did not report the configured build folder.", "configure_failed")
            build = Path(match.group(1).strip()).resolve()
        else:
            build = root / choice["path"]
            write_query(build)
            run_cmake(["-S", str(root), "-B", str(build)], root)
        import os
        try:
            relative = Path(os.path.relpath(build, root)).as_posix()
        except ValueError as exc:
            raise ApplicationError("The build folder must be on the same drive as the source project.") from exc
        compile_db = {"cmake_build_dir": relative, "configuration": choice["configuration"] or "Debug"}
    roots = [p for p in ("engine/source", "source", "src", "include", "apps") if (root / p).is_dir()]
    write_config(root, compile_db, roots)


def ensure_model(root: Path, db: Path, destination: Path) -> None:
    config = load_config(root)
    repo = ModelRepo(config.carma_dir / "model")
    if repo.files():
        return
    repo = ModelRepo(destination)
    with SQLiteStore(db) as store:
        skeleton = build_skeleton(store.list_files(), config.source_roots, config.ignore, config.skeleton_depth, root.name)
    if not skeleton:
        raise ApplicationError("No indexed source folders were found in this project.")
    for component in skeleton:
        repo.create(component.data())


def prepare(root: Path, choice: dict, staging: Path, progress: Callable[..., None], *, reindex: bool) -> list[str]:
    configure(root, choice, progress)
    config = load_config(root)
    current = config.cache_dir / "facts.db"
    if not reindex and has_facts(current):
        progress("model", "Preparing the architecture model")
        ensure_model(root, current, staging.parent / "model")
        return []
    progress("discovering", "Reading the project build settings")
    commands = load_for_config(config)
    tus, _ = select_tus(commands, root, config.ignore, config.index_ignored_tus)
    if not tus:
        raise ApplicationError("No C++ source files were found in the selected build configuration.")
    try:
        library = discovery.find_libclang(config.libclang)
    except discovery.LibclangError as exc:
        raise ApplicationError("The C++ indexer is unavailable. Install LLVM 19 or newer, then retry.", "indexer_missing") from exc
    progress("indexing", "Indexing C++ source files", 0, len(tus))
    facts = staging.parent / "facts.jsonl"
    report = index_project(root, tus, facts, libclang=library, ignore=config.ignore,
                           jobs=min(8, len(tus)), progress=lambda done, total, path: progress("indexing", path, done, total))
    if len(report.tus_with_errors) == len(report.tus):
        diagnostics = "\n".join(m for tu in report.tus_with_errors[:3] for m in tu.messages[:2])
        raise ApplicationError("The C++ files could not be parsed. Check the build configuration and generated headers.\n\n"
                               + diagnostics, "parse_failed")
    progress("storing", "Saving the indexed code")
    with SQLiteStore(staging) as store:
        load_facts(store, facts, full=True)
    progress("model", "Preparing the architecture model")
    ensure_model(root, staging, staging.parent / "model")
    if report.tus_with_errors:
        return [f"{len(report.tus_with_errors)} of {len(report.tus)} source files had parse errors; the map is incomplete."]
    return []
