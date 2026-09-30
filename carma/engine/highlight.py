"""Highlight lifting (spec «Ядро», 5): one highlight in terms of facts, shown on any level."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from carma.engine.state import State
from carma.engine.symbols import top_symbol
from carma.engine.tree import EXTERNAL, ROOT, UNASSIGNED
from carma.engine.views import View


class HighlightError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class Step:
    caption: str
    symbols: tuple[str, ...] = ()
    components: tuple[str, ...] = ()


@dataclass(frozen=True)
class Highlight:
    title: str
    steps: tuple[Step, ...]


@dataclass(frozen=True)
class LiftedStep:
    caption: str
    nodes: tuple[str, ...]  # visible nodes of the level, in the order the step names them
    unresolved: tuple[str, ...]  # symbol and component IDs that are not in the facts or the model


@dataclass(frozen=True)
class LiftedHighlight:
    scope: str
    title: str
    steps: tuple[LiftedStep, ...]


def parse_highlight(data: Any) -> Highlight:
    """The body of POST /highlight: {title, steps: [{caption, symbols?, components?}]}."""
    errors: list[str] = []
    if not isinstance(data, dict):
        raise HighlightError(["<root>: must be an object"])
    title = data.get("title")
    if not isinstance(title, str) or not title:
        errors.append("title: a non-empty string is required")
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        errors.append("steps: a non-empty list is required")
        raw_steps = []
    steps = []
    for n, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            errors.append(f"steps/{n}: must be an object")
            continue
        caption = raw.get("caption")
        if not isinstance(caption, str) or not caption:
            errors.append(f"steps/{n}/caption: a non-empty string is required")
        lists = {}
        for key in ("symbols", "components"):
            value = raw.get(key, [])
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                errors.append(f"steps/{n}/{key}: must be a list of strings")
                value = []
            lists[key] = tuple(value)
        if not lists["symbols"] and not lists["components"]:
            errors.append(f"steps/{n}: needs symbols or components")
        unknown = set(raw) - {"caption", "symbols", "components"}
        if unknown:
            errors.append(f"steps/{n}: unknown keys {sorted(unknown)}")
        steps.append(Step(caption or "", lists["symbols"], lists["components"]))
    unknown = set(data) - {"title", "steps"}
    if unknown:
        errors.append(f"<root>: unknown keys {sorted(unknown)}")
    if errors:
        raise HighlightError(errors)
    return Highlight(title, tuple(steps))


def _symbol_node(state: State, view: View, sid: str) -> str | None:
    cid = state.membership.component_of.get(sid)
    if cid is None or cid == EXTERNAL:
        return None
    if view.level == "components":
        return state.tree.node_at(view.scope, cid)[0]
    if cid == view.component:
        return view.node_of.get(top_symbol(sid, state.symbols))
    return state.tree.node_at(view.component, cid)[0]


def _component_node(state: State, view: View, cid: str) -> str | None:
    """A component that is the open level or contains it gives no node there."""
    if view.component != ROOT and (cid == view.component or state.tree.is_ancestor(cid, view.component)):
        return None
    return state.tree.node_at(view.component, cid)[0]


def lift(highlight: Highlight, view: View, state: State) -> LiftedHighlight:
    visible = {n.id for n in view.nodes} | {n.id for n in view.boundary}
    steps = []
    for step in highlight.steps:
        candidates: list[str | None] = []
        unresolved: list[str] = []
        for sid in step.symbols:
            if sid in state.symbols:
                candidates.append(_symbol_node(state, view, sid))
            else:
                unresolved.append(sid)
        for cid in step.components:
            if cid in state.model.components or cid == UNASSIGNED:
                candidates.append(_component_node(state, view, cid))
            else:
                unresolved.append(cid)
        nodes: list[str] = []
        for node in candidates:
            if node is not None and node in visible and node not in nodes:
                nodes.append(node)
        steps.append(LiftedStep(step.caption, tuple(nodes), tuple(unresolved)))
    return LiftedHighlight(view.scope, highlight.title, tuple(steps))
