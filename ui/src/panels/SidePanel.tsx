// The side panel: what the selection is. Symbol card with callers and callees and "open in editor",
// the refs behind an edge, a component card, or a summary of the level.
import { useEffect, useState } from "react";

import {
  api,
  type CallList,
  type ComponentCard,
  type RefList,
  type SymbolCard,
  type View,
  type ViewNode,
} from "../api/client";
import { cycleGroups } from "../graph/edges";
import { cardTitle } from "../graph/NodeCard";
import { drillScope } from "../nav";
import { useMap } from "../store";

/** Load data for the panel; a newer request cancels an older one. */
function useLoad<T>(load: () => Promise<T>, deps: unknown[]): { data: T | null; error: string | null } {
  const [state, setState] = useState<{ data: T | null; error: string | null }>({ data: null, error: null });
  useEffect(() => {
    let current = true;
    setState({ data: null, error: null });
    load().then(
      (data) => current && setState({ data, error: null }),
      (error: unknown) => current && setState({ data: null, error: error instanceof Error ? error.message : String(error) }),
    );
    return () => {
      current = false;
    };
  }, deps);
  return state;
}

const CALLABLE = new Set(["function", "method", "constructor"]);

function shortId(id: string): string {
  return id.startsWith("cxx ") ? id.slice(4) : id;
}

function SymbolLink({ id, label }: { id: string; label?: string }) {
  const showSymbol = useMap((s) => s.showSymbol);
  return (
    <button type="button" className="link" title={id} onClick={() => void showSymbol(id)}>
      {label ?? shortId(id)}
    </button>
  );
}

