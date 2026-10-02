"""Contract 4: the View API over HTTP and SSE, and the built UI (spec «Контракт 4: View API»).

Every route is a thin translation of a Core method; the core holds the lock, so the routes run in
FastAPI's thread pool.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from urllib.parse import urlsplit
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from carma import __version__
from carma.api import schemas as s
from carma.api.application import build_application_router
from carma.application.preparation import ApplicationError
from carma.application.manager import ProjectManager
from carma.engine import views
from carma.config import SCHEMA_VERSION as CONFIG_VERSION
from carma.config import ConfigError
from carma.compiledb.model import CompileDbError
from carma.engine.core import Core, UnknownSymbol
from carma.engine.symbols import place_loc
from carma.engine.tree import ROOT, UNASSIGNED
from carma.model import yaml_io
from carma.model.layout import LAYOUT_VERSION
from carma.model.workspace import load_workspace, save_workspace
from carma.model.json_io import read_json, write_json
from carma.model.repo import SCHEMA_VERSION, ModelValidationError, UnknownComponentError
from carma.store.api import CONTRACT_VERSION as STORE_VERSION
from carma.store.api import Loc, Ref

PREFIX = "/api/v0"
EVENTS = ("facts_changed", "model_changed", "highlight_changed", "reindex_progress")
ERRORS = {404: {"model": s.ErrorResponse, "description": "unknown ID or scope"},
          422: {"model": s.ErrorResponse, "description": "invalid request"}}
UI_DIR = Path(__file__).resolve().parent.parent / "_ui"


def _core(request: Request):
    manager = request.app.state.manager
    if manager is not None:
        with manager.lease(request.headers.get("X-Carma-Project")) as core:
            yield core
        return
    core = request.app.state.core
    if core is None:
        raise StarletteHTTPException(503, "no project is loaded")
    yield core


def _stream_core(request: Request) -> Core:
    """Event streams do not lease the session for their entire lifetime."""
    manager = request.app.state.manager
    if manager is not None:
        with manager.lease(request.headers.get("X-Carma-Project")) as core:
            return core
    core = request.app.state.core
    if core is None:
        raise StarletteHTTPException(503, "no project is loaded")
    return core


CoreDep = Annotated[Core, Depends(_core)]


def _loc(loc: Loc) -> s.Location:
    return s.Location(path=loc.path, line=loc.range[0] + 1, column=loc.range[1] + 1, end_line=loc.extent[2] + 1)


def _ref(ref: Ref) -> s.RefSample:
    return s.RefSample(symbol=ref.symbol, container=ref.container, path=ref.path, line=ref.range[0] + 1,
                       column=ref.range[1] + 1, roles=sorted(ref.roles))


def _node(n: views.Node) -> s.ViewNode:
    return s.ViewNode(id=n.id, name=n.name, type=n.type, kind=n.kind, lifecycle=n.lifecycle, intent_short=n.intent_short,
                      symbols=n.symbols, children=n.children, file=n.file, issues=list(n.issues),
                      pos=s.Position(x=n.pos[0], y=n.pos[1]) if n.pos else None, metrics=dict(n.metrics),
                      members=[s.ViewMember(id=m.id, name=m.name, kind=m.kind, signature=m.signature, access=m.access)
                               for m in n.members])


def _tree(n) -> s.TreeNode:
    return s.TreeNode(id=n.id, name=n.name, kind=n.kind, lifecycle=n.lifecycle, symbols=n.symbols,
                      own_symbols=n.own_symbols, issues=list(n.issues), children=[_tree(c) for c in n.children])


def _issue(i) -> s.Issue:
    return s.Issue(code=i.code, component=i.component, target=i.target, members=list(i.members), scope=i.scope,
                   symbols=list(i.symbols), count=i.count, message=i.message, text=i.describe())


def _error(status: int, code: str, message: str, details: list | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details or []}})


def build_router() -> APIRouter:
    r = APIRouter(prefix=PREFIX, responses=ERRORS)

    @r.get("/status", response_model=s.Status, summary="Contract versions, fact statistics, platform, model counts")
    def status(core: CoreDep) -> s.Status:
        st = core.status()
        f = st.facts
        return s.Status(
            version=__version__,
            contracts=s.Contracts(api=s.API_VERSION, facts=f.facts_version, store=STORE_VERSION, model=SCHEMA_VERSION,
                                  config=CONFIG_VERSION, layout=LAYOUT_VERSION),
            project_root=st.project_root, project_name=Path(st.project_root).name,
            facts=s.FactsStatus(files=f.files, symbols=f.symbols, refs=f.refs, relations=f.relations,
                                facts_version=f.facts_version, platform=f.platform, loaded_at=f.loaded_at),
            components=st.components, invalid_files=list(st.invalid_files), issues=st.issues, highlight=st.highlight)

    @r.get("/view", response_model=s.View, summary="Nodes, edges, issues and pinned positions of one level")
    def view(core: CoreDep, scope: str = ROOT) -> s.View:
        v = core.view(scope)
        return s.View(scope=v.scope, level=v.level, component=v.component,
                      trail=[s.Crumb(scope=a, name=b) for a, b in v.trail], nodes=[_node(n) for n in v.nodes],
                      edges=[s.ViewEdge(src=e.src, dst=e.dst, refs=e.refs, calls=e.calls, uses=e.uses, declared=e.declared,
                                        issues=list(e.issues), metrics=dict(e.metrics)) for e in v.edges],
                      boundary=[_node(n) for n in v.boundary], grouped_by=v.grouped_by)

    @r.get("/components", response_model=s.ComponentTree, summary="Component tree with symbol counts and issues")
    def components(core: CoreDep, parent: str = ROOT) -> s.ComponentTree:
        tree = core.component_tree(parent)
        return s.ComponentTree(parent=parent, components=[_tree(n) for n in tree],
                               unassigned=core.state.membership.own[UNASSIGNED] if parent == ROOT else 0)

    @r.get("/components/{component_id}", response_model=s.ComponentCard,
           summary="Component model, computed issues, interface symbols, incoming and outgoing edges")
    def component(core: CoreDep, component_id: str) -> s.ComponentCard:
        c = core.component_card(component_id)
        edge = lambda e: s.DependencyEdge(node=e.node, refs=e.refs, calls=e.calls, uses=e.uses, declared=e.declared)  # noqa: E731
        return s.ComponentCard(
            id=c.id, parent=c.parent, children=list(c.children), model=c.data, symbols=c.symbols,
            own_symbols=c.own_symbols, issues=[_issue(i) for i in c.issues],
            interface=[s.InterfaceSymbol(id=sid, present=info is not None, name=info.name if info else None,
                                         kind=info.kind if info else None, signature=info.signature if info else None,
                                         path=info.place if info else None) for sid, info in c.interface],
            fingerprint=c.fingerprint, edges_out=[edge(e) for e in c.edges_out], edges_in=[edge(e) for e in c.edges_in])

    @r.get("/symbols/search", response_model=s.SymbolList, summary="Symbols by name")
    def search(core: CoreDep, q: Annotated[str, Query(min_length=1)],
               kind: Annotated[list[str] | None, Query(description="repeat for several kinds")] = None,
               limit: Annotated[int, Query(ge=1, le=500)] = 50) -> s.SymbolList:
        found, more = core.search_symbols(q, kind, limit)
        items = []
        for sym in found:
            place = place_loc(sym)
            items.append(s.SymbolBrief(id=sym.id, name=sym.display_name, kind=sym.kind, signature=sym.signature,
                                       component=core.component_of(sym.id), path=place.path if place else None,
                                       line=place.range[0] + 1 if place else None, external=sym.external))
        return s.SymbolList(items=items, more=more)

    @r.get("/symbols", response_model=s.SymbolCard, summary="A symbol, its definition, component and editor link")
    def symbol(core: CoreDep, id: str) -> s.SymbolCard:
        card = core.symbol(id)
        sym = card.symbol
        return s.SymbolCard(id=sym.id, name=sym.display_name, kind=sym.kind, signature=sym.signature, doc=sym.doc,
                            access=sym.access, parent=sym.parent_id, external=sym.external, component=card.component,
                            defs=[_loc(l) for l in sym.defs], decls=[_loc(l) for l in sym.decls],
                            place=s.Place(scope=card.place[0], node=card.place[1]) if card.place else None,
                            editor_uri=card.editor_uri)

    def calls(core: Core, edges, limit: int) -> s.CallList:
        items = [s.CallEdge(caller=e.caller, callee=e.callee, caller_name=core.symbol_name(e.caller),
                            callee_name=core.symbol_name(e.callee), path=e.path, line=e.line + 1, depth=e.depth)
                 for e in edges[:limit]]
        return s.CallList(items=items, more=len(edges) > limit)

    @r.get("/symbols/callers", response_model=s.CallList, summary="Who calls the symbol")
    def callers(core: CoreDep, id: str, depth: Annotated[int, Query(ge=1, le=10)] = 1,
                limit: Annotated[int, Query(ge=1, le=1000)] = 200) -> s.CallList:
        return calls(core, core.callers(id, depth), limit)

    @r.get("/symbols/callees", response_model=s.CallList, summary="What the symbol calls")
    def callees(core: CoreDep, id: str, depth: Annotated[int, Query(ge=1, le=10)] = 1,
                limit: Annotated[int, Query(ge=1, le=1000)] = 200) -> s.CallList:
        return calls(core, core.callees(id, depth), limit)

    @r.get("/paths", response_model=s.PathList, summary="Shortest call chains between two symbols")
    def paths(core: CoreDep, src: Annotated[str, Query(alias="from")], dst: Annotated[str, Query(alias="to")],
              max_depth: Annotated[int, Query(ge=1, le=12)] = 6, limit: Annotated[int, Query(ge=1, le=50)] = 5) -> s.PathList:
        return s.PathList(paths=core.paths(src, dst, max_depth, limit))

    @r.get("/edges/samples", response_model=s.RefList, summary="The refs an edge of a level is made of")
    def samples(core: CoreDep, src: str, dst: str, scope: str = ROOT,
                limit: Annotated[int, Query(ge=1, le=500)] = 20) -> s.RefList:
        refs, more = core.edge_samples(scope, src, dst, limit)
        return s.RefList(items=[_ref(ref) for ref in refs], more=more)

    @r.put("/layout/{scope}", response_model=s.LayoutResult, summary="Save the pinned positions of one level")
    def layout(core: CoreDep, scope: str, body: s.LayoutBody) -> s.LayoutResult:
        positions = {node: {"x": p.x, "y": p.y} for node, p in body.positions.items()}
        core.save_layout(scope, positions)
        return s.LayoutResult(scope=scope, positions=body.positions)

    @r.get("/events", response_class=StreamingResponse, summary="Server-sent events: " + ", ".join(EVENTS),
           responses={200: {"content": {"text/event-stream": {}}, "description": "an event stream"}})
    async def events(request: Request, core: Annotated[Core, Depends(_stream_core)]) -> StreamingResponse:
        queue: asyncio.Queue[str] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        unsubscribe = core.subscribe(lambda event: loop.call_soon_threadsafe(queue.put_nowait, event))
        keepalive = request.app.state.keepalive

        async def stream():
            try:
                yield "retry: 2000\n\n"
                while not await request.is_disconnected():
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=keepalive)
                    except TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    yield f"event: {event}\ndata: {json.dumps({'event': event})}\n\n"
            finally:
                unsubscribe()

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @r.get("/workspace", response_model=s.Workspace, summary="Renderer-independent viewing state")
    def workspace(core: CoreDep):
        return load_workspace(core.config.carma_dir)

    @r.put("/workspace", response_model=s.Workspace, summary="Save the last level, camera and filters")
    def write_workspace(core: CoreDep, body: s.Workspace):
        return save_workspace(core.config.carma_dir, body.model_dump())

    @r.get("/layout-cache/{key}", response_model=s.CachedLayout, summary="Derived node positions for this project and graph")
    def layout_cache(core: CoreDep, key: str):
        if not key.isalnum() or len(key) > 100:
            raise StarletteHTTPException(422, "invalid layout cache key")
        return read_json(core.config.cache_dir / "layouts" / f"{key}.json", {"key": key, "positions": {}})

    @r.put("/layout-cache/{key}", response_model=s.CachedLayout)
    def write_layout_cache(core: CoreDep, key: str, body: s.CachedLayout):
        if not key.isalnum() or len(key) > 100 or key != body.key:
            raise StarletteHTTPException(422, "invalid layout cache key")
        write_json(core.config.cache_dir / "layouts" / f"{key}.json", body.model_dump())
        return body

    return r


def create_app(core: Core | None = None, *, ui_dir: Path | None = UI_DIR, keepalive: float = 15.0,
               manager: ProjectManager | None = None, choose_folder=None) -> FastAPI:
    app = FastAPI(title="CARMA View API", version=s.API_VERSION.split("/")[1], openapi_url=f"{PREFIX}/openapi.json",
                  docs_url=None, redoc_url=None,
                  description="The core's API for the UI and the MCP server (docs/carma-spec.md, «Контракт 4»). "
                              "Symbol IDs contain spaces, '/' and '#', so they always travel as the query parameter id.")
    app.state.core = core
    app.state.manager = manager
    app.state.choose_folder = choose_folder
    app.state.keepalive = keepalive
    app.include_router(build_router())
    app.include_router(build_application_router(PREFIX))

    @app.middleware("http")
    async def local_access(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                return _error(403, "forbidden", "Request came from another application.")
            if manager and not secrets.compare_digest(request.headers.get("X-Carma-Token", ""), manager.token):
                return _error(403, "forbidden", "Application token required.")
        return await call_next(request)

    app.add_exception_handler(ApplicationError, lambda request, exc: _error(
        409 if exc.code in {"busy", "project_changed", "no_project"} else 400, exc.code, str(exc)))
    for failure in (ConfigError, CompileDbError):
        app.add_exception_handler(failure, lambda request, exc: _error(400, "project_error", str(exc)))
    app.add_exception_handler(OSError, lambda request, exc: _error(400, "file_error", "Could not access project files: " + str(exc)))

    for missing in (views.UnknownScope, UnknownComponentError, UnknownSymbol):
        app.add_exception_handler(missing, lambda request, exc: _error(404, "not_found", f"unknown: {exc.args[0]}"))
    app.add_exception_handler(ModelValidationError, lambda request, exc: _error(422, "validation_failed", str(exc), exc.errors))
    app.add_exception_handler(RequestValidationError, lambda request, exc: _error(
        422, "validation_failed", "invalid request", jsonable_encoder(exc.errors())))
    app.add_exception_handler(StarletteHTTPException, lambda request, exc: _error(
        exc.status_code, "not_found" if exc.status_code == 404 else "http_error", str(exc.detail)))

    if ui_dir is not None and (ui_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=ui_dir, html=True), name="ui")
    else:
        @app.get("/", include_in_schema=False)
        def no_ui() -> HTMLResponse:
            return HTMLResponse("<!doctype html><title>CARMA</title><p>The CARMA UI is not built: run "
                                "<code>npm ci</code> and <code>npm run build</code> in <code>ui/</code>. "
                                f"The API is at <code>{PREFIX}</code>.</p>")
    return app


def openapi_yaml() -> str:
    """contracts/openapi.yaml: generated from the routes and committed; CI fails when they differ."""
    return yaml_io.dumps(create_app(ui_dir=None).openapi())
