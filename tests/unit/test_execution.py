"""Execution flow preserves control semantics and carries types only through inspected assignments."""

import os
from pathlib import Path

import pytest

from carma.execution.api import ExecutionFunction
from carma.indexers.libclang.execution import analyze


CODE = """\
struct App { virtual bool Init() { return true; } };
struct Game : App { bool Init() override { return false; } };
struct Engine {
    App* app;
    void SetApplication(App* value) { app = value; }
    bool Init() { return app->Init(); }
};
void Tick() {}
int main() {
    Engine engine;
    auto* game = new Game();
    engine.SetApplication(game);
    if (!engine.Init()) { return -1; }
    while (true) {
        Tick();
        if (false) { continue; }
        Tick();
        break;
    }
    auto callback = [] { Tick(); };
    return 0;
}
"""


@pytest.fixture
def flow_project(tmp_path, libclang_path):
    path = tmp_path / "main.cpp"
    path.write_text(CODE, encoding="utf-8")
    result = analyze(str(path), ["-std=c++17"], str(libclang_path), str(tmp_path), ())
    return {sid: ExecutionFunction.model_validate(flow) for sid, flow in result["functions"].items()}


def test_order_branches_loops_and_deferred_lambda(flow_project):
    main = flow_project["cxx main()."]
    assert [o.name for o in main.objects] == ["engine", "game"]
    calls = [c for n in main.nodes for c in n.calls if c.name == "Tick"]
    assert len(calls) == 2  # the callback's body does not run during registration
    assert len([n for n in main.nodes if n.kind == "branch"]) == 2
    assert len([n for n in main.nodes if n.kind == "loop"]) == 1
    returns = [n for n in main.nodes if n.kind == "return"]
    assert len(returns) == 2
    assert all(any(e.source == n.id and e.target == main.exit for e in main.edges) for n in returns)
    assert any(e.label == "continue" for e in main.edges)
    assert any(e.label == "break" for e in main.edges)
    assert any("runs later" in n.note for n in main.nodes)


def test_setter_summary_uses_actual_assignment(flow_project):
    setter = flow_project["cxx Engine#SetApplication(App*)."]
    effects = [e for n in setter.nodes for e in n.effects]
    assert any(e.target == "cxx Engine#app." and e.value == "value" for e in effects)
    init = flow_project["cxx Engine#Init()."]
    call = next(c for n in init.nodes for c in n.calls)
    assert call.virtual and call.receiver == "cxx Engine#app."


def test_nested_else_is_not_an_else_of_the_outer_if(tmp_path, libclang_path):
    source = tmp_path / "nested.cpp"
    source.write_text('int main() { if (true) { if (false) return 1; else return 2; } return 0; }', encoding="utf-8")
    flow = ExecutionFunction.model_validate(analyze(str(source), [], str(libclang_path), str(tmp_path), ())["functions"]["cxx main()."])
    assert len([n for n in flow.nodes if n.label == "Else"]) == 1
    assert len([n for n in flow.nodes if n.kind == "return"]) == 3


@pytest.fixture
def execution_core(tmp_path, libclang_path, flow_project):
    from carma.compiledb.model import CompileCommand
    from carma.config import Config
    from carma.engine.core import Core
    from carma.indexers.libclang.indexer import index_project
    from carma.store.loader import load_facts
    from carma.store.sqlite import SQLiteStore

    previous = Path.cwd()
    try:
        source = tmp_path / "main.cpp"
        facts = tmp_path / "facts.jsonl"
        index_project(tmp_path, [CompileCommand(tmp_path, source, ("clang++", "-std=c++17", str(source)))],
                      facts, libclang=libclang_path, jobs=1)
        with SQLiteStore(tmp_path / "facts.db") as store:
            load_facts(store, facts)
            core = Core(Config(tmp_path), store)
            core.load()
            yield core
            core.close()
    finally:
        os.chdir(previous)


class MemoryProvider:
    def __init__(self, functions):
        self.functions = functions

    def function(self, symbol, path, line):
        from carma.execution.api import ExecutionUnavailable
        if symbol not in self.functions:
            raise ExecutionUnavailable("No source body")
        return self.functions[symbol]


def test_contextual_dispatch_and_unknown_receiver(execution_core, flow_project):
    from carma.engine.execution import execution_view
    provider = MemoryProvider(flow_project)
    main = execution_view(execution_core, provider, "cxx main().", {})
    init_call = next(c for n in main.nodes for c in n.calls if c.name == "Init")
    init = execution_view(execution_core, provider, init_call.symbol, init_call.bindings)
    virtual = next(c for n in init.nodes for c in n.calls)
    assert virtual.candidates == ["cxx Game#Init()."]
    assert virtual.resolution == "inferred" and virtual.symbol == "cxx App#Init()."
    standalone = execution_view(execution_core, provider, init_call.symbol, {})
    unresolved = next(c for n in standalone.nodes for c in n.calls)
    assert unresolved.resolution == "virtual"
    assert set(unresolved.candidates) == {"cxx App#Init().", "cxx Game#Init()."}
    assert not next(c for n in flow_project[init_call.symbol].nodes for c in n.calls).candidates  # provider data stays immutable


