"""Source suggestions preserve complete scopes and personal knowledge survives migration."""

from carma.execution.api import ExecutionFunction
from carma.indexers.libclang.execution import analyze
from carma.model.exploration import load_exploration, save_exploration
from carma.model.json_io import write_json


def test_comment_groups_preserve_returns_and_line_independent_anchors(tmp_path, libclang_path):
    source = tmp_path / "flow.cpp"
    code = '''void Hint(int) {}
int main() {
    // Window settings
    Hint(1); Hint(2); Hint(3);
    // Application initialization
    if (true) { Hint(4); return -1; }
    Hint(5);
    return 0;
}
'''
    source.write_text(code, encoding="utf-8")
    def read():
        return ExecutionFunction.model_validate(analyze(str(source), [], str(libclang_path), str(tmp_path), ())["functions"]["cxx main()."])
    original = read()
    settings = next(g for g in original.groups if g.label == "Window settings")
    assert len(settings.members) == 3
    app = next(g for g in original.groups if g.label == "Application initialization")
    returned = next(n for n in original.nodes if n.code == "return -1")
    assert returned.id in app.members
    assert any(e.source == returned.id and e.target == original.exit for e in original.edges)
    assert all(g.members and len(set(g.members)) == len(g.members) for g in original.groups)
    source.write_text("\n\n" + code, encoding="utf-8")
    shifted = read()
    assert [n.anchor for n in original.nodes] == [n.anchor for n in shifted.nodes]
    assert [g.id for g in original.groups] == [g.id for g in shifted.groups]
    assert original.nodes[0].id != shifted.nodes[0].id


def test_migrate_previous_exploration_without_losing_layout(tmp_path):
    old = {"schema_version": "exploration/0.1", "mode": "execution", "entry": "main", "views": {
        "main@main.cpp": {"expanded": {"root/call@0": "init"}, "positions": {"root/call": {"x": 22, "y": 33}}, "camera": {"x": 0, "y": 0, "zoom": 1}}}}
    write_json(tmp_path / "exploration.json", old)
    new = load_exploration(tmp_path)
    assert new["schema_version"] == "exploration/0.2"
    assert new["views"] == old["views"]
    new["studies"] = {"init@main.cpp": {"groups": [{"id": "custom:glfw", "title": "GLFW Init", "members": ["a", "b"]}],
        "annotations": {"custom:glfw": {"status": "understood", "note": "Sets up the context", "color": "#438a60"}}}}
    assert save_exploration(tmp_path, new) == load_exploration(tmp_path)
