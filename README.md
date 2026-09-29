# CARMA

**Code As Result of Modeled Architecture** — *every codebase has its karma.*

CARMA indexes a C++ codebase, draws an architecture map of it, and lets an agent (Claude Code over MCP) answer questions about the code by highlighting the route on the map. The map is backed by two layers:

- **facts** — symbols, references, calls and inheritance extracted from the code by libclang; never edited, always recomputed;
- **model** — YAML files with components, intent, dependencies and domain annotations; the only layer people and the agent edit.

A deterministic core joins the two: it assigns symbols to components, aggregates edges, finds undeclared dependencies and cycles, and serves one level of the map at a time.

CARMA runs natively on Windows, macOS and Linux.

## Status

Early development. Milestone M0 (skeleton, contracts, reference project) is done; the indexer (M1) is next.

## Development

Requires [uv](https://docs.astral.sh/uv/) and CMake ≥ 3.20; the indexer (from M1) also needs LLVM ≥ 19.

```
uv sync
uv run pytest
```

## License

MIT, see [LICENSE](LICENSE).
