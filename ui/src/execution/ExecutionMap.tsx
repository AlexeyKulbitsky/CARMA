import { Background, Controls, Handle, MarkerType, Position, ReactFlow, SelectionMode, useNodesState, useReactFlow, type Node, type NodeProps } from "@xyflow/react";
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { api, type ExecutionEntity, type ExecutionFunction, type ExecutionNode, type SymbolBrief, type StudyAnnotation } from "../api/client";
import type { Positions } from "../layout/layout";
import { executionDiagram, executionPositions, type DiagramNode } from "./diagram";
import { callKey, useExecution, viewKey } from "./store";
import { blockKey, groupVisibleSteps, studyBlocks, studyKey, visibleStudySteps } from "./study";

function targetName(id: string) {
  const text = id.replace(/^cxx /, "");
  const hash = text.lastIndexOf("#");
  return hash >= 0 ? text.slice(0, hash).split("/").at(-1) + "::" + text.slice(hash + 1) : text.split("/").at(-1);
}

type StepNode = Node<{ item: DiagramNode }, "step">;
function StepCard({ data, selected }: NodeProps<StepNode>) {
  const { step, functionName, prefix, group, annotation, detached } = data.item;
  const blocks = useExecution((s) => s.saved.views?.[viewKey(s.saved.entry ?? "", s.saved.entry_path)]?.blocks);
  const expanded = group && blocks?.includes(blockKey(detached ? `detached:${detached}` : prefix, group.id));
  return <div className={`execution-card execution-${group ? "group" : step.kind} study-${annotation?.status ?? "unread"}${annotation?.color ? " study-colored" : ""}${selected ? " selected" : ""}`}
    style={annotation?.color ? { "--study-color": annotation.color } as CSSProperties : undefined}>
    <Handle id="flow-in" type="target" position={Position.Top} />
    <Handle id="details-in" type="target" position={Position.Left} />
    <span className="execution-kind">{group ? "block" : step.kind}{prefix !== "root" && ` · ${functionName}`}</span>
    <strong>{step.label}</strong>
    <span className="execution-location">{step.path}:{step.line}</span>
    <div className="execution-card-actions nodrag">
      {group && <button onClick={(e) => { e.stopPropagation(); useExecution.getState().select(data.item.id); useExecution.getState().toggleBlock(prefix, group.id, detached); }}>
        {expanded ? "Collapse" : "Expand"} block</button>}
      {annotation?.status && annotation.status !== "unread" && <span className="badge">{annotation.status}</span>}
      {annotation?.note && <span className="badge" title={annotation.note}>note</span>}
      {step.calls?.some((c) => c.virtual) && <span className="badge">virtual</span>}
    </div>
    <Handle id="flow-out" type="source" position={Position.Bottom} />
    <Handle id="details-out" type="source" position={Position.Right} />
  </div>;
}
type InspectionNode = Node<{ title: string; width: number; height: number; inspector: string }, "inspection">;
function InspectionFrame({ data }: NodeProps<InspectionNode>) {
  return <div className="inspection-frame" style={{ height: data.height, width: data.width }}>
    <div className="inspection-heading"><strong>{data.title}</strong><button className="nodrag" aria-label="Close separate view"
      onClick={() => useExecution.getState().closeInspector(data.inspector)}>×</button></div>
  </div>;
}
const nodeTypes = { step: StepCard, inspection: InspectionFrame };

export function ExecutionControls() {
  const entries = useExecution((s) => s.entries);
  const saved = useExecution((s) => s.saved);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<SymbolBrief[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const timer = setTimeout(() => {
      if (!query.trim()) { setFound([]); return; }
      void api.search(query, 30).then((data) => {
        if (active) { setFound(data.items.filter((s) => ["function", "method", "constructor"].includes(s.kind) && !s.external)); setError(""); }
      }, (error) => active && setError(String(error)));
    }, 250);
    return () => { active = false; clearTimeout(timer); };
  }, [query]);
  const chosen = saved.entry ? viewKey(saved.entry, saved.entry_path) : "";
  return <>
    <label className="execution-picker">Entry point
      <select aria-label="Entry point" value={chosen} onChange={(event) => {
        const item = entries.find((s) => viewKey(s.id, s.path) === event.target.value);
        if (item) void useExecution.getState().open(item.id, item.path ?? undefined);
      }}>
        <option value="" disabled>Choose an entry point…</option>
        {saved.entry && !entries.some((s) => viewKey(s.id, s.path) === chosen) && <option value={chosen}>{targetName(saved.entry)}</option>}
        {entries.map((item) => <option key={viewKey(item.id, item.path)} value={viewKey(item.id, item.path)}>{item.name} · {item.path}</option>)}
      </select>
    </label>
    <div className="execution-search"><input aria-label="Explore a function" placeholder="Explore a function…" value={query} onChange={(e) => setQuery(e.target.value)} />
      {!!query && <div className="execution-search-results">
        {error && <p role="alert">{error}</p>}
        {found.map((s) => <button className="link" key={s.id} onClick={() => { setQuery(""); void useExecution.getState().open(s.id, s.path ?? undefined); }}>
          {s.signature ?? s.name}<small>{s.path}</small></button>)}
        {!found.length && !error && <p className="muted">Search for a function or method.</p>}
      </div>}
    </div>
  </>;
}

