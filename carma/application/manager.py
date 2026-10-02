"""Application service: one active project, durable recents and cancellable isolated jobs.

There are no GUI imports here. HTTP and native clients share these operations.
"""

from __future__ import annotations

import contextlib
import os
import signal
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from carma.application.files import read_json, write_json
from carma.application.preparation import ApplicationError, discover, project_id, project_path, ready
from carma.config import load_config
from carma.engine.core import Core
from carma.model.repo import ModelRepo
from carma.store.sqlite import SQLiteStore


def data_directory() -> Path:
    override = os.environ.get("CARMA_DATA_DIR")
    if override:
        return Path(override).resolve()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "CARMA"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/CARMA"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "carma"


class ProjectManager:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or data_directory()
        self.token = uuid.uuid4().hex
        self._lock = threading.RLock()
        # A primitive lock may be acquired/released by different API thread-pool threads.
        self._session = threading.Lock()
        self.core: Core | None = None
        self._store: SQLiteStore | None = None
        self._job: dict | None = None
        self._process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._closed = False
        self._warnings: list[str] = []
        self._recent = read_json(self.data_dir / "projects.json", [])

    def _summary(self, root: Path, opened_at: str | None = None) -> dict:
        return {"id": project_id(root), "name": root.name, "path": str(root), "available": root.is_dir(),
                "ready": ready(root), "opened_at": opened_at}

    def state(self) -> dict:
        with self._lock:
            job = dict(self._job) if self._job else None
            if job and job["status"] == "running":
                try:
                    progress = read_json(self.data_dir / "jobs" / job["id"] / "progress.json", {})
                    job.update(progress)
                except (ValueError, OSError):
                    pass  # atomic progress replacement can briefly be unavailable on Windows
            return {"managed": True, "token": self.token,
                    "active": self._summary(self.core.config.project_root) if self.core else None,
                    "projects": [self._summary(Path(p["path"]), p.get("opened_at")) for p in self._recent],
                    "job": job, "warnings": list(self._warnings)}

    def inspect(self, value: str) -> dict:
        root = project_path(value)
        return {"project": self._summary(root), "choices": discover(root)}

    def _remember(self, root: Path, replace_id: str | None = None) -> None:
        pid = project_id(root)
        previous = self._recent
        self._recent = [{"path": str(root), "opened_at": datetime.now(timezone.utc).isoformat()},
                        *[p for p in previous if project_id(Path(p["path"])) not in {pid, replace_id}]][:30]
        try:
            write_json(self.data_dir / "projects.json", self._recent)
        except Exception:
            self._recent = previous
            raise

    def forget(self, pid: str) -> dict:
        with self._lock:
            previous = self._recent
            self._recent = [p for p in previous if project_id(Path(p["path"])) != pid]
            try:
                write_json(self.data_dir / "projects.json", self._recent)
            except Exception:
                self._recent = previous
                raise
        return self.state()

    @contextlib.contextmanager
    def lease(self, expected: str | None = None):
        with self._session:
            core = self.core
            if core is None:
                raise ApplicationError("Open a project first.", "no_project")
            if expected and project_id(core.config.project_root) != expected:
                raise ApplicationError("The active project changed. Reload the map.", "project_changed")
            yield core

    def open(self, value: str, build_id: str | None = None, *, reindex: bool = False, replace_id: str | None = None) -> dict:
        root = project_path(value)
        with self._lock:
            if self._closed or (self._job and self._job["status"] == "running"):
                raise ApplicationError("Wait for the current operation or cancel it first.", "busy")
            is_ready = ready(root)
            if is_ready and not reindex:
                choice = None
            else:
                choices = discover(root)
                choice = next((c for c in choices if c["id"] == build_id), None)
                if choice is None and len(choices) == 1 and build_id is None:
                    choice = choices[0]
                if choice is None:
                    raise ApplicationError("Choose a build configuration." if choices else
                                           "No supported C++ build configuration was found. Choose a CMake project or a folder containing compile_commands.json.",
                                           "build_required")
            jid = uuid.uuid4().hex
            self._cancel = threading.Event()
            self._job = {"id": jid, "path": str(root), "status": "running", "stage": "opening",
                         "message": "Opening the saved map" if choice is None else "Preparing the project",
                         "done": 0, "total": 0, "error": None}
            self._thread = threading.Thread(target=self._run, args=(root, choice, jid, reindex, replace_id), daemon=True)
            self._thread.start()
        return self.state()

    def _run(self, root: Path, choice: dict | None, jid: str, reindex: bool, replace_id: str | None) -> None:
        staging = root / ".carma/cache/tasks" / jid / "facts.db"
        try:
            warnings = []
            if choice is not None:
                task = self.data_dir / "jobs" / jid
                spec = task / "spec.json"
                write_json(spec, {"root": str(root), "choice": choice, "staging": str(staging), "reindex": reindex})
                command = ([sys.executable, "--worker", str(spec)] if getattr(sys, "frozen", False) else
                           [sys.executable, "-m", "carma.application.worker", str(spec)])
                environment = os.environ.copy()
                if not getattr(sys, "frozen", False):
                    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2]) + os.pathsep + environment.get("PYTHONPATH", "")
                task.mkdir(parents=True, exist_ok=True)
                with (task / "worker.log").open("w", encoding="utf-8") as log:
                    with self._lock:
                        if self._cancel.is_set():
                            return
                        self._process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                                         env=environment, start_new_session=sys.platform != "win32",
                                                         creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                        process = self._process
                    code = process.wait()
                if self._cancel.is_set():
                    return
                result = read_json(task / "result.json", {})
                if code or not result.get("ok"):
                    raise ApplicationError(result.get("error", "Project preparation stopped unexpectedly. Retry the operation."),
                                           result.get("code", "worker_failed"))
                warnings = result.get("warnings", [])
            # Validate before touching the published database or releasing the previous session.
            config = load_config(root)
            candidate = SQLiteStore(staging if staging.exists() else config.cache_dir / "facts.db")
            try:
                if not candidate.stats().files:
                    raise ApplicationError("This project has no indexed source files. Update the map first.")
                model = staging.parent / "model"
                validation = Core(config, candidate, repo=ModelRepo(model) if model.exists() else None)
                validation.load()
                validation.close()
            finally:
                candidate.close()
            with self._lock:
                if self._cancel.is_set():
                    return
                self._job.update(stage="opening", message="Opening the architecture map", done=0, total=0)
                with self._session:
                    self._activate(root, staging if staging.exists() else None, model if model.exists() else None)
                self._warnings = warnings
                self._remember(root, replace_id)
                self._job.update(status="ready", message="Project ready")
        except Exception as exc:
            with self._lock:
                if not self._cancel.is_set():
                    self._job.update(status="failed", error=str(exc), message="Could not open the project")
        finally:
            with self._lock:
                self._process = None
                if self._cancel.is_set():
                    self._job.update(status="cancelled", message="Operation cancelled")
            # Only remove files created by this job, never recursively delete a project path.
            for name in ("facts.db", "facts.db-wal", "facts.db-shm", "facts.jsonl"):
                (staging.parent / name).unlink(missing_ok=True)
            model = staging.parent / "model"
            if model.exists():
                for file in model.glob("*.yaml"):
                    file.unlink()
                model.rmdir()

    def _release(self) -> None:
        if self.core:
            self.core.close()
            self.core = None
        if self._store:
            self._store.close()
            self._store = None

    def _load(self, root: Path) -> None:
        config = load_config(root)
        store = SQLiteStore(config.cache_dir / "facts.db")
        core = Core(config, store)
        try:
            core.load()
            core.watch_model()
        except Exception:
            core.close()
            store.close()
            raise
        self.core, self._store = core, store

    def _activate(self, root: Path, staging: Path | None, model: Path | None = None) -> None:
        previous = self.core.config.project_root if self.core else None
        self._release()
        target = root / ".carma/cache/facts.db"
        backup = staging.parent / "previous.db" if staging else None
        moved = False
        published = False
        published_model = False
        destination = root / ".carma/model"
        try:
            if model and not any(destination.glob("*.yaml")):
                if destination.exists():
                    destination.rmdir()  # only an empty directory; never recursively delete user data
                os.replace(model, destination)
                published_model = True
            if staging:
                if target.exists():
                    shutil.copy2(target, backup)
                    moved = True
                os.replace(staging, target)
                published = True
            self._load(root)
        except Exception:
            if moved and published:
                os.replace(backup, target)
            if published_model:
                os.replace(destination, model)
            if previous:
                self._load(previous)
            raise
        finally:
            if backup and backup.exists() and self.core is not None:
                backup.unlink()

    def cancel(self) -> dict:
        with self._lock:
            if self._job and self._job["status"] == "running":
                self._cancel.set()
                process = self._process
                if process and process.poll() is None:
                    if sys.platform == "win32":
                        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
                    else:
                        os.killpg(process.pid, signal.SIGTERM)
        return self.state()

    def close_project(self) -> dict:
        with self._lock:
            if self._job and self._job["status"] == "running":
                raise ApplicationError("Cancel or finish the current operation before closing the project.", "busy")
            with self._session:
                self._release()
            self._warnings = []
        return self.state()

    def shutdown(self) -> None:
        self.cancel()
        if self._thread:
            self._thread.join(timeout=15)
        with self._lock:
            self._closed = True
            with self._session:
                self._release()
