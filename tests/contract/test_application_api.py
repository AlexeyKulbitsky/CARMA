"""Application API and workspace contract are usable by clients other than React."""

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from carma.api.app import PREFIX, create_app
from carma.application.manager import ProjectManager
from carma.contracts import load_openapi, validation_errors


def test_application_state_matches_openapi(tmp_path):
    manager = ProjectManager(tmp_path / "settings")
    try:
        with TestClient(create_app(manager=manager, ui_dir=None)) as client:
            response = client.get(PREFIX + "/app/state")
            assert response.status_code == 200
            spec = load_openapi()
            schema = spec["paths"][PREFIX + "/app/state"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
            assert not list(Draft202012Validator({**schema, "components": spec["components"]}).iter_errors(response.json()))
    finally:
        manager.shutdown()


def test_workspace_contract_and_api_agree(golden_core):
    with TestClient(create_app(golden_core, ui_dir=None)) as client:
        data = client.get(PREFIX + "/workspace").json()
        assert validation_errors("workspace", data) == []
        assert client.put(PREFIX + "/workspace", json={**data, "renderer": "ReactFlow"}).status_code == 422
        assert validation_errors("workspace", {**data, "renderer": "ReactFlow"})
        cache = {"key": "abc123", "positions": {"render": {"x": 14, "y": 28}}}
        assert client.put(PREFIX + "/layout-cache/abc123", json=cache).status_code == 200
        assert client.get(PREFIX + "/layout-cache/abc123").json() == cache
        assert client.put(PREFIX + "/layout-cache/abc123", json={**cache, "key": "another"}).status_code == 422
