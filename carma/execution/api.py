"""Normalized function flow. Adapters produce this data; the core adds contextual targets."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

VERSION = "execution/0.2"


class Data(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ExecutionCall(Data):
    symbol: str | None
    name: str
    receiver: str | None = None
    arguments: list[str | None] = []
    virtual: bool = False
    candidates: list[str] = []
    expandable: list[str] = []
    resolution: Literal["direct", "inferred", "virtual", "unknown"] = "direct"
    explanation: str = ""
    bindings: dict[str, str] = {}
    assignments: list[ExecutionEffect] = []


class ExecutionEffect(Data):
    target: str
    value: str | None = None
    type_symbol: str | None = None
    ownership: str | None = None


class ExecutionObject(Data):
    id: str
    name: str
    type_name: str
    type_symbol: str | None
    ownership: Literal["value", "borrowed", "unique", "shared", "raw"]
    created: bool
    line: int = Field(ge=1)


class ExecutionNode(Data):
    id: str
    anchor: str = Field(default="", description="Content anchor stable across line shifts; repeated statements have distinct occurrences")
    kind: Literal["entry", "exit", "action", "branch", "loop", "return", "break", "continue", "opaque"]
    label: str
    code: str
    path: str
    line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    calls: list[ExecutionCall] = []
    effects: list[ExecutionEffect] = []
    objects: list[str] = []
    note: str = ""


class ExecutionEdge(Data):
    source: str
    target: str
    label: str = ""


class ExecutionGroup(Data):
    id: str
    label: str
    members: list[str]
    origin: Literal["comment", "structure"]


class ExecutionFunction(Data):
    schema_version: Literal["execution/0.2"] = VERSION
    symbol: str
    name: str
    path: str
    line: int = Field(ge=1)
    entry: str
    exit: str
    parameters: list[str] = []
    nodes: list[ExecutionNode]
    edges: list[ExecutionEdge]
    objects: list[ExecutionObject] = []
    warnings: list[str] = []
    groups: list[ExecutionGroup] = []


class FlowProvider(Protocol):
    def function(self, symbol: str, path: str, line: int) -> ExecutionFunction: ...


class ExecutionUnavailable(Exception):
    """No source body or usable compilation settings are available."""
