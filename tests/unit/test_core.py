"""The recompute pipeline of the core: model writes, hand edits, events, statuses and layout."""

import threading

from carma.engine.checks import fingerprint, interface


def codes(core):
    return [(i.code, i.component or i.target) for i in core.issues() if i.code not in ("undeclared_dependency", "cycle")]


def test_writes_recompute_and_notify(golden_core):
    events = []
    golden_core.subscribe(events.append)
    assert not golden_core.reload_model()  # nothing changed on disk
    golden_core.create_component({"schema_version": "model/0.1", "id": "io.queue", "name": "Queue",
                                  "members": [{"path": "src/io/IoQueue.*"}]})
    assert golden_core.state.membership.component_of["cxx golden/io/IoQueue#"] == "io.queue"
    assert [n.id for n in golden_core.view("io").nodes] == ["io.queue", "io._self"]
    golden_core.delete_component("io.queue")
    assert "io.queue" not in golden_core.state.model.components
    assert events == ["model_changed", "model_changed"]


def test_statuses(golden_core):
    golden_core.patch_component("core", {"members": [{"path": "src/nowhere/**"}, {"symbol": "cxx golden/Gone#"}]})
    golden_core.create_component({"schema_version": "model/0.1", "id": "planned", "name": "Planned", "lifecycle": "planned"})
    assert codes(golden_core) == [("broken_anchor", "core"), ("empty", "core"),
                                  ("missing_dependency", "render"), ("missing_dependency", "streaming")]
    view = golden_core.view("root")
    assert next(n for n in view.nodes if n.id == "core").issues == ("broken_anchor", "empty")
    assert next(n for n in view.nodes if n.id == "render").issues == ("missing_dependency",)
    assert next(n for n in view.nodes if n.id == "planned").lifecycle == "planned"


def test_stale_annotation(golden_core):
    state = golden_core.state
    current = fingerprint(interface(state.model.components["io"], state.tree, state.membership, state.symbols))
    golden_core.patch_component("io", {"sync": {"fingerprint": current[:16], "annotated_at": "2026-09-30"}})
    assert codes(golden_core) == []
    golden_core.patch_component("io", {"sync": {"fingerprint": "0123abcd"}})
    assert codes(golden_core) == [("stale", "io")]
    # a neighbour's model edit does not touch the fingerprint of io
    golden_core.patch_component("io", {"sync": {"fingerprint": current[:8]}})
    golden_core.patch_component("streaming", {"intent": "Streams."})
    assert codes(golden_core) == []


def test_invalid_file_is_an_issue_and_left_out(golden_core):
    path = golden_core.repo.path_of("apps")
    path.write_text(path.read_text(encoding="utf-8").replace("kind: subsystem", "kind: galaxy"), encoding="utf-8")
    assert golden_core.reload_model()
    assert codes(golden_core) == [("invalid_model", "apps.yaml")]
    assert "apps" not in golden_core.state.model.components
    assert golden_core.state.membership.component_of["cxx main()."] == "_unassigned"


def test_layout_positions_reach_the_view(golden_core):
    golden_core.save_layout("root", {"render": {"x": 120, "y": 80}})
    nodes = {n.id: n.pos for n in golden_core.view("root").nodes}
    assert nodes["render"] == (120, 80) and nodes["io"] is None
    assert (golden_core.config.carma_dir / "layout.json").is_file()


def test_hand_edits_are_picked_up_by_the_watcher(golden_core):
    changed = threading.Event()
    golden_core.subscribe(lambda event: changed.set())
    golden_core.watch_model()
    path = golden_core.repo.path_of("streaming")
    path.write_text(path.read_text(encoding="utf-8") + "  - component: render\n", encoding="utf-8")
    assert changed.wait(timeout=15), "no model_changed event after a hand edit"
    assert [i.code for i in golden_core.issues()] == ["cycle"]
