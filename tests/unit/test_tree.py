"""The component hierarchy and the node a component shows up as on each level."""

from carma.engine.tree import ROOT, ComponentTree

TREE = ComponentTree(["render", "render.backend", "render.backend.gl", "streaming", "gameplay.inventory"])


def test_parent_is_the_closest_existing_component():
    assert TREE.parent["render.backend.gl"] == "render.backend"
    assert TREE.parent["gameplay.inventory"] == ROOT  # there is no gameplay.yaml
    assert TREE.children[ROOT] == ["gameplay.inventory", "render", "streaming"]
    assert TREE.levels() == [ROOT, "render", "render.backend"]
    assert TREE.subtree("render") == ["render", "render.backend", "render.backend.gl"]


def test_node_inside_the_level():
    assert TREE.node_at(ROOT, "render.backend.gl") == ("render", False)
    assert TREE.node_at("render", "render.backend.gl") == ("render.backend", False)
    assert TREE.node_at("render", "render") == ("render._self", False)
    assert TREE.node_at(ROOT, "_unassigned") == ("_unassigned", False)


def test_boundary_nodes():
    assert TREE.node_at("render", "streaming") == ("streaming", True)  # a neighbor of the open component
    assert TREE.node_at("render.backend", "streaming") == ("streaming", True)  # a neighbor of its ancestor
    assert TREE.node_at("render.backend.gl", "render") == ("render._self", True)  # an ancestor's own symbols
    assert TREE.node_at("render.backend", "_unassigned") == ("_unassigned", True)
    assert TREE.node_at("render", "_external") is None


def test_ancestry():
    assert TREE.is_ancestor(ROOT, "render") and TREE.is_ancestor("render", "render.backend.gl")
    assert not TREE.is_ancestor("render", "render") and not TREE.is_ancestor("render.backend", "render")
    assert TREE.within("render", "render") and TREE.within("render.backend", "render")
