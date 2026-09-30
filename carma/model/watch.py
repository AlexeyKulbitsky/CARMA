"""Watching .carma/model/ so hand edits reach the core without a restart (spec «Правила записи»)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from watchfiles import watch

log = logging.getLogger(__name__)


def _is_component_file(_change, path: str) -> bool:
    name = Path(path).name
    return name.endswith(".yaml") and not name.startswith(".")


class ModelWatcher:
    """Calls on_change from a background thread after component files change; stop() ends it."""

    def __init__(self, folder: Path, on_change: Callable[[], None], debounce_ms: int = 200):
        self.folder = folder
        self.on_change = on_change
        self.debounce_ms = debounce_ms
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._run, name="carma-model-watch", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def _run(self) -> None:
        changes = watch(self.folder, watch_filter=_is_component_file, debounce=self.debounce_ms, stop_event=self._stop,
                        yield_on_timeout=True, rust_timeout=500, raise_interrupt=False)
        for batch in changes:
            self._ready.set()  # the first timeout tick means the OS watcher is in place
            if batch:
                try:
                    self.on_change()
                except Exception:  # a bad reload must not stop the watcher
                    log.exception("reloading the model after a file change failed")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