function Calls({ title, list, side }: { title: string; list: CallList | null; side: "caller" | "callee" }) {
  if (!list) return null;
  return (
    <section>
      <h3>
        {title} <span className="count">{list.items.length}{list.more ? "+" : ""}</span>
      </h3>
      {list.items.length === 0 ? (
        <p className="muted">none in the call graph</p>
      ) : (
        <ul className="plain">
          {list.items.map((call) => (
            <li key={`${call.caller}>${call.callee}`}>
              <SymbolLink id={call[side]} label={side === "caller" ? call.caller_name : call.callee_name} />
              <span className="muted"> {call.path}:{call.line}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function SymbolPanel({ id }: { id: string }) {
  const card = useLoad<SymbolCard>(() => api.symbol(id), [id]);
  const callers = useLoad<CallList>(() => api.callers(id), [id]);
  const callees = useLoad<CallList>(() => api.callees(id), [id]);
  if (card.error) return <p className="error">{card.error}</p>;
  const s = card.data;
  if (!s) return <p className="muted">Loading…</p>;
  const place = s.defs[0] ?? s.decls[0];
  return (
    <div className="panel-body">
      <h2>{s.name}</h2>
      <p className="muted">
        {s.kind}
        {s.access ? ` · ${s.access}` : ""} · {s.component ?? "no component"}
      </p>
      {s.signature && <pre className="code">{s.signature}</pre>}
      {place && (
        <p>
          {s.defs.length ? "Defined in" : "Declared in"} <code>{place.path}:{place.line}</code>
        </p>
      )}
      {s.editor_uri && (
        <a className="button" href={s.editor_uri}>
          Open in editor
        </a>
      )}
      {s.doc && <pre className="doc">{s.doc}</pre>}
      {CALLABLE.has(s.kind) && <Calls title="Callers" list={callers.data} side="caller" />}
      {CALLABLE.has(s.kind) && <Calls title="Callees" list={callees.data} side="callee" />}
      <p className="muted small" title={s.id}>{s.id}</p>
    </div>
  );
}

export function EdgePanel({ view, src, dst }: { view: View; src: string; dst: string }) {
  const samples = useLoad<RefList>(() => api.samples(view.scope, src, dst), [view.scope, src, dst]);
  const edge = view.edges.find((e) => e.src === src && e.dst === dst);
  const name = (id: string) => {
    const node = [...view.nodes, ...view.boundary].find((n) => n.id === id);
    return node ? cardTitle(node) : shortId(id);
  };
  return (
    <div className="panel-body">
      <h2>
        {name(src)} → {name(dst)}
      </h2>
      {edge && (
        <p className="muted">
          {edge.refs} refs · {edge.calls} calls · {edge.uses} uses · {edge.declared ? "declared" : "not declared"}
          {edge.issues.map((code) => (
            <span key={code} className="badge badge-issue">
              {code.replaceAll("_", " ")}
            </span>
          ))}
        </p>
      )}
      {samples.error && <p className="error">{samples.error}</p>}
      {samples.data && (
        <section>
          <h3>
            Examples <span className="count">{samples.data.items.length}{samples.data.more ? "+" : ""}</span>
          </h3>
          <ul className="plain">
            {samples.data.items.map((ref) => (
              <li key={`${ref.path}:${ref.line}:${ref.column}:${ref.symbol}`}>
                <code>
                  {ref.path}:{ref.line}
                </code>{" "}
                <span className="muted">{ref.roles.join(", ")}</span>
                <br />
                {ref.container ? <SymbolLink id={ref.container} /> : <span className="muted">file scope</span>} →{" "}
                <SymbolLink id={ref.symbol} />
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

export function ComponentPanel({ id }: { id: string }) {
  const navigate = useMap((s) => s.navigate);
  const card = useLoad<ComponentCard>(() => api.component(id), [id]);
  if (card.error) return <p className="error">{card.error}</p>;
  const c = card.data;
  if (!c) return <p className="muted">Loading…</p>;
  const model = c.model as { name?: string; kind?: string; lifecycle?: string; intent?: string };
  return (
    <div className="panel-body">
      <h2>{model.name ?? c.id}</h2>
      <p className="muted">
        {model.kind ?? "component"} · {model.lifecycle ?? "current"} · {c.symbols} symbols ({c.own_symbols} own)
      </p>
      {model.intent ? <p className="intent">{model.intent}</p> : <p className="muted">No intent yet.</p>}
      <button type="button" className="button" onClick={() => navigate(c.id)}>
        Open
      </button>
      {c.issues.length > 0 && (
        <section>
          <h3>Issues</h3>
          <ul className="plain">
            {c.issues.map((issue) => (
              <li key={issue.text} className="issue">
                {issue.text}
              </li>
            ))}
          </ul>
        </section>
      )}
      <section>
        <h3>Depends on</h3>
        <ul className="plain">
          {c.edges_out.map((e) => (
            <li key={e.node}>
              {e.node} <span className="muted">{e.refs} refs{e.declared ? "" : " · not declared"}</span>
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h3>Used by</h3>
        <ul className="plain">
          {c.edges_in.map((e) => (
            <li key={e.node}>
              {e.node} <span className="muted">{e.refs} refs</span>
            </li>
          ))}
        </ul>
      </section>
      <p className="muted small">
        {c.interface.length} interface symbols · fingerprint {c.fingerprint}
      </p>
    </div>
  );
}

function LevelPanel({ view }: { view: View }) {
  const select = useMap((s) => s.select);
  const undeclared = view.edges.filter((e) => e.issues.includes("undeclared_dependency"));
  const cycles = cycleGroups(view.edges);
  const issues = view.nodes.filter((n) => n.issues.length > 0);
  const names = new Map([...view.nodes, ...view.boundary].map((n) => [n.id, cardTitle(n)]));
  return (
    <div className="panel-body">
      <h2>{view.trail[view.trail.length - 1]?.name ?? view.scope}</h2>
      <p className="muted">
        {view.nodes.length} nodes · {view.edges.length} edges
        {view.grouped_by ? ` · grouped by ${view.grouped_by}` : ""}
      </p>
      <p className="muted small">
        Double click opens a component. Dragging pins a node. Click a node or an edge for details.
      </p>
      {(undeclared.length > 0 || cycles.length > 0 || issues.length > 0) && (
        <section>
          <h3>Issues on this level</h3>
          <ul className="plain">
            {cycles.map((group) => (
              <li key={group.join(",")}>
                <span className="issue">cycle of {group.length}:</span>{" "}
                {group.map((id, i) => (
                  <span key={id}>
                    {i > 0 && ", "}
                    <button type="button" className="link" onClick={() => select({ kind: "node", id })}>
                      {names.get(id) ?? id}
                    </button>
                  </span>
                ))}
              </li>
            ))}
            {undeclared.map((e) => (
              <li key={`${e.src}>${e.dst}`}>
                <button type="button" className="link" onClick={() => select({ kind: "edge", src: e.src, dst: e.dst })}>
                  {names.get(e.src) ?? e.src} → {names.get(e.dst) ?? e.dst}
                </button>{" "}
                <span className="muted">not in requires</span>
              </li>
            ))}
            {issues.map((n) => (
              <li key={n.id}>
                <button type="button" className="link" onClick={() => select({ kind: "node", id: n.id })}>
                  {cardTitle(n)}
                </button>{" "}
                <span className="muted">{n.issues.join(", ").replaceAll("_", " ")}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function NodePanel({ node, symbol }: { node: ViewNode; symbol?: string }) {
  const navigate = useMap((s) => s.navigate);
  if (node.type === "symbol") return <SymbolPanel id={symbol ?? node.id} />;
  if (node.type === "component") return <ComponentPanel id={node.id} />;
  const scope = drillScope(node.id, node.type);
  return (
    <div className="panel-body">
      <h2>{cardTitle(node)}</h2>
      <p className="muted">
        {node.type} · {node.symbols} symbols
      </p>
      {scope && (
        <button type="button" className="button" onClick={() => navigate(scope)}>
          Open
        </button>
      )}
    </div>
  );
}

export function SidePanel() {
  const view = useMap((s) => s.view);
  const selection = useMap((s) => s.selection);
  if (!view) return <aside className="panel" />;
  let body = <LevelPanel view={view} />;
  if (selection?.kind === "edge") {
    body = <EdgePanel view={view} src={selection.src} dst={selection.dst} />;
  } else if (selection?.kind === "node") {
    const node = [...view.nodes, ...view.boundary].find((n) => n.id === selection.id);
    if (node) body = <NodePanel node={node} symbol={selection.symbol} />;
  }
  return <aside className="panel">{body}</aside>;
}
