"""The View API on the reference project: what each answer says, the SSE stream and the served UI."""

import threading
import time

import httpx2
import pytest
import uvicorn
from fastapi.testclient import TestClient

from carma.api.app import PREFIX, create_app

DRAW_SCENE = "cxx golden/render/Renderer#DrawScene()."
UPLOAD = "cxx golden/render/GpuUploader#Upload(const std::string&)."
RENDERER = "cxx golden/render/Renderer#"


@pytest.fixture
def client(golden_core):
    with TestClient(create_app(golden_core, ui_dir=None)) as c:
        yield c


def get(client, path, **params):
    response = client.get(PREFIX + path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_symbol_card(client, golden_project):
    card = get(client, "/symbols", id=DRAW_SCENE)
    assert card["component"] == "render" and card["place"] == {"scope": "render._self", "node": RENDERER}
    assert card["defs"] == [{"path": "src/render/Renderer.cpp", "line": 15, "column": 16, "end_line": 35}]
    absolute = (golden_project.resolve() / "src/render/Renderer.cpp").as_posix()
    assert card["editor_uri"] == f"vscode://file/{absolute.lstrip('/')}:15"  # one '/' after file on every OS
    assert get(client, "/symbols", id="cxx std/")["place"] is None  # namespaces and externals are not drawn


def test_search_and_calls(client):
    found = get(client, "/symbols/search", q="Renderer", kind=["class"])
    assert [s["id"] for s in found["items"]] == [RENDERER]
    assert found["items"][0] | {"line": None} == {"id": RENDERER, "name": "Renderer", "kind": "class", "signature": None,
                                                  "component": "render", "path": "src/render/Renderer.h", "line": None,
                                                  "external": False}
    assert get(client, "/symbols/search", q="e", limit=2)["more"]
    callers = get(client, "/symbols/callers", id=UPLOAD, depth=2)["items"]
    assert {(c["caller_name"], c["depth"]) for c in callers} == {("OnLoaded", 1), ("RequestLoad", 2)}
    first = next(c for c in callers if c["depth"] == 1)
    assert (first["path"], first["line"]) == ("src/streaming/TextureStreamer.cpp", 26)


def test_edge_samples_on_both_kinds_of_levels(client):
    root = get(client, "/edges/samples", src="streaming", dst="render")
    assert [(r["symbol"], r["roles"], r["line"]) for r in root["items"]] == [
        ("cxx golden/render/GpuUploader#", ["reference"], 26), (UPLOAD, ["call"], 26)]
    leaf = get(client, "/edges/samples", scope="render._self", src=RENDERER, dst="streaming", limit=3)
    assert len(leaf["items"]) == 3 and leaf["more"]
    assert get(client, "/edges/samples", src="io", dst="render")["items"] == []


def test_component_tree_and_card(client):
    tree = get(client, "/components")
    assert [c["id"] for c in tree["components"]] == ["apps", "core", "io", "render", "streaming"]
    assert tree["components"][3]["children"][0]["id"] == "render.backend" and tree["unassigned"] == 0
    assert [c["id"] for c in get(client, "/components", parent="render")["components"]] == ["render.backend"]

    card = get(client, "/components/render")
    assert (card["parent"], card["children"], card["symbols"], card["own_symbols"]) == ("root", ["render.backend"], 24, 14)
    assert [(e["node"], e["refs"], e["declared"]) for e in card["edges_out"]] == [("core", 7, True), ("streaming", 4, True)]
    assert [(e["node"], e["declared"]) for e in card["edges_in"]] == [("apps", False), ("streaming", False)]
    assert len(card["fingerprint"]) == 16 and card["model"]["requires"][0]["component"] == "streaming"
    assert {s["id"] for s in card["interface"]} >= {DRAW_SCENE, RENDERER} and all(s["present"] for s in card["interface"])

    streaming = get(client, "/components/streaming")
    assert [i["code"] for i in streaming["issues"]] == ["undeclared_dependency"]
    assert streaming["issues"][0]["text"] == "streaming -> render: not in requires (2 refs)"
    assert client.get(f"{PREFIX}/components/nope").status_code == 404


def test_layout_pins_and_unpins(client):
    body = {"positions": {"render": {"x": 120, "y": 80}}}
    assert client.put(f"{PREFIX}/layout/root", json=body).status_code == 200
    nodes = {n["id"]: n["pos"] for n in get(client, "/view", scope="root")["nodes"]}
    assert nodes["render"] == {"x": 120.0, "y": 80.0} and nodes["io"] is None
    client.put(f"{PREFIX}/layout/root", json={"positions": {}})
    assert all(n["pos"] is None for n in get(client, "/view", scope="root")["nodes"])
    assert client.put(f"{PREFIX}/layout/nope", json=body).status_code == 404
    bad = client.put(f"{PREFIX}/layout/root", json={"positions": {"render": {"x": "left"}}})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation_failed"


def test_trail(client):
    trail = get(client, "/view", scope="render._self")["trail"]
    assert trail == [{"scope": "root", "name": "root"}, {"scope": "render", "name": "Render"},
                     {"scope": "render._self", "name": "Render"}]


def test_the_built_ui_is_served(golden_core, tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>map</title>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    with TestClient(create_app(golden_core, ui_dir=tmp_path)) as c:
        assert "<title>map</title>" in c.get("/").text
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert c.get(f"{PREFIX}/status").json()["components"] == 6
    with TestClient(create_app(golden_core, ui_dir=tmp_path / "missing")) as c:
        assert "not built" in c.get("/").text


def test_events_stream_model_changes(golden_core, free_port):
    port = free_port
    server = uvicorn.Server(uvicorn.Config(create_app(golden_core, ui_dir=None, keepalive=0.2), host="127.0.0.1",
                                           port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        with httpx2.Client(timeout=10) as http, http.stream("GET", f"http://127.0.0.1:{port}{PREFIX}/events") as stream:
            assert stream.headers["content-type"].startswith("text/event-stream")
            golden_core.patch_component("io", {"intent": "Reads files."})
            lines = []
            for line in stream.iter_lines():
                lines.append(line)
                if line.startswith("data:"):
                    break
        assert "event: model_changed" in lines and 'data: {"event": "model_changed"}' in lines
    finally:
        server.should_exit = True
        thread.join(timeout=10)
