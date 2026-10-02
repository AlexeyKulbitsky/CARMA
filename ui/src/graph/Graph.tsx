// The open level as a graph. Double click opens a component; dragging pins a node (PUT /layout).
import {
  Background,
  Controls,
  type Edge,
  MarkerType,
  MiniMap,
  ReactFlow,
  useNodesState,
  useReactFlow,
} from "@xyflow/react";
import { useEffect, useMemo, useState } from "react";

import type { View, ViewEdge } from "../api/client";
import { autoLayout, type Positions, withPinned } from "../layout/layout";
import { drillScope } from "../nav";
import { useMap } from "../store";
import { edgeTone, edgeWidth, maxMetric, visibleEdges } from "./edges";
import { type CardNode, cardHeight, cardTitle, cardWidth, NodeCard } from "./NodeCard";

const nodeTypes = { card: NodeCard };
const TONE_COLOR = {
  undeclared: "var(--edge-undeclared)",
  cycle: "var(--edge-cycle)",
  declared: "var(--edge-declared)",
  plain: "var(--edge)",
};

function pinnedOf(view: View): Positions {
  const pinned: Positions = {};
  for (const node of [...view.nodes, ...view.boundary]) if (node.pos) pinned[node.id] = node.pos;
  return pinned;
}

export function Graph() {
  const view = useMap((s) => s.view);
  const error = useMap((s) => s.error);
  const [auto, setAuto] = useState<{ scope: string; positions: Positions } | null>(null);
  const [layoutError, setLayoutError] = useState<string | null>(null);

  // Layout depends on which nodes and edges exist, not on metrics, selection or pins.
  useEffect(() => {
    if (!view) return;
    let current = true;
    setLayoutError(null);
    const boxes = [...view.nodes, ...view.boundary].map((n) => ({ id: n.id, width: cardWidth(n), height: cardHeight(n) }));
    const links = view.edges.map((e) => ({ source: e.src, target: e.dst }));
    autoLayout(view.scope, view.level, boxes, links).then(
      (positions) => {
        if (!current) return;
        setLayoutError(null);
        setAuto({ scope: view.scope, positions });
      },
      (error: unknown) => current && setLayoutError(String(error)),
    );
    return () => {
      current = false;
    };
  }, [view]);

  if (!view) return <div className="graph graph-empty" role="region" aria-label="Architecture map"><p>{error ? "Map unavailable. See the error above." : "Loading map…"}</p></div>;
  return (
    <div className="graph" role="region" aria-label="Architecture map">
      {layoutError && <div className="banner banner-error" role="alert">Layout failed: {layoutError}</div>}
      {(!auto || auto.scope !== view.scope) && !layoutError && <p className="graph-message" role="status">Arranging map…</p>}
      {view.nodes.length === 0 && view.boundary.length === 0 && <p className="graph-message">No nodes on this level.</p>}
      {auto && auto.scope === view.scope && <Level key={view.scope} view={view} positions={auto.positions} />}
    </div>
  );
}

/** One level; mounted anew for every scope, so fitView frames the level once its nodes are in place. */
function Level({ view, positions }: { view: View; positions: Positions }) {
  const flow = useReactFlow();
  const metric = useMap((s) => s.metric);
  const threshold = useMap((s) => s.threshold);
  const selection = useMap((s) => s.selection);
  const select = useMap((s) => s.select);
  const navigate = useMap((s) => s.navigate);
  const pin = useMap((s) => s.pin);
  const focus = selection?.kind === "node" ? selection.id : null;

  const cards = useMemo<CardNode[]>(() => {
    const placed = withPinned(positions, pinnedOf(view));
    const card = (node: View["nodes"][number], boundary: boolean): CardNode => ({
      id: node.id,
      type: "card",
      position: placed[node.id] ?? { x: 0, y: 0 },
      data: { node, boundary },
      ariaLabel: `${node.name}, ${node.type}, ${node.symbols} symbols${node.issues.length ? `, issues: ${node.issues.join(", ").replaceAll("_", " ")}` : ""}`,
      selected: node.id === focus,
      width: cardWidth(node),
      height: cardHeight(node),
    });
    return [...view.nodes.map((n) => card(n, false)), ...view.boundary.map((n) => card(n, true))];
  }, [view, positions, focus]);

  const [nodes, setNodes, onNodesChange] = useNodesState<CardNode>(cards);
  useEffect(() => setNodes(cards), [cards, setNodes]);
  useEffect(() => {
    if (selection?.kind !== "node" || !selection.reveal) return;
    const frame = window.requestAnimationFrame(() => {
      void flow.fitView({ nodes: [{ id: selection.id }], padding: 0.3, maxZoom: 1.1, duration: 250 });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [flow, selection, view.scope]);

  const edges = useMemo<Edge<{ edge: ViewEdge }>[]>(() => {
    const shown = visibleEdges(view.edges, metric, threshold, focus);
    const max = maxMetric(view.edges, metric);
    const boundary = new Set(view.boundary.map((n) => n.id));
    const names = new Map([...view.nodes, ...view.boundary].map((n) => [n.id, cardTitle(n)]));
    return shown.map((e) => {
      const tone = edgeTone(e);
      return {
        id: `${e.src}->${e.dst}`,
        source: e.src,
        target: e.dst,
        data: { edge: e },
        className: `edge edge-${tone}${boundary.has(e.src) || boundary.has(e.dst) ? " edge-boundary" : ""}`,
        style: { strokeWidth: edgeWidth(e[metric], max) },
        markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, markerUnits: "userSpaceOnUse", color: TONE_COLOR[tone] },
        label: String(e[metric]),
        ariaLabel: `${names.get(e.src) ?? e.src} to ${names.get(e.dst) ?? e.dst}, ${e[metric]} ${metric}${e.issues.length ? `, issues: ${e.issues.join(", ").replaceAll("_", " ")}` : ""}`,
        selected: selection?.kind === "edge" && selection.src === e.src && selection.dst === e.dst,
      };
    });
  }, [view, metric, threshold, focus, selection]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodesChange={onNodesChange}
      onNodeClick={(_, node) => select({ kind: "node", id: node.id })}
      onNodeDoubleClick={(_, node) => {
        const scope = drillScope(node.id, (node as CardNode).data.node.type);
        if (scope) navigate(scope);
      }}
      onEdgeClick={(_, edge) => select({ kind: "edge", src: edge.source, dst: edge.target })}
      onPaneClick={() => select(null)}
      onNodeDragStop={(_, node) => void pin(node.id, node.position)}
      onlyRenderVisibleElements
      nodesConnectable={false}
      zoomOnDoubleClick={false}
      fitView
      fitViewOptions={{ padding: 0.12, minZoom: 0.8 }}
      minZoom={0.4}
      maxZoom={2}
    >
      <Background gap={24} />
      <Controls showInteractive={false} />
      <MiniMap pannable zoomable className="minimap" ariaLabel="Map overview; drag or zoom to navigate" />
    </ReactFlow>
  );
}
