"""Reading and writing component files: validation, round-trip merges, atomic replace, layout.json."""

import shutil

import pytest

from carma.model.layout import load_layout, save_layout
from carma.model.repo import (
    ComponentExistsError,
    ModelRepo,
    ModelValidationError,
    UnknownComponentError,
    merge_patch,
)


@pytest.fixture
def repo(tmp_path, samples_dir):
    folder = tmp_path / "model"
    shutil.copytree(samples_dir / "model", folder)
    return ModelRepo(folder)


INVENTORY = "gameplay.inventory"


def test_load_reports_bad_files_and_keeps_the_rest(repo):
    (repo.folder / "broken.yaml").write_text("id: [unclosed\n", encoding="utf-8")
    (repo.folder / "renamed.yaml").write_text("schema_version: model/0.1\nid: other\nname: X\nmembers: []\n", encoding="utf-8")
    (repo.folder / "empty.yaml").write_text("", encoding="utf-8")
    snapshot = repo.load()
    assert sorted(snapshot.components) == ["gameplay.crafting", INVENTORY]
    assert sorted(snapshot.invalid) == ["broken.yaml", "empty.yaml", "renamed.yaml"]
    assert "does not match the file name" in snapshot.invalid["renamed.yaml"][0]
    inventory = snapshot.components[INVENTORY]
    assert inventory.requires == ("gameplay.items",) and inventory.declares_requires
    assert inventory.anchors == ("cxx game/InventoryDebugHud#", "cxx game/IInventory#")
    assert inventory.kind == "component" and snapshot.components["gameplay.crafting"].lifecycle == "planned"


def test_digest_changes_only_with_content(repo):
    before = repo.load().digest
    assert repo.load().digest == before
    repo.patch(INVENTORY, {"name": "Bag"})
    assert repo.load().digest != before


def test_write_keeps_comments_order_and_styles(repo):
    path = repo.path_of(INVENTORY)
    original = path.read_text(encoding="utf-8")
    data = repo.read(INVENTORY)
    assert repo.write(data) == data
    assert path.read_text(encoding="utf-8") == original  # an unchanged write changes no byte

    data["intent"] = "Keeps the character's items.\n"
    data["notes"].append({"text": "Weight limit comes from the save file", "source": "human", "date": "2026-09-30"})
    data["runtime"]["thread"] = "main"
    repo.write(data)
    text = path.read_text(encoding="utf-8")
    expected = (original.replace("  Хранит предметы персонажа, валидирует операции на сервере,\n"
                                 "  реплицирует состояние владельцу.\n", "  Keeps the character's items.\n")
                .replace("thread: game", "thread: main")
                .replace("{ path: src/gameplay/inventory/tests/** }", "{path: src/gameplay/inventory/tests/**}")
                .replace("    date: 2026-09-29\n\nsync:", "    date: 2026-09-29\n  - text: Weight limit comes from the save file\n"
                         "    source: human\n    date: 2026-09-30\n\nsync:"))
    # ruamel drops the padding inside { }, as in the contract round-trip test; the rest is untouched
    assert text == expected
    assert repo.read(INVENTORY) == data

    del data["members"][-1], data["notes"][0]
    repo.write(data)
    text = path.read_text(encoding="utf-8")
    assert "exclude" not in text and "  - symbol: \"cxx game/InventoryDebugHud#\"\n\nprovides:" in text
    assert "notes:\n  - text: Weight limit comes from the save file\n" in text and "date: 2026-09-30\n\nsync:" in text


def test_removing_and_adding_keys(repo):
    data = repo.read(INVENTORY)
    del data["runtime"], data["invariants"]
    data["lifecycle"] = "deprecated"
    repo.write(data)
    text = repo.path_of(INVENTORY).read_text(encoding="utf-8")
    assert "runtime" not in text and "invariants" not in text
    assert "lifecycle: deprecated      # current | planned | deprecated" in text  # the comment keeps its column
    data["invariants"] = ["Stacks never exceed MaxStack"]
    repo.write(data)
    text = repo.path_of(INVENTORY).read_text(encoding="utf-8")
    assert text.index("requires:") < text.index("invariants:") < text.index("manual:")  # back in the schema order


def test_new_file_uses_the_schema_key_order(repo):
    written = repo.create({"members": [{"path": "src/ui/**"}], "name": "UI", "id": "ui", "schema_version": "model/0.1",
                           "intent": "Menus\nand HUD\n"})
    text = repo.path_of("ui").read_text(encoding="utf-8")
    assert text == "schema_version: model/0.1\nid: ui\nname: UI\nintent: |\n  Menus\n  and HUD\nmembers:\n  - path: src/ui/**\n"
    assert written["intent"] == "Menus\nand HUD\n"
    with pytest.raises(ComponentExistsError):
        repo.create(written)


def test_invalid_data_is_rejected_and_nothing_is_written(repo):
    path = repo.path_of(INVENTORY)
    before = path.read_bytes()
    data = repo.read(INVENTORY)
    data["lifecycle"] = "draft"
    with pytest.raises(ModelValidationError) as info:
        repo.write(data)
    assert info.value.errors and path.read_bytes() == before
    assert not list(repo.folder.glob(".*.tmp"))


def test_a_broken_file_is_replaced_by_a_whole_write(repo):
    path = repo.path_of(INVENTORY)
    path.write_text("id: [unclosed\n", encoding="utf-8")
    with pytest.raises(ModelValidationError):
        repo.patch(INVENTORY, {"name": "Bag"})
    repo.write({"schema_version": "model/0.1", "id": INVENTORY, "name": "Bag", "members": []})
    assert repo.read(INVENTORY)["name"] == "Bag"


def test_merge_patch():
    assert merge_patch({"a": 1, "b": {"c": 2, "d": 3}}, {"a": None, "b": {"c": 5}, "e": [1]}) == {"b": {"c": 5, "d": 3}, "e": [1]}
    assert merge_patch({"a": 1}, [1, 2]) == [1, 2]


def test_patch_delete_and_unknown_ids(repo):
    written = repo.patch(INVENTORY, {"intent": "Items.", "runtime": None})
    assert written["intent"] == "Items." and "runtime" not in written
    with pytest.raises(ModelValidationError):
        repo.patch(INVENTORY, {"id": "gameplay.bag"})
    repo.delete("gameplay.crafting")
    assert "gameplay.crafting" not in repo.load().components
    with pytest.raises(UnknownComponentError):
        repo.delete("gameplay.crafting")
    with pytest.raises(UnknownComponentError):
        repo.patch("nope", {"name": "x"})


def test_crlf_files_stay_crlf(repo):
    path = repo.path_of(INVENTORY)
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    repo.patch(INVENTORY, {"name": "Bag"})
    raw = path.read_bytes()
    assert b"name: Bag\r\n" in raw and raw.count(b"\n") == raw.count(b"\r\n")


def test_layout(tmp_path):
    assert load_layout(tmp_path) == {}
    save_layout(tmp_path, "root", {"render": {"x": 120, "y": 80}})
    save_layout(tmp_path, "render", {"render._self": {"x": 1.5, "y": -2}})
    assert load_layout(tmp_path) == {"root": {"render": {"x": 120, "y": 80}}, "render": {"render._self": {"x": 1.5, "y": -2}}}
    save_layout(tmp_path, "render", {})
    assert list(load_layout(tmp_path)) == ["root"]
    with pytest.raises(ModelValidationError):
        save_layout(tmp_path, "root", {"render": {"x": "120"}})