export function ExecutionMap() {
  const functions = useExecution((s) => s.functions);
  const saved = useExecution((s) => s.saved);
  const loading = useExecution((s) => s.loading);
  const error = useExecution((s) => s.error);
  const expanding = useExecution((s) => s.expanding);
  const placing = useExecution((s) => s.placing);
  const past = useExecution((s) => s.past.length);
  const future = useExecution((s) => s.future.length);
  const key = viewKey(saved.entry ?? "", saved.entry_path);
  const view = saved.views?.[key];
  const diagram = useMemo(() => executionDiagram(functions, saved, view), [functions, saved, view]);
  const positions = useMemo(() => executionPositions(diagram, view), [diagram, view]);
  useEffect(() => {
    useExecution.getState().keepPositions(positions);
  }, [positions]);
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      const element = event.target as HTMLElement;
      if (element.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(element.tagName)) return;
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.key.toLowerCase() !== "z" && event.key.toLowerCase() !== "y") return;
      if (event.key.toLowerCase() === "y" || event.shiftKey) useExecution.getState().redo();
      else useExecution.getState().undo();
      event.preventDefault();
    };
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, []);
  return <>
    {error && <div className="banner banner-error" role="alert">{error}</div>}
    {(loading || expanding) && <div className="banner" role="status">{loading ? "Reading the selected function…" : "Expanding the call…"}</div>}
    {placing && <div className="banner" role="status">Click a free spot on the map to open this scope separately.
      <button className="link" onClick={() => useExecution.getState().cancelPlacement()}>Cancel</button></div>}
    <main className="main execution-main">
      <div className="graph" role="region" aria-label="Execution map">
        <div className="execution-history" role="group" aria-label="Exploration history">
          <button className="button" disabled={!past} title="Undo (Ctrl/Cmd+Z)" onClick={() => useExecution.getState().undo()}>Undo</button>
          <button className="button" disabled={!future} title="Redo (Ctrl/Cmd+Shift+Z)" onClick={() => useExecution.getState().redo()}>Redo</button>
        </div>
        {!functions.root && !loading && <div className="graph-message"><p>Choose an entry point or search for a function to start exploring.</p></div>}
        {functions.root && positions && <ExecutionGraph key={key} diagram={diagram} positions={positions} />}
      </div>
      <ExecutionPanel />
    </main>
    <footer className="execution-footer">Static flow · read each scope from top to bottom · dashed arrows open details to the right</footer>
  </>;
}

