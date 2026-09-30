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
        cmd.add_argument("--project", type=Path, help="project root with .carma/config.yaml (default: search from the current folder)")
        if name == "index":
            cmd.add_argument("--jobs", type=int, help="worker processes (default: number of CPUs)")
            cmd.add_argument("--full", action="store_true", help="reload every file into the store")
    return parser


def _project_root(args) -> Path:
    from carma.config import find_project_root

    return args.project.resolve() if args.project else find_project_root(Path.cwd())


def _index(args) -> int:
    from carma import compiledb
    from carma.config import load_config
    from carma.indexers.libclang import discovery
    from carma.indexers.libclang.indexer import index_project, select_tus
    from carma.store.loader import load_facts
    from carma.store.sqlite import SQLiteStore

    config = load_config(_project_root(args))
    root = config.project_root
    print(f"carma index {root}")

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
    report = index_project(root, tus, facts, libclang=library, ignore=config.ignore, jobs=args.jobs, progress=progress)
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
        loaded = load_facts(store, facts, full=args.full)
    kind = "full load" if loaded.full else "incremental"
    print(f"  store             {loaded.files_loaded} of {loaded.files_total} files loaded ({kind}) in {loaded.seconds:.1f} s")
    return 0 if len(failed) < len(report.tus) else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "index":
        from carma.compiledb import CompileDbError
        from carma.config import ConfigError
        from carma.indexers.libclang.discovery import LibclangError

        try:
            return _index(args)
        except (ConfigError, CompileDbError, LibclangError) as exc:
            print(f"carma index: {exc}", file=sys.stderr)
            return 2
    _, milestone = COMMANDS[args.command]
    print(f"carma {args.command}: not implemented yet (milestone {milestone})", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
