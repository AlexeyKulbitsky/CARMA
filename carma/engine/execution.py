"""Static, contextual execution views over normalized adapter data and indexed symbols."""

from collections import deque

from carma.engine.symbols import place_loc
from carma.execution.api import ExecutionFunction, ExecutionUnavailable, FlowProvider


def entrypoints(core) -> list[dict]:
    result = []
    for symbol in core.state.symbols.values():
        if symbol.kind == "function" and not symbol.external and symbol.name in {"main", "wmain", "WinMain", "wWinMain"}:
            card = core.symbol(symbol.id)
            for location in card.symbol.defs:
                result.append({"id": symbol.id, "name": symbol.name, "kind": symbol.kind, "signature": symbol.signature,
                               "component": card.component, "path": location.path,
                               "line": location.range[0] + 1, "external": False})
    return sorted(result, key=lambda s: (s["name"] != "main", s["path"] or "", s["id"]))


def read_function(core, provider: FlowProvider, symbol: str, path: str | None = None) -> ExecutionFunction:
    card = core.symbol(symbol)
    location = place_loc(card.symbol)
    if path is not None:
        location = next((loc for loc in card.symbol.defs if loc.path == path), None)
    if not location or card.symbol.external:
        raise ExecutionUnavailable("This function has no source body in the project.")
    return provider.function(symbol, location.path, location.range[0] + 1).model_copy(deep=True)


def _overrides(core, symbol: str) -> list[str]:
    found, pending = set(), [symbol]
    while pending:
        for relation in core.store.relations(pending.pop(), "overrides", "in"):
            if relation.from_id not in found:
                found.add(relation.from_id)
                pending.append(relation.from_id)
    return sorted(found)


def _merge(states: list[dict[str, str]]) -> dict[str, str]:
    if not states:
        return {}
    return {key: value for key, value in states[0].items() if all(s.get(key) == value for s in states[1:])}


def execution_view(core, provider: FlowProvider, symbol: str, bindings: dict[str, str], path: str | None = None) -> ExecutionFunction:
    flow = read_function(core, provider, symbol, path)
    bindings = dict(bindings)
    for index, parameter in enumerate(flow.parameters):
        if bindings.get(f"$arg{index}"):
            bindings[parameter] = bindings[f"$arg{index}"]
            if bindings.get(f"$alias{index}"):
                bindings["&" + parameter] = bindings[f"$alias{index}"]
    nodes = {n.id: n for n in flow.nodes}
    predecessors: dict[str, list[str]] = {n: [] for n in nodes}
    successors: dict[str, list[str]] = {n: [] for n in nodes}
    for edge in flow.edges:
        predecessors[edge.target].append(edge.source)
        successors[edge.source].append(edge.target)
    summaries: dict[str, list] = {}

    def setter_effects(callee):
        if callee not in summaries:
            effects = []
            info = core.state.symbols.get(callee)
            if info and info.kind == "method" and not info.external:
                try:
                    location = place_loc(core.symbol(callee).symbol)
                    if not location or location.extent[2] - location.extent[0] > 10:
                        summaries[callee] = []
                        return []
                    candidate = read_function(core, provider, callee)
                    # Only short unconditional methods qualify. Complex behavior is never guessed from a name.
                    if (len(candidate.nodes) <= 8 and not any(n.kind in {"branch", "loop", "opaque"} for n in candidate.nodes)
                            and all(c.name in {"reset", "move", "forward", "operator="} for n in candidate.nodes for c in n.calls)):
                        effects = [(e, candidate.parameters) for n in candidate.nodes for e in n.effects
                                   if e.target.startswith("cxx ") and e.value in candidate.parameters]
                except ExecutionUnavailable:
                    pass
            summaries[callee] = effects
        return summaries[callee]

    def transfer(node, incoming, decorate=False):
        state = dict(incoming)
        def field_key(key):
            return "@" + state["$this"] + "::" + key if key.startswith("cxx ") and "$this" in state else key
        def type_of(key):
            return state.get(field_key(key)) or state.get(key)
        def identity(key):
            if key == "this":
                return state.get("$this", symbol)
            if key.startswith("cxx "):
                qualified = field_key(key)
                return state.get("&" + qualified, qualified)
            return state.get("&" + key, symbol + "|" + key)
        for call in node.calls:
            receiver_type = type_of(call.receiver or "")
            choices = []
            if call.symbol:
                alternatives = _overrides(core, call.symbol) if call.virtual else []
                choices = [call.symbol, *alternatives]
                if receiver_type and call.virtual:
                    concrete = [sid for sid in choices if core.state.symbols.get(sid) and
                                core.state.symbols[sid].parent == receiver_type]
                    if concrete:
                        choices = concrete
            chosen = choices[0] if len(choices) == 1 else call.symbol
            info = core.state.symbols.get(chosen)
            nested = {k: v for k, v in state.items() if k.startswith(("cxx ", "@", "&@"))}
            if receiver_type:
                nested["this"] = receiver_type
                nested["$this"] = identity(call.receiver)
            elif info and info.parent:
                nested["this"] = info.parent
            for index, argument in enumerate(call.arguments):
                if argument and type_of(argument):
                    nested[f"$arg{index}"] = type_of(argument)
                    nested[f"$alias{index}"] = identity(argument)
            if chosen:
                # Parameters and stored object types are propagated only by inspected assignments.
                for effect, parameters in setter_effects(chosen):
                    index = parameters.index(effect.value)
                    key = call.arguments[index] if index < len(call.arguments) else None
                    destination = "@" + identity(call.receiver or "this") + "::" + effect.target
                    if key and type_of(key):
                        state[destination] = type_of(key)
                        state["&" + destination] = identity(key)
                    else:
                        state.pop(destination, None)
                        state.pop("&" + destination, None)
                    if decorate:
                        call.assignments.append(effect.model_copy(update={"value": key, "type_symbol": type_of(key or "")}))
            if decorate:
                call.candidates = choices
                call.expandable = [sid for sid in choices if sid in core.state.symbols and
                                   not core.state.symbols[sid].external and core.symbol(sid).symbol.defs]
                call.bindings = nested
                if call.virtual:
                    call.resolution = "inferred" if receiver_type and len(choices) == 1 else "virtual"
                    call.explanation = ("Receiver type inferred from object assignments in this explored path. Later mutations or callbacks may change it."
                                        if call.resolution == "inferred" else "Virtual dispatch: the concrete receiver is not established on this path.")
                elif not call.symbol:
                    call.resolution = "unknown"
                    call.explanation = "The call target could not be resolved statically."
        for effect in node.effects:
            target = field_key(effect.target)
            value = effect.type_symbol or type_of(effect.value or "")
            if value:
                state[target] = value
                if effect.value:
                    state["&" + target] = identity(effect.value)
            else:
                state.pop(target, None)
                state.pop("&" + target, None)
        return state

    outputs: dict[str, dict[str, str]] = {}
    inputs: dict[str, dict[str, str]] = {}
    pending = deque([flow.entry])
    iterations = 0
    while pending and iterations < max(100, len(nodes) * 20):
        nid = pending.popleft()
        incoming = dict(bindings) if nid == flow.entry else _merge([outputs[p] for p in predecessors[nid] if p in outputs])
        inputs[nid] = incoming
        outgoing = transfer(nodes[nid], incoming)
        if outputs.get(nid) != outgoing:
            outputs[nid] = outgoing
            pending.extend(successors[nid])
        iterations += 1
    for nid, node in nodes.items():
        transfer(node, inputs.get(nid, {}), decorate=True)
    if pending:
        flow.warnings.append("Type propagation reached its limit; some receivers remain unresolved.")
    return flow
