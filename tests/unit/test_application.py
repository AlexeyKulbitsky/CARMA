"""Project lifetime, safe failures and cross-renderer durable state."""

import time

import pytest
from fastapi.testclient import TestClient

from carma.api.app import PREFIX, create_app
from carma.application.manager import ProjectManager
from carma.application.preparation import ApplicationError, discover, prepare, project_id
from carma.model.workspace import load_workspace


def wait(manager):
    deadline = time.monotonic() + 30
    while manager.state()["job"]["status"] == "running":
        assert time.monotonic() < deadline
        time.sleep(.02)
    return manager.state()


@pytest.fixture
def manager(tmp_path):
    service = ProjectManager(tmp_path / "settings")
    yield service
    service.shutdown()


def test_reopen_restores_recents_and_layout_without_preparation(manager, golden_project, tmp_path):
    manager.open(str(golden_project))
    assert wait(manager)["job"]["status"] == "ready"
    with manager.lease() as core:
        core.save_layout("root", {"render": {"x": 431, "y": 214}})
    manager.close_project()
    # An existing map opens even when build tools/source files are absent.
    manager.open(str(golden_project))
    assert wait(manager)["job"]["status"] == "ready"
    with manager.lease() as core:
        assert next(n.pos for n in core.view("root").nodes if n.id == "render") == (431, 214)
    assert len(manager.state()["projects"]) == 1
    another = ProjectManager(manager.data_dir)
    assert another.state()["projects"][0]["path"] == str(golden_project.resolve())
    another.shutdown()


def test_failed_open_keeps_previous_project_and_database(manager, golden_project, tmp_path):
    manager.open(str(golden_project))
    assert wait(manager)["job"]["status"] == "ready"
    other = tmp_path / "broken"
    (other / "build").mkdir(parents=True)
    (other / "build/compile_commands.json").write_text("[]", encoding="utf-8")
    manager.open(str(other))
    result = wait(manager)
    assert result["job"]["status"] == "failed"
    assert "No C++ source files" in result["job"]["error"]
    assert result["active"]["path"] == str(golden_project.resolve())
    with manager.lease() as core:
        assert core.status().facts.files > 0


def test_workspace_round_trip_and_stale_project_requests(manager, golden_project):
    manager.open(str(golden_project))
    assert wait(manager)["job"]["status"] == "ready"
    with TestClient(create_app(manager=manager, ui_dir=None, choose_folder=lambda: str(golden_project))) as client:
        headers = {"X-Carma-Token": manager.token, "X-Carma-Project": project_id(golden_project)}
        data = {"schema_version": "workspace/0.1", "scope": "render._self", "views": {
            "render._self": {"metric": "calls", "threshold": 3, "camera": {"x": 24, "y": -18, "zoom": 1.2}}}}
        assert client.put(PREFIX + "/workspace", json=data, headers=headers).status_code == 200
        assert load_workspace(golden_project / ".carma") == data
        assert client.get(PREFIX + "/workspace").json() == data
        assert client.get(PREFIX + "/view", headers={"X-Carma-Project": "old-project"}).status_code == 409
        assert client.post(PREFIX + "/app/pick-folder", headers=headers).json()["path"] == str(golden_project)
        assert client.post(PREFIX + "/app/close", headers=headers).status_code == 200
        assert client.get(PREFIX + "/view").status_code == 409


def test_local_mutations_require_instance_token_and_same_origin(manager):
    with TestClient(create_app(manager=manager, ui_dir=None)) as client:
        assert client.post(PREFIX + "/app/cancel").status_code == 403
        assert client.post(PREFIX + "/app/cancel", headers={"X-Carma-Token": manager.token, "Origin": "https://other.invalid"}).status_code == 403
        assert client.post(PREFIX + "/app/cancel", headers={"X-Carma-Token": manager.token}).status_code == 200


