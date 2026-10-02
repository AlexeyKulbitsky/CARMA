// Edge metrics: thickness by the chosen metric, a threshold for weak edges, focus on a selected node.
import type { ViewEdge } from "../api/client";

export type Metric = "refs" | "calls" | "uses";
export type EdgeTone = "undeclared" | "cycle" | "declared" | "plain";

export const MAX_WIDTH = 8;

export function edgeWidth(value: number, max: number): number {
  if (value <= 0 || max <= 0) return 1;
  return 1 + (MAX_WIDTH - 1) * Math.sqrt(Math.min(value, max) / max);
}

/** Edges worth drawing: with the metric at or above the threshold (and above zero), touching the focused node. */
export function visibleEdges(edges: ViewEdge[], metric: Metric, threshold: number, focus: string | null): ViewEdge[] {
  const floor = Math.max(1, threshold);
  return edges.filter((e) => e[metric] >= floor && (focus === null || e.src === focus || e.dst === focus));
}

export function maxMetric(edges: ViewEdge[], metric: Metric): number {
  return edges.reduce((max, e) => Math.max(max, e[metric]), 0);
}

export function metricThresholds(edges: ViewEdge[], metric: Metric): number[] {
  return [...new Set([1, ...edges.map((edge) => edge[metric]).filter((value) => value > 0)])].sort((a, b) => a - b);
}

/** Start large levels with their strongest connections visible; the slider can reveal the rest. */
export function initialThreshold(edges: ViewEdge[], metric: Metric, target = 24): number {
  const values = edges.map((edge) => edge[metric]).filter((value) => value > 0).sort((a, b) => b - a);
  return values.length > target ? values[target - 1] : 1;
}

export function edgeTone(edge: ViewEdge): EdgeTone {
  if (edge.issues.includes("undeclared_dependency")) return "undeclared";
  if (edge.issues.includes("cycle")) return "cycle";
  return edge.declared ? "declared" : "plain";
}

/** Nodes that share a cycle on this level, from the edges marked "cycle": one sorted group per cycle. */
export function cycleGroups(edges: ViewEdge[]): string[][] {
  const parent = new Map<string, string>();
  const find = (x: string): string => {
    let root = x;
    while (parent.get(root) !== root) root = parent.get(root)!;
    parent.set(x, root);
    return root;
  };
  for (const e of edges) {
    if (!e.issues.includes("cycle")) continue;
    for (const n of [e.src, e.dst]) if (!parent.has(n)) parent.set(n, n);
    parent.set(find(e.src), find(e.dst));
  }
  const groups = new Map<string, string[]>();
  for (const n of parent.keys()) {
    const root = find(n);
    groups.set(root, [...(groups.get(root) ?? []), n]);
  }
  return [...groups.values()].map((g) => g.sort()).sort((a, b) => a[0].localeCompare(b[0]));
}