def test_execution_api_contract_and_saved_exploration(execution_core, flow_project):
    from fastapi.testclient import TestClient
    from carma.api.app import PREFIX, create_app
    from carma.contracts import validation_errors
    provider = MemoryProvider(flow_project)
    with TestClient(create_app(execution_core, ui_dir=None, execution_factory=lambda config: provider)) as client:
        response = client.post(PREFIX + "/execution/view", json={"symbol": "cxx main()."})
        assert response.status_code == 200
        assert validation_errors("execution", response.json()) == []
        assert client.get(PREFIX + "/execution/entrypoints").json()["items"][0]["id"] == "cxx main()."
        entity = client.get(PREFIX + "/execution/entity", params={"id": "cxx Game#"}).json()
        assert entity["bases"][0]["id"] == "cxx App#"
        assert any(m["name"] == "Init" for m in entity["members"])
        saved = client.get(PREFIX + "/exploration").json()
        saved.update(entry="cxx main().", views={"main": {"expanded": {"root/call@0": "cxx Engine#Init()."},
                     "positions": {"root/node": {"x": 12, "y": 30}}, "camera": {"x": 0, "y": 0, "zoom": .8}, "blocks": [], "detached": {}}})
        assert client.put(PREFIX + "/exploration", json=saved).status_code == 200
        from carma.api.schemas import Exploration
        assert client.get(PREFIX + "/exploration").json()["views"] == Exploration.model_validate(saved).model_dump()["views"]
        assert validation_errors("exploration", saved) == []
        assert client.put(PREFIX + "/exploration", json={**saved, "renderer": "ReactFlow"}).status_code == 422
        assert client.post(PREFIX + "/execution/view", json={"symbol": "cxx main().", "path": "../../outside.cpp"}).status_code == 422
        assert client.post(PREFIX + "/execution/view", json={"symbol": "cxx missing()."}).status_code == 404


def test_two_instances_keep_separate_receiver_types(execution_core, flow_project, tmp_path, libclang_path):
    from carma.engine.execution import execution_view
    source = tmp_path / "instances.cpp"
    source.write_text(CODE[:CODE.index('int main()')] + '''int main() {
        Engine first, second; Game game; App other;
        first.SetApplication(&game); second.SetApplication(&other);
        first.Init(); second.Init(); return 0;
    }''', encoding="utf-8")
    raw = analyze(str(source), [], str(libclang_path), str(tmp_path), ())
    functions = {sid: ExecutionFunction.model_validate(f) for sid, f in raw["functions"].items()}
    provider = MemoryProvider(functions)
    main = execution_view(execution_core, provider, "cxx main().", {})
    calls = [c for n in main.nodes for c in n.calls if c.name == "Init"]
    targets = []
    for call in calls:
        nested = execution_view(execution_core, provider, call.symbol, call.bindings)
        targets.append(next(c for n in nested.nodes for c in n.calls).candidates)
    assert targets == [["cxx Game#Init()."], ["cxx App#Init()."]]


def test_conditional_assignments_do_not_establish_a_single_type(execution_core, flow_project, tmp_path, libclang_path):
    from carma.engine.execution import execution_view
    source = tmp_path / "branches.cpp"
    source.write_text(CODE[:CODE.index('int main()')] + '''bool Choose(); int main() {
        Engine engine; Game game; App other;
        if (Choose()) engine.SetApplication(&game); else engine.SetApplication(&other);
        return engine.Init();
    }''', encoding="utf-8")
    raw = analyze(str(source), [], str(libclang_path), str(tmp_path), ())
    provider = MemoryProvider({sid: ExecutionFunction.model_validate(f) for sid, f in raw["functions"].items()})
    main = execution_view(execution_core, provider, "cxx main().", {})
    call = next(c for n in main.nodes for c in n.calls if c.name == "Init")
    nested = execution_view(execution_core, provider, call.symbol, call.bindings)
    virtual = next(c for n in nested.nodes for c in n.calls)
    assert virtual.resolution == "virtual" and len(virtual.candidates) == 2


def test_isolated_service_invalidates_on_source_change(tmp_path, libclang_path):
    import json
    from carma.application.execution import ExecutionService
    from carma.config import load_config, write_config
    source = tmp_path / "main.cpp"
    source.write_text("void Tick() {} int main() { Tick(); return 0; }", encoding="utf-8")
    commands = tmp_path / "compile_commands.json"
    commands.write_text(json.dumps([{"directory": str(tmp_path), "file": str(source),
                                   "arguments": ["clang++", "-std=c++17", str(source)]}]), encoding="utf-8")
    write_config(tmp_path, {"compile_commands": "compile_commands.json"}, [])
    service = ExecutionService(load_config(tmp_path))
    first = service.function("cxx main().", "main.cpp", 1)
    assert sum(c.name == "Tick" for n in first.nodes for c in n.calls) == 1
    source.write_text("void Tick() {} int main() { Tick(); Tick(); return 0; }", encoding="utf-8")
    second = service.function("cxx main().", "main.cpp", 1)
    assert sum(c.name == "Tick" for n in second.nodes for c in n.calls) == 2