def test_discovery_finds_nested_builds_and_does_not_guess_between_them(tmp_path, manager):
    for name in ("out/build/debug", "out/build/release"):
        folder = tmp_path / name
        folder.mkdir(parents=True)
        (folder / "compile_commands.json").write_text("[]", encoding="utf-8")
    assert len(discover(tmp_path)) == 2
    with pytest.raises(ApplicationError, match="Choose a build configuration"):
        manager.open(str(tmp_path))


def test_prepare_reuses_facts_and_preserves_an_existing_model(golden_project, tmp_path):
    model = golden_project / ".carma/model/render.yaml"
    original = model.read_bytes()
    stage = tmp_path / "stage/facts.db"
    prepare(golden_project, {"kind": "saved"}, stage, lambda *args: None, reindex=False)
    assert not stage.exists()
    assert model.read_bytes() == original


def test_application_and_core_do_not_import_renderer_libraries(repo_root):
    import ast
    for folder in ("application", "engine"):
        for path in (repo_root / "carma" / folder).glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
            names += [alias.name for n in ast.walk(tree) if isinstance(n, ast.Import) for alias in n.names]
            assert not any(n.startswith(("carma.presentation", "webview", "PySide", "PyQt", "tkinter")) for n in names), path


def test_cancelling_update_keeps_the_published_map(manager, golden_project, monkeypatch):
    import subprocess
    import sys
    manager.open(str(golden_project))
    assert wait(manager)["job"]["status"] == "ready"
    original = manager.core.status().facts
    real_popen = subprocess.Popen

    def slow_worker(command, **kwargs):
        if "carma.application.worker" in command:
            command = [sys.executable, "-c", "import time; time.sleep(60)"]
        return real_popen(command, **kwargs)

    monkeypatch.setattr("carma.application.manager.subprocess.Popen", slow_worker)
    manager.open(str(golden_project), reindex=True)
    deadline = time.monotonic() + 10
    while manager._process is None:
        assert time.monotonic() < deadline
        time.sleep(.02)
    process = manager._process
    started = time.monotonic()
    manager.cancel()
    assert wait(manager)["job"]["status"] == "cancelled"
    assert process.poll() is not None
    assert time.monotonic() - started < 5
    assert manager.core.status().facts == original


def test_initial_model_is_staged_until_project_activation(make_golden, tmp_path):
    project = make_golden(model=False)
    stage = tmp_path / "task/facts.db"
    prepare(project, {"kind": "saved"}, stage, lambda *args: None, reindex=False)
    assert list((stage.parent / "model").glob("*.yaml"))
    assert not list((project / ".carma/model").glob("*.yaml"))


def test_locating_a_moved_project_replaces_the_old_recent_entry(tmp_path, golden_project):
    from carma.application.files import write_json
    settings = tmp_path / "settings"
    old = tmp_path / "unavailable"
    write_json(settings / "projects.json", [{"path": str(old), "opened_at": None}])
    service = ProjectManager(settings)
    try:
        assert not service.state()["projects"][0]["available"]
        service.open(str(golden_project), replace_id=project_id(old))
        assert wait(service)["job"]["status"] == "ready"
        assert [p["path"] for p in service.state()["projects"]] == [str(golden_project.resolve())]
    finally:
        service.shutdown()


def test_application_lifetime_can_use_another_window(tmp_path, monkeypatch):
    import httpx2
    from carma.desktop import main
    monkeypatch.setenv("CARMA_DATA_DIR", str(tmp_path / "settings"))
    monkeypatch.setattr("sys.argv", ["carma-app"])

    class OtherWindow:
        def choose_folder(self):
            return str(tmp_path)

        def run(self, url):
            self.url = url
            state = httpx2.get(url + PREFIX + "/app/state").json()
            assert state["managed"] and state["active"] is None
            response = httpx2.post(url + PREFIX + "/app/pick-folder", headers={"X-Carma-Token": state["token"]})
            assert response.json()["path"] == str(tmp_path)

        def show_error(self, message):
            pytest.fail(message)

    window = OtherWindow()
    assert main(window) == 0
    with pytest.raises(httpx2.TransportError):
        httpx2.get(window.url + PREFIX + "/app/state", timeout=1)
