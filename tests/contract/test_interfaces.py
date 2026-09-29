"""Contracts 2, 5, 6: interfaces and the tool list match the spec."""

from carma.contracts import mcp_tool_names
from carma.llm import api as llm_api
from carma.store import api as store_api

# docs/carma-spec.md, «Контракт 2».
STORE_OPERATIONS = {
    "begin_load", "file_hashes",
    "get_symbol", "search_symbols", "symbols_in_file", "list_files", "symbol_at",
    "refs_to", "refs_from", "relations",
    "set_membership", "component_edges", "edge_samples",
    "callers", "callees", "paths",
    "stats",
}

# docs/carma-spec.md, «Контракт 5».
MCP_TOOLS = [
    "carma_status", "list_components", "get_component", "component_deps", "search_symbols",
    "get_symbol", "callers", "callees", "find_paths", "highlight", "clear_highlight",
    "annotate_component", "propose_component",
]


def protocol_methods(protocol) -> set[str]:
    return {name for name, value in vars(protocol).items() if callable(value) and not name.startswith("_")}


def test_store_operations():
    assert store_api.CONTRACT_VERSION == "store/0.1"
    assert protocol_methods(store_api.FactStore) == STORE_OPERATIONS
    assert protocol_methods(store_api.LoadSession) == {"put", "delete_file", "commit"}


def test_mcp_tool_list():
    assert mcp_tool_names() == MCP_TOOLS


class FakeProvider:
    contract_version = llm_api.CONTRACT_VERSION
    capabilities = llm_api.Capabilities(structured_output=False, tool_use=False, max_context_tokens=8000)

    def complete(self, messages, *, output_schema=None, tools=None, max_tokens=4096):
        return llm_api.Completion(text="ok", json=None, usage=llm_api.Usage(1, 1), stop_reason="end")


def test_llm_provider_shape():
    assert llm_api.CONTRACT_VERSION == "llm/0.1"
    provider = FakeProvider()
    assert isinstance(provider, llm_api.LLMProvider)
    result = provider.complete([llm_api.Message(role="user", content="hi")])
    assert result.text == "ok"
