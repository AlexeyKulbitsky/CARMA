"""Contract 3: component files, config and layout match their schemas; YAML round-trips."""

import copy
import re

import pytest

from carma.contracts import validation_errors
from carma.model import yaml_io


def load_plain(path):
    return yaml_io.to_plain(yaml_io.load(path))


@pytest.fixture(scope="module")
def inventory(samples_dir):
    return load_plain(samples_dir / "model" / "gameplay.inventory.yaml")


def model_files(samples_dir, golden_dir):
    return sorted((samples_dir / "model").glob("*.yaml")) + sorted((golden_dir / "expected" / "model").glob("*.yaml"))


def test_valid_components(samples_dir, golden_dir):
    files = model_files(samples_dir, golden_dir)
    assert files
    for path in files:
        data = load_plain(path)
        assert validation_errors("model", data) == [], path.name
        assert data["id"] == path.stem, f"{path.name}: id must match the file name"


def test_planned_component_needs_no_members(samples_dir):
    data = load_plain(samples_dir / "model" / "gameplay.crafting.yaml")
    assert data["lifecycle"] == "planned" and "members" not in data
    assert validation_errors("model", data) == []


INVALID = [
    ("reserved underscore id", lambda d: d.update(id="_hidden")),
    ("reserved underscore segment", lambda d: d.update(id="render._self")),
    ("reserved root id", lambda d: d.update(id="root")),
    ("uppercase id", lambda d: d.update(id="Gameplay.inventory")),
    ("unknown key", lambda d: d.update(owner="alex")),
    ("current without members", lambda d: d.pop("members")),
    ("unknown lifecycle", lambda d: d.update(lifecycle="draft")),
    ("unknown intent source", lambda d: d.update(intent_source="bot")),
    ("absolute path rule", lambda d: d.update(members=[{"path": "C:/src/**"}])),
    ("broken namespace rule", lambda d: d.update(members=[{"namespace": "game::"}])),
    ("symbol without scheme", lambda d: d.update(members=[{"symbol": "game/Foo#"}])),
    ("two rules in one item", lambda d: d.update(members=[{"path": "src/**", "namespace": "game"}])),
    ("requires reserved component", lambda d: d.update(requires=[{"component": "_external"}])),
    ("note from unknown source", lambda d: d["notes"][0].update(source="llm")),
    ("non-scalar runtime value", lambda d: d["runtime"].update(thread=["game", "render"])),
]


@pytest.mark.parametrize("mutate", [c[1] for c in INVALID], ids=[c[0] for c in INVALID])
def test_invalid_component(inventory, mutate):
    data = copy.deepcopy(inventory)
    mutate(data)
    assert validation_errors("model", data)


def test_round_trip_keeps_comments_and_key_order(samples_dir):
    # Byte-for-byte except padding inside flow mappings: ruamel writes `{ a: b }` as `{a: b}`.
    unpad = lambda text: re.sub(r"\{\s+", "{", re.sub(r"\s+\}", "}", text))  # noqa: E731
    path = samples_dir / "model" / "gameplay.inventory.yaml"
    original = path.read_text(encoding="utf-8")
    assert unpad(yaml_io.dumps(yaml_io.loads(original))) == unpad(original)


# ---------------------------------------------------------------- config.yaml


@pytest.fixture(scope="module")
def gd_engine_config(samples_dir):
    return load_plain(samples_dir / "config_gd_engine.yaml")


def test_valid_configs(gd_engine_config, golden_dir):
    assert validation_errors("config", gd_engine_config) == []
    assert validation_errors("config", load_plain(golden_dir / "expected" / "config.yaml")) == []


def test_compile_commands_source_is_valid(gd_engine_config):
    data = copy.deepcopy(gd_engine_config)
    data["compile_db"] = {"compile_commands": "build/compile_commands.json"}
    assert validation_errors("config", data) == []


INVALID_CONFIG = [
    ("both compile_db sources", lambda d: d["compile_db"].update(compile_commands="build/compile_commands.json")),
    ("no compile_db", lambda d: d.pop("compile_db")),
    ("absolute source root", lambda d: d.update(source_roots=["C:/gd-engine/source"])),
    ("editor uri without path", lambda d: d.update(editor_uri="vscode://file/")),
    ("unknown indexer", lambda d: d["indexer"].update(name="scip-clang")),
    ("unknown key", lambda d: d.update(index_everything=True)),
]


@pytest.mark.parametrize("mutate", [c[1] for c in INVALID_CONFIG], ids=[c[0] for c in INVALID_CONFIG])
def test_invalid_config(gd_engine_config, mutate):
    data = copy.deepcopy(gd_engine_config)
    mutate(data)
    assert validation_errors("config", data)


# ---------------------------------------------------------------- layout.json


def test_layout():
    valid = {"layout_version": "0.1", "views": {"root": {"gameplay": {"x": 120, "y": 80}}}}
    assert validation_errors("layout", valid) == []
    missing_y = {"layout_version": "0.1", "views": {"root": {"gameplay": {"x": 120}}}}
    assert validation_errors("layout", missing_y)
    string_x = {"layout_version": "0.1", "views": {"root": {"gameplay": {"x": "120", "y": 80}}}}
    assert validation_errors("layout", string_x)