function ExecutionGraph({ diagram, positions }: { diagram: ReturnType<typeof executionDiagram>; positions: Positions }) {
  const selected = useExecution((s) => s.selected);
  const selection = useExecution((s) => s.selection);
  const saved = useExecution((s) => s.saved);
  const flow = useReactFlow();
  const canvasRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuOrigin = useRef<HTMLElement | null>(null);
  const [marquee, setMarquee] = useState(false);
  const [menu, setMenu] = useState<{ x: number; y: number; id?: string } | null>(null);
  const view = saved.views?.[viewKey(saved.entry!, saved.entry_path)];
  const cards = useMemo<(StepNode | InspectionNode)[]>(() => {
    const steps: StepNode[] = diagram.nodes.map((item) => ({ id: item.id, type: "step",
      position: positions[item.id] ?? { x: 0, y: 0 }, data: { item },
      selected: selection.includes(item.id), width: 310, height: 150,
      ariaLabel: `${item.group ? "block" : item.step.kind}: ${item.step.label}, ${item.step.path}:${item.step.line}` }));
    const frames: InspectionNode[] = diagram.scopes.filter((s) => s.id === `detached:${s.detached}`).map((s) => {
      const scopeCards = steps.filter((n) => n.data.item.detached === s.detached);
      const first = scopeCards[0];
      const height = Math.max(...scopeCards.map((n) => n.position.y)) - first.position.y + 230;
      const width = Math.max(...scopeCards.map((n) => n.position.x)) - first.position.x + 346;
      return { id: `frame:${s.detached}`, type: "inspection", data: { title: `Separate view · ${first.data.item.functionName}`, width, height, inspector: s.detached! },
        position: { x: first.position.x - 18, y: first.position.y - 65 }, width, height, zIndex: -1, dragHandle: ".inspection-heading", selectable: false };
    });
    return [...frames, ...steps];
  }, [diagram, positions, selection]);
  const [nodes, setNodes, onNodesChange] = useNodesState(cards);
  useEffect(() => setNodes(cards), [cards, setNodes]);
  const previousScopes = useRef(new Set(diagram.scopes.map((s) => s.id)));
  useEffect(() => {
    const fresh = diagram.scopes.filter((s) => !previousScopes.current.has(s.id));
    previousScopes.current = new Set(diagram.scopes.map((s) => s.id));
    if (!fresh.length) return;
    const scope = fresh.at(-1)!;
    const frame = requestAnimationFrame(() => void flow.fitView({ nodes: diagram.nodes.filter((n) => n.scope === scope.id).slice(0, 3).map((n) => ({ id: n.id })), padding: .3, minZoom: .5, maxZoom: 1 }));
    void frame;
  }, [diagram, flow]);
  useEffect(() => {
    const item = diagram.nodes.find((n) => n.id === selected);
    if (!item) return;
    const focus = item.step.kind === "entry" && !item.group ? diagram.nodes.filter((n) => n.scope === item.scope).slice(0, 3) : [item];
    const frame = requestAnimationFrame(() => void flow.fitView({ nodes: focus.map((n) => ({ id: n.id })), padding: .3, minZoom: .5, maxZoom: 1 }));
    return () => cancelAnimationFrame(frame);
  }, [selected, flow]);
  const edges = useMemo(() => diagram.edges.map((e) => ({ ...e, style: { stroke: e.detail ? "var(--accent)" : "var(--edge)", strokeDasharray: e.detail ? "6 4" : undefined },
    type: e.detail ? "straight" : "smoothstep", sourceHandle: e.detail ? "details-out" : "flow-out", targetHandle: e.detail ? "details-in" : "flow-in",
    markerEnd: { type: MarkerType.ArrowClosed, color: e.detail ? "var(--accent)" : "var(--edge)" } })), [diagram]);
  function showMenu(event: { clientX: number; clientY: number; preventDefault(): void }, id?: string) {
    event.preventDefault();
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    menuOrigin.current = document.activeElement as HTMLElement;
    setMenu({ x: Math.max(8, Math.min(event.clientX - rect.left, rect.width - 248)),
      y: Math.max(8, Math.min(event.clientY - rect.top, rect.height - 300)), id });
  }
  function focusDetails() {
    setMenu(null);
    document.getElementById("execution-details")?.focus();
  }
  const menuItem = menu?.id && diagram.nodes.find((item) => item.id === menu.id);
  const state = useExecution.getState();
  const menuActions: { label: string; run: () => void; disabled?: boolean }[] = menuItem ? [
    { label: "Show details", run: () => { state.select(menuItem.id); focusDetails(); } },
    ...(menuItem.group ? [
      { label: `${view?.blocks?.includes(blockKey(menuItem.detached ? `detached:${menuItem.detached}` : menuItem.prefix, menuItem.group.id)) ? "Collapse" : "Expand"} block`,
        run: () => state.toggleBlock(menuItem.prefix, menuItem.group!.id, menuItem.detached) },
      { label: "Open separately", run: () => state.place(menuItem.prefix, menuItem.group!.id) },
      { label: "Ungroup block", run: () => state.ungroup(menuItem.prefix, menuItem.group!.id) },
    ] : []),
    ...(menuItem.step.kind === "entry" && !menuItem.group ? [
      { label: "Open separately", run: () => state.place(menuItem.prefix, null) },
      ...(menuItem.prefix !== "root" ? [{ label: "Collapse function", run: () => state.collapse(menuItem.prefix) }] : []),
    ] : []),
    ...(menuItem.step.calls ?? []).flatMap((call, index) => {
      const key = callKey(menuItem.prefix, menuItem.step.id, index);
      return state.functions[key] ? [{ label: `Collapse ${call.name}`, run: () => state.collapse(key) }] :
        (call.expandable ?? []).map((target) => ({ label: `Expand ${targetName(target)}`, run: () => void state.expand(key, target), disabled: !!state.expanding }));
    }),
    ...([ ["Mark understood", "understood"], ["Mark studying", "studying"], ["Mark as question", "question"] ] as const)
      .map(([label, status]) => ({ label, run: () => state.annotate(menuItem.prefix, menuItem.annotationKey, { status }) })),
    { label: "Set color or title…", run: () => { state.select(menuItem.id); focusDetails();
      requestAnimationFrame(() => document.querySelector<HTMLInputElement>('[aria-label="Block title"]')?.focus()); } },
    { label: "Add or edit note", run: () => { state.select(menuItem.id); focusDetails();
      requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>('[aria-label="Study note"]')?.focus()); } },
    ...(selection.length > 1 && selection.includes(menuItem.id) ? [{ label: "Group selected blocks…", run: () => {
      focusDetails(); requestAnimationFrame(() => document.querySelector<HTMLInputElement>('[aria-label="Selected group name"]')?.focus());
    } }] : []),
  ] : [
    { label: "Undo", run: () => state.undo(), disabled: !state.past.length },
    { label: "Redo", run: () => state.redo(), disabled: !state.future.length },
    { label: marquee ? "Pan map" : "Select blocks", run: () => setMarquee(!marquee) },
  ];
  useEffect(() => {
    if (!menu) return;
    menuRef.current?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus();
    const dismiss = (event: PointerEvent) => { if (!menuRef.current?.contains(event.target as globalThis.Node)) setMenu(null); };
    window.addEventListener("pointerdown", dismiss);
    return () => window.removeEventListener("pointerdown", dismiss);
  }, [menu]);
  return <div className="execution-canvas" ref={canvasRef} tabIndex={0} aria-label="Execution canvas actions"
    onKeyDown={(event) => {
      if ((event.key === "Enter" || event.key === " ") && !(event.target as Element).closest("button, input, textarea, select")) {
        const focused = (event.target as Element).closest<HTMLElement>('.react-flow__node[data-id]');
        if (focused?.dataset.id) useExecution.getState().select(focused.dataset.id);
      }
      if (!(event.key === "ContextMenu" || event.key === "F10" && event.shiftKey)) return;
      const node = (event.target as Element).closest<HTMLElement>('.react-flow__node[data-id]');
      const id = node?.dataset.id;
      if (id && !useExecution.getState().selection.includes(id)) useExecution.getState().select(id);
      const rect = (node ?? canvasRef.current)!.getBoundingClientRect();
      showMenu({ clientX: rect.left + 18, clientY: rect.top + 18, preventDefault: () => event.preventDefault() }, id);
    }}>
    <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={(changes) => {
      onNodesChange(changes);
      // React Flow's keyboard nudges do not emit onNodeDragStop.
      const completed = Object.fromEntries(changes.flatMap((change) => change.type === "position" && change.position && !change.dragging ?
        [[change.id, change.position] as const] : []));
      if (Object.keys(completed).length) useExecution.getState().pinMany(completed);
    }}
    onSelectionEnd={() => useExecution.getState().selectMany(flow.getNodes().filter((n) => n.type === "step" && n.selected).map((n) => n.id))}
    onNodeClick={(event, n) => {
      if (n.type !== "step") return;
      const state = useExecution.getState();
      if (event.ctrlKey || event.metaKey) state.selectMany(state.selection.includes(n.id) ? state.selection.filter((id) => id !== n.id) : [...state.selection, n.id]);
      else state.select(n.id);
    }}
    onNodeDoubleClick={(_, n) => {
      const item = diagram.nodes.find((step) => step.id === n.id);
      if (!item) return;
      const current = useExecution.getState();
      current.select(item.id);
      if (item.group) { current.toggleBlock(item.prefix, item.group.id, item.detached); return; }
      const choices = (item.step.calls ?? []).flatMap((call, index) => (call.expandable ?? []).map((target) => ({ key: callKey(item.prefix, item.step.id, index), target })));
      if (choices.length === 1) {
        if (current.functions[choices[0].key]) current.collapse(choices[0].key);
        else void current.expand(choices[0].key, choices[0].target);
      } else focusDetails();
    }}
    onNodeContextMenu={(event, n) => {
      if (n.type !== "step") return;
      if (!useExecution.getState().selection.includes(n.id)) useExecution.getState().select(n.id);
      showMenu(event, n.id);
    }}
    onPaneContextMenu={(event) => showMenu(event)}
    onPaneClick={(event) => { setMenu(null); const state = useExecution.getState(); if (state.placing) state.attach(flow.screenToFlowPosition({ x: event.clientX, y: event.clientY })); else state.select(null); }}
    onNodeDragStop={(_, n) => {
      if (n.type === "inspection") {
        const original = cards.find((c) => c.id === n.id)!.position;
        useExecution.getState().moveInspector((n as InspectionNode).data.inspector, { x: n.position.x - original.x, y: n.position.y - original.y });
      } else {
        const moved = flow.getNodes().filter((item) => item.type === "step" && item.selected);
        const positions = Object.fromEntries((moved.length ? moved : [n]).map((item) => [item.id, item.position]));
        useExecution.getState().pinMany(positions);
      }
    }}
    onMoveEnd={(_, camera) => useExecution.getState().camera(camera)} defaultViewport={view?.camera ?? undefined}
    fitView={!view?.camera} fitViewOptions={{ nodes: diagram.nodes.filter((n) => n.prefix === "root").slice(0, 3).map((n) => ({ id: n.id })), padding: .2, minZoom: .5, maxZoom: 1 }} minZoom={.08} maxZoom={2}
    nodesConnectable={false} deleteKeyCode={null} zoomOnDoubleClick={false} onlyRenderVisibleElements
    selectionOnDrag={marquee} selectionMode={SelectionMode.Partial} panOnDrag={marquee ? [1] : true}
    ariaLabelConfig={{
      "node.a11yDescription.default": "Press Enter or Space to select a block. Use the details panel for actions.",
      "node.a11yDescription.keyboardDisabled": "Press Enter or Space to select a block. Use the details panel for actions.",
      "edge.a11yDescription.default": "Control flow or detail connection between blocks.",
    }}>
    <Background gap={24} /><Controls showInteractive={false} />
  </ReactFlow>
    <div className="execution-selection-tools" role="group" aria-label="Canvas selection">
      <button className="button" aria-pressed={marquee} onClick={() => setMarquee(!marquee)}>{marquee ? "Pan map" : "Select blocks"}</button>
      <span>{marquee ? "Drag a rectangle to select; middle drag pans" : "Shift+drag selects; drag pans"}</span>
    </div>
    {menu && <div className="execution-context-menu" ref={menuRef} role="menu" aria-label={menuItem ? "Block actions" : "Canvas actions"}
      style={{ left: menu.x, top: menu.y }} onKeyDown={(event) => {
        if (event.key === "Escape") { setMenu(null); menuOrigin.current?.focus(); event.stopPropagation(); return; }
        if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const buttons = [...menuRef.current!.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')];
        const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
        buttons[event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 :
          (index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length]?.focus();
      }}>
      {menuActions.map((action) => <button type="button" role="menuitem" key={action.label} disabled={action.disabled}
        onClick={() => { setMenu(null); action.run(); }}>{action.label}</button>)}
    </div>}
  </div>;
}

function CallActions({ prefix, step }: { prefix: string; step: ExecutionNode }) {
  const functions = useExecution((s) => s.functions);
  const expanding = useExecution((s) => s.expanding);
  return <section><h3>Calls in this step</h3>{(step.calls ?? []).map((call, index) => {
    const key = callKey(prefix, step.id, index);
    const candidates = call.expandable ?? [];
    return <div className="execution-call" key={key}>
      <strong>{call.name}</strong> <span className="badge">{call.resolution}</span>
      {call.explanation && <p className="muted small">{call.explanation}</p>}
      {call.assignments?.map((a, i) => <p className="small" key={i}>Stores <code>{a.value}</code> in <code>{targetName(a.target)}</code>{a.ownership && ` (${a.ownership})`}.</p>)}
      {functions[key] ? <><button className="button" onClick={() => useExecution.getState().collapse(key)}>Collapse {call.name}</button>
        <button className="button" onClick={() => void useExecution.getState().expand(key, functions[key].symbol)}>Show details here</button></> :
        candidates.map((target) => <button className="button" disabled={!!expanding} key={target} title={target}
          onClick={() => void useExecution.getState().expand(key, target)}>Expand {targetName(target)}</button>)}
      {!candidates.length && <p className="muted">{call.symbol ? "No indexed project body is available for this call." : "No statically resolved target."}</p>}
    </div>;
  })}</section>;
}

function EntityPanel({ id }: { id: string }) {
  const [data, setData] = useState<ExecutionEntity | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    setData(null); setError(null);
    void api.entity(id).then((d) => active && setData(d), (e) => active && setError(String(e)));
    return () => { active = false; };
  }, [id]);
  if (error) return <p role="alert">{error}</p>;
  if (!data) return <p role="status">Reading the entity…</p>;
  const fields = data.members.filter((m) => ["field", "variable"].includes(m.kind));
  const methods = data.members.filter((m) => ["method", "constructor", "function"].includes(m.kind));
  return <section className="execution-entity"><button className="link" onClick={() => useExecution.getState().inspect(null)}>← Back to step</button>
    <h2>{data.symbol.name}</h2><p><code>{data.symbol.signature}</code></p>
    {data.symbol.editor_uri && <a className="button" href={data.symbol.editor_uri}>Open in editor</a>}
    {!!data.bases.length && <><h3>Base types</h3>{data.bases.map((b) => <button className="link" key={b.id} onClick={() => useExecution.getState().inspect(b.id)}>{b.name}</button>)}</>}
    <h3>Fields</h3>{fields.length ? <ul className="plain">{fields.map((m) => <li key={m.id}><code>{m.signature ?? m.name}</code></li>)}</ul> : <p className="muted">No indexed fields.</p>}
    <h3>Methods</h3><ul className="plain">{methods.map((m) => <li key={m.id}><button className="link" onClick={() => void useExecution.getState().open(m.id, m.path ?? undefined)}>{m.signature ?? m.name}</button></li>)}</ul>
  </section>;
}

