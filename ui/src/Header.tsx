// Breadcrumbs, search over components and symbols, and the edge controls.
import { useEffect, useMemo, useRef, useState } from "react";

import { api, type SymbolBrief } from "./api/client";
import { type Metric, maxMetric } from "./graph/edges";
import { crumbLabel, type FlatComponent, flattenTree } from "./nav";
import { useMap } from "./store";

export function Breadcrumbs() {
  const view = useMap((s) => s.view);
  const status = useMap((s) => s.status);
  const navigate = useMap((s) => s.navigate);
  if (!view) return <nav className="crumbs" />;
  return (
    <nav className="crumbs" aria-label="level">
      {view.trail.map((crumb, i) => {
        const last = i === view.trail.length - 1;
        return (
          <span key={crumb.scope} className="crumb">
            {i > 0 && <span className="sep">/</span>}
            {last ? (
              <strong>{crumbLabel(crumb, status?.project_name)}</strong>
            ) : (
              <button type="button" className="link" onClick={() => navigate(crumb.scope)}>
                {crumbLabel(crumb, status?.project_name)}
              </button>
            )}
          </span>
        );
      })}
    </nav>
  );
}

type Hit = { kind: "component"; item: FlatComponent } | { kind: "symbol"; item: SymbolBrief };

export function Search() {
  const tree = useMap((s) => s.tree);
  const navigate = useMap((s) => s.navigate);
  const showSymbol = useMap((s) => s.showSymbol);
  const [text, setText] = useState("");
  const [symbols, setSymbols] = useState<SymbolBrief[]>([]);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const components = useMemo(() => flattenTree(tree?.components ?? []), [tree]);

  useEffect(() => {
    const query = text.trim();
    if (query.length < 2) {
      setSymbols([]);
      return;
    }
    let current = true;
    const timer = window.setTimeout(() => {
      api.search(query).then(
        (found) => current && setSymbols(found.items),
        () => current && setSymbols([]),
      );
    }, 200);
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [text]);

  const query = text.trim().toLowerCase();
  const hits: Hit[] = query
    ? [
        ...components
          .filter((c) => c.id.includes(query) || c.name.toLowerCase().includes(query))
          .slice(0, 6)
          .map((item) => ({ kind: "component" as const, item })),
        ...symbols.map((item) => ({ kind: "symbol" as const, item })),
      ]
    : [];

  function choose(hit: Hit) {
    setOpen(false);
    setText("");
    if (hit.kind === "component") navigate(hit.item.parent, { kind: "node", id: hit.item.id });
    else void showSymbol(hit.item.id);
  }

  return (
    <div className="search" ref={box} onBlur={(e) => !box.current?.contains(e.relatedTarget) && setOpen(false)}>
      <input
        type="search"
        placeholder="Search components and symbols"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
          if (e.key === "Enter" && hits[0]) choose(hits[0]);
        }}
      />
      {open && hits.length > 0 && (
        <ul className="results" role="listbox">
          {hits.map((hit) => (
            <li key={`${hit.kind}:${hit.item.id}`}>
              <button type="button" onClick={() => choose(hit)}>
                <span className="result-name">{hit.item.name}</span>
                <span className="muted">
                  {hit.kind === "component"
                    ? ` ${hit.item.kind} · ${hit.item.id}`
                    : ` ${hit.item.kind} · ${hit.item.component ?? "external"}`}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const METRICS: Metric[] = ["refs", "calls", "uses"];

export function Toolbar() {
  const view = useMap((s) => s.view);
  const metric = useMap((s) => s.metric);
  const threshold = useMap((s) => s.threshold);
  const setMetric = useMap((s) => s.setMetric);
  const setThreshold = useMap((s) => s.setThreshold);
  const resetLayout = useMap((s) => s.resetLayout);
  const max = view ? maxMetric(view.edges, metric) : 0;
  const pinned = view ? [...view.nodes, ...view.boundary].some((n) => n.pos) : false;
  return (
    <div className="toolbar">
      <div className="segmented" role="group" aria-label="edge metric">
        {METRICS.map((m) => (
          <button key={m} type="button" className={m === metric ? "on" : ""} onClick={() => setMetric(m)}>
            {m}
          </button>
        ))}
      </div>
      <label className="threshold" title="hide edges weaker than this">
        ≥ {threshold}
        <input
          type="range"
          min={1}
          max={Math.max(1, max)}
          value={Math.min(threshold, Math.max(1, max))}
          onChange={(e) => setThreshold(Number(e.target.value))}
        />
      </label>
      <button type="button" className="button" disabled={!pinned} onClick={() => void resetLayout()}>
        Reset layout
      </button>
    </div>
  );
}
