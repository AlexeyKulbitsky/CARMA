// Automatic positions from ELK, cached by a hash of the node and edge sets.
// ELK runs in its own Web Worker (elk-worker.min.js), never on the main thread; elk-api.js only
// talks to it. Pinned positions from layout.json always win over the automatic ones.
import ELK, { type ELK as ElkEngine, type ElkNode } from "elkjs/lib/elk-api.js";
import elkWorkerUrl from "elkjs/lib/elk-worker.min.js?url";
import { api } from "../api/client";

export interface Box {
  id: string;
  width: number;
  height: number;
}

export interface Link {
  source: string;
  target: string;
}

export type Positions = Record<string, { x: number; y: number }>;

export type Level = "components" | "symbols";

// Component levels are few nodes where the direction of dependencies matters: layered, top down.
// Symbol levels put dozens of classes into one layer and turn into a thin strip, so they use stress
// and then remove overlaps.
const LAYERED = {
  "elk.algorithm": "layered",
  "elk.direction": "DOWN",
  "elk.spacing.nodeNode": "40",
  "elk.layered.spacing.nodeNodeBetweenLayers": "70",
  "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
};
const STRESS = { "elk.algorithm": "stress", "elk.stress.desiredEdgeLength": "260" };
const NO_OVERLAP = { "elk.algorithm": "sporeOverlap", "elk.spacing.nodeNode": "24" };

/** FNV-1a over the level kind, the scope, the node boxes and the edges, order-independent. */
export function layoutKey(scope: string, level: Level, boxes: Box[], links: Link[], project = ""): string {
  const nodes = boxes.map((b) => `${b.id}:${b.width}x${b.height}`).sort();
  const edges = links.map((l) => `${l.source}>${l.target}`).sort();
  const text = `${project}|${level}|${scope}|${nodes.join(",")}|${edges.join(",")}`;
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, "0") + text.length.toString(16);
}

export function elkGraph(boxes: Box[], links: Link[], options: Record<string, string> = LAYERED): ElkNode {
  const ids = new Set(boxes.map((b) => b.id));
  return {
    id: "level",
    layoutOptions: options,
    children: boxes.map((b) => ({ id: b.id, width: b.width, height: b.height })),
    edges: links
      .filter((l) => ids.has(l.source) && ids.has(l.target) && l.source !== l.target)
      .map((l, i) => ({ id: `e${i}`, sources: [l.source], targets: [l.target] })),
  };
}

/** Pinned positions override the automatic ones. */
export function withPinned(auto: Positions, pinned: Positions): Positions {
  return { ...auto, ...pinned };
}

const memory = new Map<string, Positions>();
let engine: ElkEngine | null = null;

export async function autoLayout(scope: string, level: Level, boxes: Box[], links: Link[],
                                 projectKey = "", project: string | null = null): Promise<Positions> {
  const key = layoutKey(scope, level, boxes, links, projectKey);
  const persisted = memory.has(key) ? null : await api.cachedLayout(key, project);
  const known = memory.get(key) ?? (persisted && Object.keys(persisted.positions).length ? persisted.positions : null);
  if (known) {
    memory.set(key, known);
    return known;
  }
  engine ??= new ELK({ workerUrl: elkWorkerUrl });
  let result = await engine.layout(elkGraph(boxes, links, level === "components" ? LAYERED : STRESS));
  if (level === "symbols") {
    const placed = (result.children ?? []).map((c) => ({ id: c.id, x: c.x, y: c.y, width: c.width, height: c.height }));
    result = await engine.layout({ ...elkGraph(boxes, links, NO_OVERLAP), children: placed });
  }
  const positions: Positions = {};
  for (const child of result.children ?? []) positions[child.id] = { x: child.x ?? 0, y: child.y ?? 0 };
  memory.set(key, positions);
  await api.cacheLayout({ key, positions }, project);
  return positions;
}
