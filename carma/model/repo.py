"""Contract 3: component files in .carma/model/, one per component.

Loading never fails on a bad file: it is reported and left out. Writing validates first, merges
the new data into the existing YAML tree so comments, key order and scalar styles a person added
survive, and replaces the file atomically.
"""

from __future__ import annotations

import datetime as dt
import difflib
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import CommentMark, YAMLError
from ruamel.yaml.scalarstring import LiteralScalarString, ScalarString
from ruamel.yaml.tokens import CommentToken

from carma.contracts import validation_errors
from carma.model import yaml_io
from carma.model.files import newline_of, write_atomic

SCHEMA_VERSION = "model/0.1"
# Key order of a new file and the place a new key takes in an existing one (spec «Файл компонента»).
KEY_ORDER = ("schema_version", "id", "name", "kind", "lifecycle", "intent", "intent_source", "members",
             "provides", "requires", "runtime", "invariants", "manual", "attach_points", "notes", "sync")
DATE_KEYS = frozenset({"date", "annotated_at"})
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ModelError(Exception):
    pass


class ModelValidationError(ModelError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


class ComponentExistsError(ModelError):
    pass


class UnknownComponentError(ModelError, KeyError):
    pass


@dataclass(frozen=True)
class Component:
    """A valid component file as plain JSON-compatible data, with the defaults the spec gives."""

    id: str
    data: dict = field(repr=False)

    @property
    def name(self) -> str:
        return self.data["name"]

    @property
    def kind(self) -> str:
        return self.data.get("kind", "component")

    @property
    def lifecycle(self) -> str:
        return self.data.get("lifecycle", "current")

    @property
    def intent(self) -> str:
        return self.data.get("intent", "")

    @property
    def members(self) -> list[dict]:
        return self.data.get("members", [])

    @property
    def declares_requires(self) -> bool:
        """Only components that declare `requires` are checked for undeclared dependencies."""
        return "requires" in self.data

    @property
    def requires(self) -> tuple[str, ...]:
        return tuple(r["component"] for r in self.data.get("requires", []))

    @property
    def symbol_rules(self) -> tuple[str, ...]:
        return tuple(rule["symbol"] for rule in self.members if "symbol" in rule)

    @property
    def provided_symbols(self) -> tuple[str, ...]:
        return tuple(s for p in self.data.get("provides", []) for s in p.get("symbols", []))

    @property
    def anchors(self) -> tuple[str, ...]:
        """Symbol IDs the model names explicitly: symbol rules (exclude included) and provides."""
        excluded = tuple(r["exclude"]["symbol"] for r in self.members if "symbol" in r.get("exclude", {}))
        return self.symbol_rules + excluded + self.provided_symbols

    @property
    def fingerprint(self) -> str | None:
        return self.data.get("sync", {}).get("fingerprint")


@dataclass(frozen=True)
class ModelSnapshot:
    components: dict[str, Component]
    invalid: dict[str, list[str]]  # file name -> errors; such files take no part in the recompute
    digest: str  # of every file's name and bytes: a reload that changes nothing is skipped


def validate_component(data: Any, file_id: str | None = None) -> list[str]:
    if not isinstance(data, dict):
        return ["<root>: a component file must be a mapping"]
    errors = validation_errors("model", data)
    if file_id is not None and data.get("id") != file_id:
        errors.append(f"id: '{data.get('id')}' does not match the file name '{file_id}.yaml'")
    return errors


def merge_patch(target: Any, patch: Any) -> Any:
    """JSON Merge Patch (RFC 7386): null removes a key, objects merge, anything else replaces."""
    if not isinstance(patch, Mapping):
        return patch
    result = dict(target) if isinstance(target, Mapping) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = merge_patch(result.get(key), value)
    return result


class ModelRepo:
    """The component files of one project; the only writer of .carma/model/."""

    def __init__(self, folder: Path):
        self.folder = folder

    def path_of(self, component_id: str) -> Path:
        return self.folder / f"{component_id}.yaml"

    def files(self) -> list[Path]:
        return sorted(self.folder.glob("*.yaml")) if self.folder.is_dir() else []

    def load(self) -> ModelSnapshot:
        components: dict[str, Component] = {}
        invalid: dict[str, list[str]] = {}
        digest = hashlib.sha256()
        for path in self.files():
            raw = path.read_bytes()
            digest.update(path.name.encode("utf-8") + b"\0" + raw + b"\0")
            try:
                data = yaml_io.to_plain(yaml_io.loads(raw.decode("utf-8")))
            except (YAMLError, UnicodeDecodeError) as exc:
                invalid[path.name] = [f"<root>: not valid YAML: {exc}".replace("\n", " ")]
                continue
            errors = validate_component(data, path.stem)
            if errors:
                invalid[path.name] = errors
            else:
                components[data["id"]] = Component(data["id"], data)
        return ModelSnapshot(components=components, invalid=invalid, digest=digest.hexdigest())

    def read(self, component_id: str) -> dict:
        path = self.path_of(component_id)
        if not path.is_file():
            raise UnknownComponentError(component_id)
        tree = _load_tree(path)
        if tree is None:
            raise ModelValidationError([f"{path.name}: not a valid component file"])
        return yaml_io.to_plain(tree)

    def create(self, data: dict) -> dict:
        if isinstance(data, dict) and self.path_of(str(data.get("id"))).exists():
            raise ComponentExistsError(f"component {data.get('id')} already exists")
        return self.write(data)

    def write(self, data: dict) -> dict:
        """Validate and write a whole component, keeping the comments of an existing file."""
        errors = validate_component(data)
        if errors:
            raise ModelValidationError(errors)
        path = self.path_of(data["id"])
        tree = _load_tree(path) if path.is_file() else None
        if tree is not None:
            if yaml_io.to_plain(tree) == data:
                return data  # nothing changed: leave the file as the person formatted it
            _merge_map(tree, data, KEY_ORDER)
        else:  # a new file, or one too broken to merge into
            tree = _node({key: data[key] for key in sorted(data, key=_key_rank)})
        write_atomic(path, yaml_io.dumps(tree), newline_of(path))
        return yaml_io.to_plain(tree)

    def patch(self, component_id: str, patch: dict) -> dict:
        data = merge_patch(self.read(component_id), patch)
        if isinstance(data, dict) and data.get("id") != component_id:
            raise ModelValidationError([f"id: a patch cannot rename {component_id}"])
        return self.write(data)

    def delete(self, component_id: str) -> None:
        path = self.path_of(component_id)
        if not path.is_file():
            raise UnknownComponentError(component_id)
        path.unlink()


# ---------------------------------------------------------------- round-trip merge


def _load_tree(path: Path) -> CommentedMap | None:
    try:
        tree = yaml_io.load(path)
    except (YAMLError, UnicodeDecodeError):
        return None
    return tree if isinstance(tree, CommentedMap) else None


def _key_rank(key: str) -> int:
    return KEY_ORDER.index(key) if key in KEY_ORDER else len(KEY_ORDER)


def _node(value: Any, key: str | None = None) -> Any:
    """A plain value as a ruamel node: block collections, dates unquoted, multi-line text as a literal block."""
    if isinstance(value, Mapping):
        node = CommentedMap()
        for k, v in value.items():
            node[k] = _node(v, k)
        return node
    if isinstance(value, (list, tuple)):
        return CommentedSeq(_node(v) for v in value)
    if isinstance(value, str):
        if key in DATE_KEYS and _DATE.match(value):
            return dt.date.fromisoformat(value)
        if "\n" in value.rstrip("\n"):
            return LiteralScalarString(value)
    return value


def _merge(old: Any, new: Any, key: str | None = None) -> Any:
    if yaml_io.to_plain(old) == new:
        return old  # unchanged: keep the node with its style and comments
    if isinstance(old, CommentedMap) and isinstance(new, Mapping):
        return _merge_map(old, new)
    if isinstance(old, CommentedSeq) and isinstance(new, (list, tuple)):
        return _merge_seq(old, new)
    if isinstance(old, ScalarString) and isinstance(new, str) and "\n" not in new.rstrip("\n"):
        return type(old)(new)  # keep folded, literal or quoted style
    return _node(new, key)


def _merge_map(old: CommentedMap, new: Mapping, order: Sequence[str] = ()) -> CommentedMap:
    for key in [k for k in old if k not in new]:
        del old[key]
    for key, value in new.items():
        if key in old:
            old[key] = _merge(old[key], value, key)
            continue
        position = len(old)
        if key in order:
            later = [i for i, k in enumerate(old) if k in order and order.index(k) > order.index(key)]
            position = later[0] if later else len(old)
        old.insert(position, key, _node(value, key))
    return old


def _tail_slot(node: Any) -> tuple[dict, Any, int] | None:
    """Where ruamel keeps the comment after the last scalar of a block collection."""
    while isinstance(node, (CommentedMap, CommentedSeq)) and node and not node.fa.flow_style():
        key = next(reversed(node)) if isinstance(node, CommentedMap) else len(node) - 1
        value = node[key]
        if isinstance(value, (CommentedMap, CommentedSeq)) and value and not value.fa.flow_style():
            node = value
            continue
        return node.ca.items, key, 2 if isinstance(node, CommentedMap) else 0
    return None


def _split_tail(seq: CommentedSeq) -> str | None:
    """Detach what follows the line of the last item (blank lines, the next key's comment); the line comment stays."""
    slot = _tail_slot(seq)
    token = slot[0].get(slot[1], [None] * 4)[slot[2]] if slot else None
    if token is None or "\n" not in token.value:
        return None
    head, _, rest = token.value.partition("\n")
    if head:
        token.value = head + "\n"
    else:
        slot[0][slot[1]][slot[2]] = None
    return rest or None


def _attach_tail(seq: CommentedSeq, tail: str) -> None:
    slot = _tail_slot(seq)
    if slot is None:
        return
    entry = slot[0].setdefault(slot[1], [None] * 4)
    token = entry[slot[2]]
    if token is None:
        entry[slot[2]] = CommentToken("\n" + tail, CommentMark(0), None)
    else:
        token.value += tail


def _merge_seq(old: CommentedSeq, new: Sequence) -> CommentedSeq:
    """Edit the list in place so comments on untouched items stay with them."""
    if len(old) == len(new):
        for i, value in enumerate(new):
            old[i] = _merge(old[i], value)
        return old
    tail = _split_tail(old)
    as_text = lambda v: json.dumps(v, sort_keys=True, default=str)  # noqa: E731
    matcher = difflib.SequenceMatcher(a=[as_text(yaml_io.to_plain(v)) for v in old], b=[as_text(v) for v in new],
                                      autojunk=False)
    for tag, i1, i2, j1, j2 in reversed(matcher.get_opcodes()):
        if tag == "equal":
            continue
        if tag == "replace" and i2 - i1 == j2 - j1:
            for offset in range(i2 - i1):
                old[i1 + offset] = _merge(old[i1 + offset], new[j1 + offset])
            continue
        for i in reversed(range(i1, i2)):
            del old[i]
        for offset, value in enumerate(new[j1:j2]):
            old.insert(i1 + offset, _node(value))
    if tail:
        _attach_tail(old, tail)
    return old
