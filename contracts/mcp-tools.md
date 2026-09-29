# CARMA MCP tools (contract 5, mcp/0.1)

The MCP server (`carma mcp`) is a thin stdio client of the core's View API. It holds no logic of its own. The agent writes to the model only through these tools and never edits `.carma/` files directly.

The table below is the contract: contract tests compare the server's tool list with the first column. Argument types use JSON Schema names; `?` marks an optional argument, `=x` a default.

| Tool | Arguments | Returns |
| --- | --- | --- |
| `carma_status` | — | Contract versions, fact statistics, indexing platform, current highlight |
| `list_components` | `parent?: string` | Component tree with symbol counts and issues |
| `get_component` | `id: string` | Model, computed statuses, interface symbols, incoming and outgoing edges |
| `component_deps` | `id: string`, `direction: "out" \| "in"` | Edges with reference counts and 3–5 sample references per edge |
| `search_symbols` | `query: string`, `kind?: string`, `limit: integer =20` | Symbols with their component and `path:line` |
| `get_symbol` | `id: string` | Signature, documentation, definitions, component |
| `callers` | `id: string`, `depth: integer =1`, `limit: integer =50` | Call edges with `path:line` |
| `callees` | `id: string`, `depth: integer =1`, `limit: integer =50` | Call edges with `path:line` |
| `find_paths` | `from_id: string`, `to_id: string`, `max_depth: integer =6`, `limit: integer =5` | Call chains as lists of symbol IDs |
| `highlight` | `title: string`, `steps: array` of `{symbols?: string[], components?: string[], caption: string}` | Confirmation and a preview at the root level |
| `clear_highlight` | — | Confirmation |
| `annotate_component` | `id: string`, `patch: object` | Updated component or validation errors |
| `propose_component` | `id: string`, `name: string`, `parent?: string`, `intent: string`, `requires: array`, `provides: array`, `attach_points: array` | Created component with `lifecycle: planned` |

## Rules

- `annotate_component` changes only `intent`, `runtime`, `invariants`, `notes`, `provides`, `requires`, and recomputes `sync.fingerprint` after writing. Agent notes get `source: agent`.
- `intent` is written only when it is empty or has `intent_source: agent`; it then gets `intent_source: agent`. Otherwise the core returns an error and the agent adds a note instead.
- Responses are compact: long lists are cut with a count of what is left and a continuation cursor.
- If the core is not running, every tool answers with a clear error telling the user to run `carma serve`.
