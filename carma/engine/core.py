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
from typing import Any

from carma.config import Config
from carma.engine import views
from carma.engine.checks import Issue
from carma.engine.highlight import Highlight, LiftedHighlight, lift, parse_highlight
from carma.engine.state import State, build_state
from carma.engine.symbols import SymbolInfo
from carma.model.layout import Positions, load_layout, save_layout
from carma.model.repo import ModelRepo, ModelSnapshot
from carma.model.watch import ModelWatcher
from carma.store.api import FactStore

Listener = Callable[[str], None]


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
