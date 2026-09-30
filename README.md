# CARMA

**Code As Result of Modeled Architecture** — *every codebase has its karma.*

CARMA indexes a C++ codebase, draws an architecture map of it, and lets an agent (Claude Code over MCP) answer questions about the code by highlighting the route on the map. The map is backed by two layers:

- **facts** — symbols, references, calls and inheritance extracted from the code by libclang; never edited, always recomputed;
- **model** — YAML files with components, intent, dependencies and domain annotations; the only layer people and the agent edit.

A deterministic core joins the two: it assigns symbols to components, aggregates edges, finds undeclared dependencies and cycles, and serves one level of the map at a time.

CARMA runs natively on Windows, macOS and Linux.

## Status

Early development. Working today:

- `carma index` turns a CMake or `compile_commands.json` project into facts in SQLite (M1);
- `carma init` writes the model skeleton from the folders, `carma check` reports undeclared dependencies, cycles and other model issues (M2);
- `carma serve` serves the View API and the map: one level at a time, drill-down, search, symbol panel, open in editor (M3).

The agent over MCP with highlighted routes (M4) is next.

## Development

Requires [uv](https://docs.astral.sh/uv/) and CMake ≥ 3.20; the indexer also needs LLVM ≥ 19. The UI needs Node 24 for development only.

```
uv sync
uv run pytest
cd ui && npm ci && npm test && npm run build
```

## License

MIT, see [LICENSE](LICENSE).
