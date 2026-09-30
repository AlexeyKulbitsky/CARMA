"""The model skeleton `carma init` writes from the folders of indexed files (spec «Скелет»)."""

from carma.contracts import validation_errors
from carma.engine.skeleton import build_skeleton, slugify

IGNORE = ("**/thirdparty/**", "build/**")

GD_ENGINE = [
    "build/engine_build/config.h",
    "engine/source/Application.cpp", "engine/source/Engine.cpp", "engine/source/eng.h",
    "engine/source/physics/PhysicsWorld.cpp", "engine/source/physics/detail/Contact.h",
    "engine/source/render/Renderer.cpp",
    "engine/source/scene/Scene.cpp", "engine/source/scene/components/MeshComponent.cpp",
    "engine/thirdparty/JoltPhysics/Jolt.h",
    "source/Game.cpp", "source/main.cpp",
]


def skeleton(files, roots, depth=2, name="gd-engine"):
    return {c.id: c for c in build_skeleton(files, roots, IGNORE, depth, name)}


def test_gd_engine_layout():
    result = skeleton(GD_ENGINE, ["engine/source", "source"])
    assert sorted(result) == ["engine-source", "physics", "physics.detail", "render", "scene", "scene.components", "source"]
    assert (result["engine-source"].path, result["engine-source"].files, result["engine-source"].name) == \
        ("engine/source/*", 3, "engine/source")
    assert (result["physics"].kind, result["physics"].path, result["physics"].files) == ("subsystem", "engine/source/physics/**", 2)
    assert (result["scene.components"].kind, result["scene.components"].name) == ("component", "Components")
    assert result["source"].path == "source/*"
    for component in result.values():
        assert validation_errors("model", component.data()) == [], component.id


def test_depth_limits_the_skeleton_but_not_the_rules():
    result = skeleton(GD_ENGINE, ["engine/source"], depth=1)
    assert "scene.components" not in result and result["scene"].path == "engine/source/scene/**"


def test_without_source_roots_the_project_root_is_the_root():
    result = skeleton(["CMakeLists.cpp", "engine/source/Engine.cpp", "source/Game.cpp"], [], depth=1)
    assert sorted(result) == ["engine", "gd-engine", "source"]
    assert result["gd-engine"].path == "*"


def test_slug_collisions():
    files = ["a/render/x.cpp", "b/render/y.cpp", "a/Render/z.cpp", "c/root/r.cpp", "c/My Folder!/q.cpp"]
    result = skeleton(files, ["a", "b", "c"], depth=1)
    assert sorted(result) == ["a-render", "a-render-2", "b-render", "my-folder", "root-2"]
    assert result["a-render-2"].path == "a/render/**" and result["a-render"].path == "a/Render/**"
    assert slugify("_Private.Dir") == "private-dir" and slugify("a  b--") == "a-b"