function Objects({ flow, ids }: { flow: ExecutionFunction; ids?: string[] }) {
  const objects = (flow.objects ?? []).filter((o) => !ids || ids.includes(o.id));
  return <section><h3>Objects</h3>{!objects.length ? <p className="muted">No objects declared here.</p> : objects.map((o) => <div className="execution-object" key={o.id}>
    <strong>{o.name}</strong> <span className="badge">{o.ownership}</span><p className="muted small">{o.created ? "Created" : "Declared or acquired"} at {flow.path}:{o.line}</p>
    <button className="link" disabled={!o.type_symbol} onClick={() => useExecution.getState().inspect(o.type_symbol)}>{o.type_name}</button>
  </div>)}</section>;
}

const statuses: [NonNullable<StudyAnnotation["status"]>, string][] = [["unread", "Not studied"], ["studying", "Studying"], ["understood", "Understood"], ["question", "Question"]];

function StudyEditor({ item }: { item: DiagramNode }) {
  const edit = (patch: Partial<StudyAnnotation>) => useExecution.getState().annotate(item.prefix, item.annotationKey, patch);
  return <section className="study-editor"><h3>My understanding</h3>
    <label>Title<input aria-label="Block title" value={item.annotation?.title ?? ""} placeholder={item.step.label} maxLength={300} onChange={(e) => edit({ title: e.target.value })} /></label>
    <label>Status<select aria-label="Study status" value={item.annotation?.status ?? "unread"} onChange={(e) => edit({ status: e.target.value as StudyAnnotation["status"] })}>
      {statuses.map(([value, name]) => <option value={value} key={value}>{name}</option>)}
    </select></label>
    <label>Color<div className="study-colors">{["", "#4682b4", "#438a60", "#c18a26", "#aa66aa", "#b45151"].map((color) =>
      <button className={item.annotation?.color === color ? "chosen" : ""} key={color} aria-label={color ? `Use color ${color}` : "Default color"}
        title={color || "Default color"} style={{ background: color || "var(--panel)" }} onClick={() => edit({ color })}>{color ? "" : "×"}</button>)}
      <input aria-label="Custom block color" type="color" value={item.annotation?.color || "#4682b4"} onChange={(e) => edit({ color: e.target.value })} /></div></label>
    <label>Note<textarea aria-label="Study note" value={item.annotation?.note ?? ""} placeholder="What does this block do? What should I investigate?" maxLength={20000} rows={4} onChange={(e) => edit({ note: e.target.value })} /></label>
  </section>;
}

