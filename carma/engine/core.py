"""The core: the model joined with the facts and recomputed as a whole on every change.

Facts reload -> membership -> edges -> checks -> facts_changed.
Model file change (through the core or by hand) -> validation -> membership -> edges -> checks -> model_changed.
One lock serializes everything that touches the state or the store, so the watcher thread and
request threads can share a core.
"""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from carma.config import Config
from carma.engine import queries, views
from carma.engine.checks import Issue
from carma.engine.highlight import Highlight, LiftedHighlight, lift, parse_highlight
from carma.engine.state import State, build_state
from carma.engine.symbols import SymbolInfo, place_loc
from carma.engine.tree import ROOT
from carma.model.layout import Positions, load_layout, save_layout
from carma.model.repo import ModelRepo, ModelSnapshot
from carma.model.watch import ModelWatcher
from carma.store.api import CallEdge, FactStore, Ref, StoreStats, Symbol

Listener = Callable[[str], None]


class UnknownSymbol(KeyError):
    pass


@dataclass(frozen=True)
class SymbolCard:
    symbol: Symbol
    component: str | None  # None for namespaces
    place: tuple[str, str] | None  # (scope, node) of the level that draws it
    editor_uri: str | None


@dataclass(frozen=True)
class Status:
    project_root: str
    facts: StoreStats
    components: int
    invalid_files: tuple[str, ...]
    issues: int
    highlight: bool


