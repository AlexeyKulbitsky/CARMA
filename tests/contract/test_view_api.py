"""Contract 4: View API answers match contracts/openapi.yaml, and the root view matches expected/view_root.json."""

import json

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from carma.api.app import PREFIX, create_app, openapi_yaml
from carma.contracts import contracts_dir, load_openapi

DRAW_SCENE = "cxx golden/render/Renderer#DrawScene()."
UPLOAD = "cxx golden/render/GpuUploader#Upload(const std::string&)."


@pytest.fixture
def client(golden_core):
    with TestClient(create_app(golden_core, ui_dir=None)) as c:
        yield c


def test_openapi_file_matches_the_code():
    committed = (contracts_dir() / "openapi.yaml").read_text(encoding="utf-8")
    assert committed == openapi_yaml(), "contracts/openapi.yaml is stale: run uv run python scripts/gen_openapi.py"


def check(response, path: str, method: str = "get") -> dict:
    """Validate a response body against the schema openapi.yaml gives for its status code."""
    spec = load_openapi()
    responses = spec["paths"][PREFIX + path][method]["responses"]
    schema = responses[str(response.status_code)]["content"]["application/json"]["schema"]
    errors = [e.message for e in Draft202012Validator({**schema, "components": spec["components"]}).iter_errors(response.json())]
    assert errors == [], f"{method.upper()} {path} {response.status_code}: {errors[:3]}"
    return response.json()


READS = [
    ("/status", {}),
    ("/view", {"scope": "root"}),
    ("/view", {"scope": "render"}),
    ("/view", {"scope": "render._self"}),
    ("/view", {"scope": "io"}),
    ("/components", {}),
    ("/components", {"parent": "render"}),
    ("/symbols/search", {"q": "Draw"}),
    ("/symbols", {"id": DRAW_SCENE}),
    ("/symbols/callers", {"id": UPLOAD, "depth": 2}),
    ("/symbols/callees", {"id": DRAW_SCENE}),
    ("/paths", {"from": "cxx main().", "to": UPLOAD}),
    ("/edges/samples", {"src": "streaming", "dst": "render"}),
]


@pytest.mark.parametrize("path, params", READS, ids=[f"{p} {v}" for p, v in READS])
def test_reads_match_the_schema(client, path, params):
    response = client.get(PREFIX + path, params=params)
    assert response.status_code == 200, response.text
    check(response, path)


def test_component_card_matches_the_schema(client):
    check(client.get(f"{PREFIX}/components/render"), "/components/{component_id}")


def test_layout_matches_the_schema(client):
    response = client.put(f"{PREFIX}/layout/root", json={"positions": {"render": {"x": 1, "y": 2}}})
    assert check(response, "/layout/{scope}", "put") == {"scope": "root", "positions": {"render": {"x": 1.0, "y": 2.0}}}


@pytest.mark.parametrize("path, params, status", [
    ("/view", {"scope": "nope"}, 404),
    ("/symbols", {"id": "cxx no/Such#"}, 404),
    ("/symbols/callers", {"id": "cxx no/Such#"}, 404),
    ("/components", {"parent": "nope"}, 404),
    ("/symbols/search", {}, 422),
    ("/symbols/callers", {"id": UPLOAD, "depth": 0}, 422),
])
def test_errors_have_one_shape(client, path, params, status):
    response = client.get(PREFIX + path, params=params)
    assert response.status_code == status
    body = check(response, path)
    assert body["error"]["code"] == ("not_found" if status == 404 else "validation_failed")


def test_root_view_matches_the_expected_answer(client, golden_dir, golden_core):
    expected = json.loads((golden_dir / "expected" / "view_root.json").read_text(encoding="utf-8"))
    expected = {k: v for k, v in expected.items() if not k.startswith("$")}
    # symbols of a platform fork count only where the facts were indexed on that platform
    symbols = json.loads((golden_dir / "expected" / "symbols.json").read_text(encoding="utf-8"))["present"]
    tree = golden_core.state.tree
    for entry in symbols:
        if "platforms" in entry and entry["id"] in golden_core.state.symbols:
            top = tree.chain(entry["component"])[-1]
            next(n for n in expected["nodes"] if n["id"] == top)["symbols"] += 1
    actual = client.get(f"{PREFIX}/view", params={"scope": "root"}).json()
    for view in (expected, actual):
        for node in view["nodes"] + view["boundary"]:
            node.pop("pos")
    assert actual == expected


def test_symbol_view_includes_class_fields_and_methods(client):
    nodes = check(client.get(f"{PREFIX}/view", params={"scope": "render._self"}), "/view")["nodes"]
    renderer = next(node for node in nodes if node["name"] == "Renderer")
    assert len(renderer["members"]) == 7
    assert renderer["members"][0] == {
        "id": "cxx golden/render/Renderer#m_items.", "name": "m_items", "kind": "field",
        "signature": "std::vector<IRenderable *> m_items", "access": "private",
    }
    assert any(member["id"] == DRAW_SCENE and member["kind"] == "method" for member in renderer["members"])
    root = check(client.get(f"{PREFIX}/view", params={"scope": "root"}), "/view")
    assert all(node["members"] == [] for node in root["nodes"])