function ScopeSteps({ flow, scope, items }: { flow: ExecutionFunction; scope: string; items: DiagramNode[] }) {
  const flowApi = useReactFlow();
  const [chosen, setChosen] = useState<string[]>([]);
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);
  const visible = visibleStudySteps(items);
  return <details className="execution-step-list" open><summary>Steps in {flow.name}</summary>
    <p className="muted small">Select consecutive blocks to give them one name.</p>
    <ol>{visible.map((n) => <li key={n.id}><label className="study-selection"><input type="checkbox" aria-label={`Group ${n.step.label}`} checked={chosen.includes(n.id)}
      onChange={(e) => setChosen(e.target.checked ? [...chosen, n.id] : chosen.filter((id) => id !== n.id))} />
      <button className="link" onClick={() => { useExecution.getState().select(n.id); void flowApi.fitView({ nodes: [{ id: n.id }], padding: .8, maxZoom: 1 }); }}>{n.step.label}</button></label>
    </li>)}</ol>
    {chosen.length > 0 && <div className="study-group-form"><input aria-label="New group name" value={title} maxLength={300} placeholder="Name this block…" onChange={(e) => setTitle(e.target.value)} />
      <button className="button" disabled={!title.trim()} onClick={() => {
        const result = groupVisibleSteps(flow, items, chosen);
        if (result.error) { setError(result.error); return; }
        useExecution.getState().group(items[0].prefix, result.members, title); setChosen([]); setTitle(""); setError(null);
      }}>Group selected blocks</button>{error && <p role="alert">{error}</p>}</div>}
    <span className="sr-only">{scope}</span>
  </details>;
}

