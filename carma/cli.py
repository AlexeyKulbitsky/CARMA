"""carma command line: init | index | serve | check | mcp."""

from __future__ import annotations

import argparse
import sys

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
        sub.add_parser(name, help=help_text)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _, milestone = COMMANDS[args.command]
    print(f"carma {args.command}: not implemented yet (milestone {milestone})", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
