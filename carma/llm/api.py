"""Contract 6: LLM provider for batch passes of the core.

Not called anywhere in v0 (all LLM work goes through the agent over MCP). The interface
is fixed now so later batch passes do not bind to a single provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

CONTRACT_VERSION = "llm/0.1"


@dataclass(frozen=True)
class Capabilities:
    structured_output: bool
    tool_use: bool
    max_context_tokens: int


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class Completion:
    text: str | None
    json: Any | None
    usage: Usage
    stop_reason: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


@runtime_checkable
class LLMProvider(Protocol):
    contract_version: str
    capabilities: Capabilities

    def complete(
        self,
        messages: list[Message],
        *,
        output_schema: dict | None = None,
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 4096,
    ) -> Completion:
        """Without native structured output, the adapter validates the JSON itself and retries once with the error text."""
        ...