function SelectionEditor({ nodes, diagram, functions }: { nodes: DiagramNode[]; diagram: ReturnType<typeof executionDiagram>; functions: Record<string, ExecutionFunction> }) {
  const [title, setTitle] = useState("");
  const [note, setNote] = useState("");
  const [color, setColor] = useState("#438a60");
  const sameScope = nodes.every((item) => item.scope === nodes[0].scope);
  const flow = sameScope ? functions[nodes[0].prefix] : undefined;
  const group = flow ? groupVisibleSteps(flow, diagram.nodes.filter((item) => item.scope === nodes[0].scope), nodes.map((item) => item.id)) :
    { error: "Select consecutive blocks in one area.", members: [] as string[] };
  const items = [...new Map(nodes.map((item) => [`${item.prefix}:${item.annotationKey}`, { prefix: item.prefix, key: item.annotationKey }])).values()];
  return <section className="execution-selection-editor" aria-label="Selected blocks">
    <button className="link" onClick={() => useExecution.getState().select(null)}>← Clear selection</button>
    <h2>{nodes.length} blocks selected</h2>
    <p className="muted small">Drag a selection rectangle, Ctrl/Cmd+click blocks, or use the Steps checklist. Grouping requires consecutive blocks in one area.</p>
    <label>Group name<input aria-label="Selected group name" value={title} maxLength={300} placeholder="Name this block…" onChange={(event) => setTitle(event.target.value)} /></label>
    <button className="button" disabled={!title.trim() || !!group.error} onClick={() => {
      useExecution.getState().group(nodes[0].prefix, group.members, title);
      setTitle("");
    }}>Group selected blocks</button>
    {group.error && <p className="muted small">{group.error}</p>}
    <h3>Apply to selected blocks</h3>
    <label>Status<select aria-label="Selected status" onChange={(event) => useExecution.getState().annotateMany(items, { status: event.target.value as StudyAnnotation["status"] })} defaultValue="">
      <option value="" disabled>Choose a status…</option>{statuses.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
    </select></label>
    <label>Color<div className="selection-color"><input aria-label="Selected color" type="color" value={color} onChange={(event) => setColor(event.target.value)} />
      <button className="button" onClick={() => useExecution.getState().annotateMany(items, { color })}>Apply color</button></div></label>
    <label>Note<textarea aria-label="Selected note" value={note} maxLength={20000} rows={3} placeholder="Apply the same note to all selected blocks…" onChange={(event) => setNote(event.target.value)} /></label>
    <button className="button" disabled={!note.trim()} onClick={() => useExecution.getState().annotateMany(items, { note })}>Apply note</button>
  </section>;
}

function ExecutionPanel() {
  const functions = useExecution((s) => s.functions);
  const saved = useExecution((s) => s.saved);
  const selected = useExecution((s) => s.selected);
  const selection = useExecution((s) => s.selection);
  const entity = useExecution((s) => s.entity);
  const flowApi = useReactFlow();
  const view = saved.views?.[viewKey(saved.entry ?? "", saved.entry_path)];
  const diagram = useMemo(() => executionDiagram(functions, saved, view), [functions, saved, view]);
  const item = diagram.nodes.find((n) => n.id === selected);
  const selectedNodes = diagram.nodes.filter((n) => selection.includes(n.id));
  const functionFlow = item ? functions[item.prefix] : functions.root;
  const steps = (scope: string, flow: ExecutionFunction) => <ScopeSteps key={scope} scope={scope} flow={flow} items={diagram.nodes.filter((n) => n.scope === scope)} />;
  const knowledge = functionFlow && studyBlocks(functionFlow, saved.studies?.[studyKey(functionFlow)]);
  const itemBlockKey = item?.group ? blockKey(item.detached ? `detached:${item.detached}` : item.prefix, item.group.id) : null;
  const groupOpen = itemBlockKey && view?.blocks?.includes(itemBlockKey);
  return <aside id="execution-details" tabIndex={-1} className="panel execution-panel" aria-label="Execution details"><div className="panel-body">
    {entity ? <EntityPanel id={entity} /> : selectedNodes.length > 1 ? <SelectionEditor nodes={selectedNodes} diagram={diagram} functions={functions} /> : item ? <>
      <button className="link" onClick={() => useExecution.getState().select(null)}>← Exploration overview</button>
      <h2>{item.group ? item.step.label : item.step.kind === "entry" ? item.functionName : "Execution step"}</h2>
      <p className="muted">{item.step.path}:{item.step.line}–{item.step.end_line} · {item.functionName}</p>
      {item.group && <div className="study-scope-actions"><button className="button" onClick={() => useExecution.getState().toggleBlock(item.prefix, item.group!.id, item.detached)}>{groupOpen ? "Collapse" : "Expand"} block</button>
        <button className="button" onClick={() => useExecution.getState().place(item.prefix, item.group!.id)}>Open separately</button>
        <button className="link" onClick={() => useExecution.getState().ungroup(item.prefix, item.group!.id)}>Ungroup block</button></div>}
      {item.detached && <button className="button" onClick={() => useExecution.getState().closeInspector(item.detached!)}>Close separate view</button>}
      {item.step.kind === "entry" && !item.group && <div className="study-scope-actions">
        <button className="button" onClick={() => useExecution.getState().place(item.prefix, null)}>Open separately</button>
        {item.prefix !== "root" && <button className="button" onClick={() => useExecution.getState().collapse(item.prefix)}>Collapse function</button>}
      </div>}
      <StudyEditor item={item} />
      {item.group ? <details><summary>Source instructions ({item.members.length})</summary><pre className="execution-source">{item.step.code}</pre></details> : <pre className="execution-source">{item.step.code}</pre>}
      {item.step.note && !item.group && <p className="banner banner-warning">{item.step.note}</p>}
      {!!item.step.calls?.length && <CallActions prefix={item.prefix} step={item.step} />}
      {functionFlow && item.group && groupOpen && steps(itemBlockKey!, functionFlow)}
      <section className="execution-position"><h3>Position</h3><div className="move-buttons">{[
        ["left", -40, 0], ["right", 40, 0], ["up", 0, -40], ["down", 0, 40],
      ].map(([direction, dx, dy]) => <button className="button" key={direction} onClick={() => {
        const position = flowApi.getNode(item.id)?.position;
        if (position) useExecution.getState().pin(item.id, { x: position.x + Number(dx), y: position.y + Number(dy) });
      }}>Move step {direction}</button>)}</div></section>
      {functionFlow && <Objects flow={functionFlow} ids={item.step.kind === "entry" && !item.group ? undefined : item.step.objects ?? []} />}
      {functionFlow && item.step.kind === "entry" && !item.group && steps(item.scope, functionFlow)}
    </> : <>
      <h2>{functions.root?.name ?? "Explore execution"}</h2>
      <p>Read from top to bottom. Expand calls and blocks to the right. Add names, notes and study marks as you build your understanding.</p>
      <p className="muted small">This shows possible source paths. Implicit cleanup and exception unwinding are not expanded.</p>
      {functions.root && <Objects flow={functions.root} />}
      {functions.root && steps("root", functions.root)}
      <h3>Expanded functions</h3><ul className="plain">{Object.entries(functions).map(([prefix, f]) => <li key={prefix}>
        <button className="link" onClick={() => { useExecution.getState().select(`${prefix}/${f.entry}`);
          void flowApi.fitView({ nodes: diagram.nodes.filter((n) => n.scope === prefix).slice(0, 3).map((n) => ({ id: n.id })), padding: .2, maxZoom: 1 }); }}>{f.name}</button>
        {prefix !== "root" && <button className="link small" onClick={() => useExecution.getState().collapse(prefix)}>Collapse</button>}
      </li>)}</ul>
      {!!Object.keys(view?.detached ?? {}).length && <><h3>Separate views</h3>{Object.keys(view!.detached!).map((id) => <div key={id}>
        <button className="link" onClick={() => void flowApi.fitView({ nodes: diagram.nodes.filter((n) => n.detached === id).slice(0, 3).map((n) => ({ id: n.id })), padding: .3, maxZoom: 1 })}>Show separate view</button>
        <button className="link" onClick={() => useExecution.getState().closeInspector(id)}>Close separate view</button></div>)}</>}
    </>}
    {knowledge && (knowledge.stale.length > 0 || knowledge.unbound.length > 0) && <details className="banner banner-warning"><summary>Some saved knowledge needs review after source changes</summary>
      {knowledge.stale.map((title) => <p key={title}>Unattached group: {title}</p>)}
      {knowledge.unbound.map((key) => { const note = saved.studies?.[studyKey(functionFlow!)]?.annotations?.[key];
        return <p key={key}>{note?.title || key}: {note?.note || note?.status}</p>; })}</details>}
    {functionFlow?.warnings?.map((w) => <p className="banner banner-warning small" key={w}>{w}</p>)}
  </div></aside>;
}
