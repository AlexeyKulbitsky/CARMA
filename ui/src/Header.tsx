// Breadcrumbs, search over components and symbols, and the edge controls.
import { useEffect, useMemo, useRef, useState } from "react";

import { api, type SymbolBrief } from "./api/client";
import { metricThresholds, type Metric, visibleEdges } from "./graph/edges";
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
  const [symbols, setSymbols] = useState<{ query: string; items: SymbolBrief[] }>({ query: "", items: [] });
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const components = useMemo(() => flattenTree(tree?.components ?? []), [tree]);

  useEffect(() => {
    const query = text.trim();
    if (query.length < 2) {
      return;
    }
    let current = true;
    const timer = window.setTimeout(() => {
      api.search(query).then(
        (found) => current && setSymbols({ query, items: found.items }),
        () => current && setSymbols({ query, items: [] }),
      );
    }, 200);
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [text]);

  useEffect(() => {
    if (open) document.getElementById(`search-result-${active}`)?.scrollIntoView?.({ block: "nearest" });
  }, [active, open, symbols]);

  const query = text.trim().toLowerCase();
  const hits: Hit[] = query
    ? [
        ...components
          .filter((c) => c.id.includes(query) || c.name.toLowerCase().includes(query))
          .slice(0, 6)
          .map((item) => ({ kind: "component" as const, item })),
        ...(symbols.query === text.trim() ? symbols.items : []).map((item) => ({ kind: "symbol" as const, item })),
      ]
    : [];

  function choose(hit: Hit) {
    setOpen(false);
    setText("");
    if (hit.kind === "component") navigate(hit.item.parent, { kind: "node", id: hit.item.id, reveal: true });
    else void showSymbol(hit.item.id);
  }

  return (
    <div className="search" ref={box} onBlur={(e) => !box.current?.contains(e.relatedTarget) && setOpen(false)}>
      <input
        type="search"
        role="combobox"
        aria-label="Search components and symbols"
        aria-autocomplete="list"
        aria-expanded={open && hits.length > 0}
        aria-controls={open && hits.length > 0 ? "search-results" : undefined}
        aria-activedescendant={open && hits.length > 0 ? `search-result-${Math.min(active, hits.length - 1)}` : undefined}
        placeholder="Search components and symbols"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
          setActive(0);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setOpen(false);
            return;
          }
          if (e.key === "ArrowDown" && hits.length > 0) {
            e.preventDefault();
            setOpen(true);
            setActive((index) => Math.min(index + 1, hits.length - 1));
          }
          if (e.key === "ArrowUp" && hits.length > 0) {
            e.preventDefault();
            setOpen(true);
            setActive((index) => Math.max(index - 1, 0));
          }
          if (e.key === "Enter" && open && hits.length > 0) {
            e.preventDefault();
            choose(hits[Math.min(active, hits.length - 1)]);
          }
        }}
      />
      {open && hits.length > 0 && (
        <ul id="search-results" className="results" role="listbox" aria-label="Search results">
          {hits.map((hit, index) => (
            <li
              key={`${hit.kind}:${hit.item.id}`}
              id={`search-result-${index}`}
              role="option"
              aria-selected={index === active}
              className={index === active ? "active" : ""}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => choose(hit)}
              onMouseEnter={() => setActive(index)}
            >
                <span className="result-name">{hit.item.name}</span>
                <span className="muted">
                  {hit.kind === "component"
                    ? ` ${hit.item.kind} · ${hit.item.id}`
                    : ` ${hit.item.kind} · ${hit.item.component ?? "external"}`}
                </span>
            </li>
          ))}
        </ul>
      )}
      {open && text.trim().length >= 2 && hits.length === 0 && (
        <div className="results results-empty" role="status">
          {symbols.query === text.trim() ? "No components or symbols found." : "Searching symbols…"}
        </div>
      )}
      <span className="sr-only" role="status" aria-live="polite">
        {open && text.trim().length >= 2 ? `${hits.length} results` : ""}
      </span>
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
  const selection = useMap((s) => s.selection);
  const values = metricThresholds(view?.edges ?? [], metric);
  const thresholdIndex = Math.max(0, values.indexOf(threshold));
  const focus = selection?.kind === "node" ? selection.id : null;
  const visible = view ? visibleEdges(view.edges, metric, threshold, focus).length : 0;
  const pinned = view ? [...view.nodes, ...view.boundary].some((n) => n.pos) : false;
  return (
    <div className="toolbar" role="group" aria-label="Map controls">
      <div className="segmented" role="group" aria-label="Connection metric">
        {METRICS.map((m) => (
          <button key={m} type="button" className={m === metric ? "on" : ""} aria-pressed={m === metric} onClick={() => setMetric(m)}>
            {m}
          </button>
        ))}
      </div>
      <label className="threshold">
        <span>Min {metric}: {threshold}</span>
        <input
          type="range"
          aria-label={`Minimum ${metric} per connection`}
          aria-valuetext={`at least ${threshold} ${metric}; ${visible} of ${view?.edges.length ?? 0} connections shown`}
          min={0}
          max={values.length - 1}
          value={thresholdIndex}
          onChange={(e) => setThreshold(values[Number(e.target.value)])}
          disabled={values.length <= 1}
        />
      </label>
      <span className="shown-count" aria-live="polite">{visible}/{view?.edges.length ?? 0} shown</span>
      {threshold > 1 && <button type="button" className="link" onClick={() => setThreshold(1)}>Show all</button>}
      <button type="button" className="button" disabled={!pinned} onClick={() => void resetLayout()}>
        Reset layout
      </button>
    </div>
  );
}
