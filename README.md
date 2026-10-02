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
- The standalone application opens folders and recent projects, prepares new C++ projects with progress and cancellation, and restores saved map positions and viewing state (M3.5).

The agent over MCP with highlighted routes (M4) is next.

## Opening the application

On Windows, double click `CARMA.exe` in the portable application's folder. Keep `_internal/` beside it. There is no terminal and no launch configuration to enter.

Choose **Open project folder…**, then select your C++ codebase. CARMA opens an existing map immediately. For a new project, it detects existing compilation databases, CMake builds and presets; choose a named build configuration if several are available, then click **Build map**. Preparation runs in the background with progress and **Cancel**. Your project's C++ compiler/SDK and external dependencies must be available; setup errors appear in the window with expandable details.

**Projects** returns to recent projects. **Update map** refreshes the indexed code while preserving the model and manual positions. Saved projects reopen at the last level with the same camera and filters. Positions live in `.carma/layout.json`, viewing state in `.carma/workspace.json`, and derived automatic layouts in `.carma/cache/layouts/`. Recent projects live in the application's user data directory. A moved project can be located again from the recent list.

The portable build includes Python, the compiled UI, libclang with its builtin headers and CMake. The current Windows window uses the system WebView2 Runtime. Desktop source installs use the `desktop` extra; the Linux window uses PySide6 and macOS uses WebKit.

The window is replaceable: `carma/presentation/api.py` is the small host contract, and `carma/presentation/webview.py` is the current implementation. `carma/application/` owns project management and jobs without importing GUI libraries. Native WPF/OpenGL clients can use the same View API and plain JSON state; no project logic is tied to React or pywebview.

## Using the map from the CLI

For a source checkout, build the UI once (`cd ui && npm ci && npm run build && cd ..`), then run:

```sh
uv sync
uv run carma init --project /path/to/cpp-project
uv run carma serve --project /path/to/cpp-project --open
```

`init` needs a configured CMake project or `compile_commands.json`. If the model and facts already exist, start with `serve`. The map opens at `http://127.0.0.1:8765`.

- Double click a component to enter it. Use the breadcrumbs or browser Back to return. The current level is in the URL, so you can bookmark it.
- On a leaf level, class, struct and union blocks show their fields and methods. Scroll inside a block to see the complete lists, or select the block for full signatures in the right panel. Choose a member to inspect it and open its source location.
- Click a node or connection to inspect it in the right panel. For a complete keyboard-accessible list, expand **Browse map** in that panel; it includes nodes outside the visible viewport and connections hidden by the filter.
- Search by component or symbol name. Use Up/Down and Enter to choose a result; Escape closes the suggestions.
- Choose **refs**, **calls**, or **uses** to change connection width and labels. The minimum slider hides weaker connections; **Show all** restores them. Select a node to see only its connections. The panel explains the line styles and issues.
- Drag the canvas to pan, use the mouse wheel or zoom controls to zoom, and use the minimap to find another area. Drag a node to pin it; the panel's **Adjust node position** buttons offer keyboard control. **Reset layout** removes saved pins.
- At a symbol, **Open in editor** follows the `editor_uri` template in `.carma/config.yaml`; the default VS Code link requires VS Code to be installed.

## Development

Requires [uv](https://docs.astral.sh/uv/) and CMake ≥ 3.20; the indexer also needs LLVM ≥ 19. The UI needs Node 24 for development only.

```
uv sync
uv run pytest
cd ui && npm ci && npm test && npm run build
```

Build and check the standalone application on its target OS:

```sh
uv sync --extra desktop --group build
uv run python scripts/build_desktop.py
```

The output is `dist/CARMA/` on Windows/Linux, and an application bundle on macOS. `scripts/check_desktop.py` checks the packaged Windows worker on a fresh project with external tools removed from PATH. `scripts/check_window.py` exercises project creation, map rendering, manual positioning and viewing-state restoration in a hidden native Windows window. Set `CARMA_DATA_DIR` to isolate application settings for development.

## License

MIT, see [LICENSE](LICENSE).