class Core:
    def __init__(self, config: Config, store: FactStore):
        self.config = config
        self.store = store
        self.repo = ModelRepo(config.carma_dir / "model")
        self._lock = threading.RLock()
        self._listeners: list[Listener] = []
        self._symbols: dict[str, SymbolInfo] = {}
        self._model: ModelSnapshot | None = None
        self._highlight: Highlight | None = None
        self._watcher: ModelWatcher | None = None
        self._state: State | None = None

    # ---------------------------------------------------------------- pipeline

    def load(self) -> State:
        with self._lock:
            self._symbols = self._read_symbols()
            self._model = self.repo.load()
            return self._recompute()

    @property
    def state(self) -> State:
        with self._lock:
            return self._state if self._state is not None else self.load()

    def _read_symbols(self) -> dict[str, SymbolInfo]:
        return {s.id: SymbolInfo.from_symbol(s) for s in self.store.iter_symbols()}

    def _recompute(self) -> State:
        self._state = build_state(self._model, self._symbols, self.store, ignore=self.config.ignore,
                                  layout=load_layout(self.config.carma_dir), max_nodes=self.config.max_nodes)
        return self._state

    def reload_facts(self) -> State:
        with self._lock:
            self._symbols = self._read_symbols()
            if self._model is None:
                self._model = self.repo.load()
            state = self._recompute()
            self._emit("facts_changed")
            return state

    def reload_model(self) -> bool:
        """Recompute after model files changed; False when their content is what the core already has."""
        with self._lock:
            model = self.repo.load()
            if self._state is not None and self._model is not None and model.digest == self._model.digest:
                return False
            self._model = model
            if not self._symbols:
                self._symbols = self._read_symbols()
            self._recompute()
            self._emit("model_changed")
            return True

    # ---------------------------------------------------------------- reading

    def issues(self) -> list[Issue]:
        return list(self.state.issues)

    def view(self, scope: str) -> views.View:
        with self._lock:
            return views.view(self.state, self.store, scope)

    def status(self) -> Status:
        with self._lock:
            state = self.state
            return Status(project_root=str(self.config.project_root), facts=self.store.stats(),
                          components=len(state.model.components), invalid_files=tuple(sorted(state.model.invalid)),
                          issues=len(state.issues), highlight=self._highlight is not None)

    def component_tree(self, parent: str = ROOT) -> tuple[queries.TreeNode, ...]:
        with self._lock:
            return queries.component_tree(self.state, parent)

    def component_card(self, component_id: str) -> queries.ComponentCard:
        with self._lock:
            return queries.component_card(self.state, component_id)

    def edge_samples(self, scope: str, src: str, dst: str, limit: int = 20) -> tuple[list[Ref], bool]:
        with self._lock:
            return views.edge_samples(self.state, self.store, scope, src, dst, limit)

    # ---------------------------------------------------------------- symbols

    def component_of(self, symbol_id: str) -> str | None:
        return self.state.membership.component_of.get(symbol_id)

    def symbol_name(self, symbol_id: str) -> str:
        info = self.state.symbols.get(symbol_id)
        return info.name if info else symbol_id

    def search_symbols(self, text: str, kinds: list[str] | None = None, limit: int = 50) -> tuple[list[Symbol], bool]:
        with self._lock:
            found = self.store.search_symbols(text, kinds, limit + 1)
            return found[:limit], len(found) > limit

    def symbol(self, symbol_id: str) -> SymbolCard:
        with self._lock:
            symbol = self.store.get_symbol(symbol_id)
            if symbol is None:
                raise UnknownSymbol(symbol_id)
            loc = place_loc(symbol)
            uri = self.config.editor_link(loc.path, loc.range[0] + 1) if loc and not symbol.external else None
            return SymbolCard(symbol, self.component_of(symbol_id), views.symbol_place(self.state, symbol_id), uri)

    def _known(self, symbol_id: str) -> None:
        if symbol_id not in self.state.symbols:
            raise UnknownSymbol(symbol_id)

    def callers(self, symbol_id: str, depth: int = 1) -> list[CallEdge]:
        with self._lock:
            self._known(symbol_id)
            return self.store.callers(symbol_id, depth)

    def callees(self, symbol_id: str, depth: int = 1) -> list[CallEdge]:
        with self._lock:
            self._known(symbol_id)
            return self.store.callees(symbol_id, depth)

    def paths(self, src: str, dst: str, max_depth: int = 6, limit: int = 5) -> list[list[str]]:
        with self._lock:
            self._known(src)
            self._known(dst)
            return self.store.paths(src, dst, max_depth, limit)

    # ---------------------------------------------------------------- model writes

    def create_component(self, data: dict) -> dict:
        with self._lock:
            written = self.repo.create(data)
            self.reload_model()
            return written

    def write_component(self, data: dict) -> dict:
        with self._lock:
            written = self.repo.write(data)
            self.reload_model()
            return written

    def patch_component(self, component_id: str, patch: dict) -> dict:
        with self._lock:
            written = self.repo.patch(component_id, patch)
            self.reload_model()
            return written

    def delete_component(self, component_id: str) -> None:
        with self._lock:
            self.repo.delete(component_id)
            self.reload_model()

    def save_layout(self, scope: str, positions: Positions) -> None:
        with self._lock:
            views.level_of(self.state, scope)  # UnknownScope for a level that does not exist
            layout = save_layout(self.config.carma_dir, scope, positions)
            self._state = dataclasses.replace(self.state, layout=layout)

    # ---------------------------------------------------------------- highlight

    def set_highlight(self, data: Any) -> Highlight:
        highlight = parse_highlight(data)
        with self._lock:
            self._highlight = highlight
            self._emit("highlight_changed")
        return highlight

    def clear_highlight(self) -> None:
        with self._lock:
            self._highlight = None
            self._emit("highlight_changed")

    def highlight(self, scope: str) -> LiftedHighlight | None:
        with self._lock:
            if self._highlight is None:
                return None
            return lift(self._highlight, self.view(scope), self.state)

    # ---------------------------------------------------------------- events and watching

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _emit(self, event: str) -> None:
        for listener in list(self._listeners):
            listener(event)

    def watch_model(self) -> None:
        if self._watcher is None:
            self._watcher = ModelWatcher(self.repo.folder, self.reload_model)
            self._watcher.start()

    def close(self) -> None:
        if self._watcher is not None:
            self._watcher.stop()
            self._watcher = None
