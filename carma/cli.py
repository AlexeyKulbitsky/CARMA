"""carma command line: init | index | serve | check | mcp."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from carma import __version__

# Commands and the milestone that implements them (docs/carma-spec.md, «Этапы реализации»).
COMMANDS = {
    "init": ("create .carma/config.yaml and the model skeleton", "M2"),
    "index": ("run the indexer adapter and load facts", "M1"),
    "serve": ("start the core and serve the UI", "M3"),
    "check": ("print model issues; non-zero exit code if any", "M2"),
    "mcp": ("run the MCP server for the agent", "M4"),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="carma", description="Architecture map of a C++ codebase.")
    parser.add_argument("--version", action="version", version=f"carma {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (help_text, _) in COMMANDS.items():
        cmd = sub.add_parser(name, help=help_text)
        if name == "init":
            cmd.add_argument("--project", type=Path, help="project root (default: the current folder)")
            source = cmd.add_mutually_exclusive_group()
            source.add_argument("--compile-commands", type=Path, help="path to compile_commands.json")
            source.add_argument("--cmake-build-dir", type=Path, help="CMake build folder, read through the File API")
            cmd.add_argument("--configuration", help="configuration of a multi-config generator (default: Debug)")
            cmd.add_argument("--source-root", type=Path, action="append", default=[],
                             help="folder the skeleton starts from; repeat for several")
        else:
            cmd.add_argument("--project", type=Path,
                             help="project root with .carma/config.yaml (default: search from the current folder)")
        if name in ("index", "init"):
            cmd.add_argument("--jobs", type=int, help="worker processes (default: number of CPUs)")
        if name == "index":
            cmd.add_argument("--full", action="store_true", help="reload every file into the store")
    return parser


def _project_root(args) -> Path:
    from carma.config import find_project_root

    return args.project.resolve() if args.project else find_project_root(Path.cwd())


def _index(args) -> int:
    from carma.config import load_config

    config = load_config(_project_root(args))
    print(f"carma index {config.project_root}")
    return _run_index(config, jobs=args.jobs, full=args.full)


def _run_index(config, *, jobs: int | None, full: bool) -> int:
    from carma import compiledb
    from carma.indexers.libclang import discovery
    from carma.indexers.libclang.indexer import index_project, select_tus
    from carma.store.loader import load_facts
    from carma.store.sqlite import SQLiteStore

    root = config.project_root
    commands = compiledb.load_for_config(config)
    tus, skipped = select_tus(commands, root, config.ignore, config.index_ignored_tus)
    source = f"CMake build folder {config.cmake_build_dir}" if config.cmake_build_dir else config.compile_commands
    print(f"  compile commands  {len(tus)} TUs from {source}, {skipped} outside the project or ignored")
    if not tus:
        print("  nothing to index", file=sys.stderr)
        return 1

    library = discovery.find_libclang(config.libclang)
    info = discovery.load(library)
    print(f"  libclang          {info.version} ({info.path})")
    warning = discovery.version_warning(info)
    if warning:
        print(f"  warning: {warning}", file=sys.stderr)

    interactive = sys.stderr.isatty()

    def progress(done: int, total: int, path: str) -> None:
        if interactive:
            print(f"\r  indexing          {done}/{total}", end="", file=sys.stderr, flush=True)

    builtin = discovery.resource_dir(info)
    print(f"  builtin headers   {builtin or 'not found; libclang will guess'}")
    sdk = discovery.macos_sdk()
    if sdk:
        print(f"  macOS SDK         {sdk}")

    facts = config.cache_dir / "facts.jsonl"
    report = index_project(root, tus, facts, libclang=library, ignore=config.ignore, jobs=jobs, progress=progress)
    if interactive:
        print("\r" + " " * 40 + "\r", end="", file=sys.stderr)
    failed = report.tus_with_errors
    print(f"  indexed           {len(report.tus)} TUs in {report.wall_s:.1f} s, {len(failed)} with parse errors")
    for tu in failed[:10]:
        print(f"    {tu.path}: {tu.errors} errors; {'; '.join(tu.messages[:2])}", file=sys.stderr)
    if any(t.stl_workaround for t in report.tus):
        print(f"  warning: {info.version} is older than the MSVC STL expects; parsed with _ALLOW_COMPILER_AND_STL_VERSION_MISMATCH",
              file=sys.stderr)
    roles = ", ".join(f"{count} {role}" for role, count in report.refs_by_role.items())
    print(f"  facts             {report.symbols} symbols, {report.refs} refs ({roles}), {report.relations} relations, "
          f"{report.files} files")

    with SQLiteStore(config.cache_dir / "facts.db") as store:
        loaded = load_facts(store, facts, full=full)
    kind = "full load" if loaded.full else "incremental"
    print(f"  store             {loaded.files_loaded} of {loaded.files_total} files loaded ({kind}) in {loaded.seconds:.1f} s")
    return 0 if len(failed) < len(report.tus) else 1


def _init(args) -> int:
    from carma.config import CARMA_DIR, CONFIG_FILE, detect_compile_db, load_config, project_relative, write_config
    from carma.engine.skeleton import build_skeleton
    from carma.model.repo import ModelRepo
    from carma.store.sqlite import SQLiteStore

    root = (args.project or Path.cwd()).resolve()
    print(f"carma init {root}")
    if (root / CARMA_DIR / CONFIG_FILE).is_file():
        if args.compile_commands or args.cmake_build_dir or args.source_root:
            print("  warning: config.yaml exists, so --compile-commands, --cmake-build-dir and --source-root are ignored",
                  file=sys.stderr)
        print(f"  config            {CARMA_DIR}/{CONFIG_FILE} exists")
    else:
        if args.compile_commands:
            compile_db = {"compile_commands": project_relative(root, args.compile_commands)}
        elif args.cmake_build_dir:
            compile_db = {"cmake_build_dir": project_relative(root, args.cmake_build_dir),
                          "configuration": args.configuration or "Debug"}
        else:
            compile_db = detect_compile_db(root)
        if compile_db is None:
            print("carma init: no compile commands found in the project root or build/; "
                  "pass --compile-commands or --cmake-build-dir", file=sys.stderr)
            return 2
        source_roots = [r for r in (project_relative(root, p) for p in args.source_root) if r != "."]
        outside = [r for r in source_roots if r == ".." or r.startswith("../")]
        if outside:
            print(f"carma init: source roots must be inside the project: {', '.join(outside)}", file=sys.stderr)
            return 2
        write_config(root, compile_db, source_roots)
        source = ", ".join(f"{k}: {v}" for k, v in compile_db.items())
        print(f"  config            created {CARMA_DIR}/{CONFIG_FILE} ({source})")

    config = load_config(root)
    with SQLiteStore(config.cache_dir / "facts.db") as store:
        indexed = store.stats().files
    if not indexed:
        print("  facts             the store is empty, indexing first")
        code = _run_index(config, jobs=args.jobs, full=False)
        if code:
            return code

    repo = ModelRepo(config.carma_dir / "model")
    existing = repo.files()
    if existing:
        print(f"  model             {len(existing)} component files exist, the skeleton is not written")
        return 0
    with SQLiteStore(config.cache_dir / "facts.db") as store:
        files = store.list_files()
    skeleton = build_skeleton(files, config.source_roots, config.ignore, config.skeleton_depth, root.name)
    if not skeleton:
        print("carma init: no folders with indexed files outside the ignore globs", file=sys.stderr)
        return 1
    for component in skeleton:
        repo.create(component.data())
    print(f"  model             {len(skeleton)} components from the folders of indexed files:")
    width = max(len(c.id) for c in skeleton)
    for c in skeleton:
        print(f"    {c.id:<{width}}  {c.kind:<9}  {c.path}  ({c.files} files)")
    print("  next              describe intent and requires, then run carma check")
    return 0


def _check(args) -> int:
    from carma.config import ConfigError, load_config
    from carma.engine.core import Core
    from carma.engine.tree import EXTERNAL, UNASSIGNED, VIRTUAL
    from carma.store.sqlite import SQLiteStore

    config = load_config(_project_root(args))
    print(f"carma check {config.project_root}")
    db = config.cache_dir / "facts.db"
    if not db.is_file():
        raise ConfigError(f"no facts in {db}: run carma index first")
    with SQLiteStore(db) as store:
        if not store.stats().files:
            raise ConfigError(f"no facts in {db}: run carma index first")
        state = Core(config, store).load()
    own = state.membership.own
    invalid = f", {len(state.model.invalid)} invalid files" if state.model.invalid else ""
    print(f"  model             {len(state.model.components)} components{invalid}")
    print(f"  symbols           {sum(n for c, n in own.items() if c not in VIRTUAL)} in components, "
          f"{own[UNASSIGNED]} unassigned, {own[EXTERNAL]} external")
    for issue in state.issues:
        print(f"  {issue.code:<22} {issue.describe()}")
    count = len(state.issues)
    print(f"{count} issue{'' if count == 1 else 's'}" if count else "no issues")
    return 1 if count else 0


HANDLERS = {"index": _index, "init": _init, "check": _check}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = HANDLERS.get(args.command)
    if handler is None:
        _, milestone = COMMANDS[args.command]
        print(f"carma {args.command}: not implemented yet (milestone {milestone})", file=sys.stderr)
        return 2
    from carma.compiledb import CompileDbError
    from carma.config import ConfigError
    from carma.indexers.libclang.discovery import LibclangError
    from carma.model.repo import ModelError
    from carma.store.loader import FactsError

    try:
        return handler(args)
    except (ConfigError, CompileDbError, LibclangError, FactsError, ModelError) as exc:
        print(f"carma {args.command}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
