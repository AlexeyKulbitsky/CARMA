// Map state: the open level, what is selected, how edges are measured. Everything comes from the View API.
import { create } from "zustand";

import { api, ApiError, type ComponentTree, type Position, type Status, type View } from "./api/client";
import type { Metric } from "./graph/edges";
import { hashForScope, ROOT, scopeFromHash } from "./nav";

export type Selection =
  | { kind: "node"; id: string; symbol?: string }
  | { kind: "edge"; src: string; dst: string }
  | null;

interface MapState {
  status: Status | null;
  tree: ComponentTree | null;
  scope: string;
  view: View | null;
  loading: boolean;
  error: string | null;
  metric: Metric;
  threshold: number;
  selection: Selection;
  pendingSelection: Selection;

  /** Load the level in the URL hash; the hashchange handler calls it. */
  open(scope: string): Promise<void>;
  /** Go to a level, with a history entry, and select something there once it is loaded. */
  navigate(scope: string, select?: Selection): void;
  /** Go to the level that draws a symbol and select its node. */
  showSymbol(id: string): Promise<void>;
  refresh(): Promise<void>;
  select(selection: Selection): void;
  setMetric(metric: Metric): void;
  setThreshold(threshold: number): void;
  pin(nodeId: string, position: Position): Promise<void>;
  resetLayout(): Promise<void>;
}

let request = 0;

function message(error: unknown): string {
  if (error instanceof ApiError) return `${error.message} (${error.code})`;
  return error instanceof Error ? error.message : String(error);
}

export const useMap = create<MapState>()((set, get) => ({
  status: null,
  tree: null,
  scope: ROOT,
  view: null,
  loading: false,
  error: null,
  metric: "refs",
  threshold: 1,
  selection: null,
  pendingSelection: null,

  async open(scope) {
    const id = ++request;
    set({ scope, loading: true, error: null });
    try {
      const view = await api.view(scope);
      if (id !== request) return;
      set({ view, loading: false, selection: get().pendingSelection, pendingSelection: null, threshold: 1 });
    } catch (error) {
      if (id !== request) return;
      set({ loading: false, error: message(error), pendingSelection: null });
      if (error instanceof ApiError && error.status === 404 && scope !== ROOT) {
        // a stale link or a deleted component: show the top level instead
        window.history.replaceState(null, "", hashForScope(ROOT));
        const shown = get().error;
        await get().open(ROOT);
        set({ error: shown });
      }
    }
  },

  navigate(scope, select = null) {
    const hash = hashForScope(scope);
    set({ pendingSelection: select });
    if (window.location.hash === hash || (scope === ROOT && scopeFromHash(window.location.hash) === ROOT)) {
      void get().open(scope);
    } else {
      window.location.hash = hash;
    }
  },

  async showSymbol(id) {
    try {
      const card = await api.symbol(id);
      if (!card.place) {
        set({ error: `${card.name} is not drawn on the map (${card.external ? "external" : "a namespace"})` });
        return;
      }
      const selection: Selection = { kind: "node", id: card.place.node, symbol: id };
      if (card.place.scope === get().scope) set({ selection });
      else get().navigate(card.place.scope, selection);
    } catch (error) {
      set({ error: message(error) });
    }
  },

  async refresh() {
    const [status, tree] = await Promise.all([api.status(), api.components()]).catch((error) => {
      set({ error: message(error) });
      return [null, null] as const;
    });
    if (status && tree) set({ status, tree });
    const { scope, selection } = get();
    set({ pendingSelection: selection });
    await get().open(scope);
  },

  select(selection) {
    set({ selection });
  },

  setMetric(metric) {
    set({ metric, threshold: 1 });
  },

  setThreshold(threshold) {
    set({ threshold });
  },

  async pin(nodeId, position) {
    const { view, scope } = get();
    if (!view) return;
    const pinned: Record<string, Position> = {};
    for (const node of [...view.nodes, ...view.boundary]) if (node.pos) pinned[node.id] = node.pos;
    pinned[nodeId] = { x: Math.round(position.x), y: Math.round(position.y) };
    const pin = (node: View["nodes"][number]) => (node.id === nodeId ? { ...node, pos: pinned[nodeId] } : node);
    set({ view: { ...view, nodes: view.nodes.map(pin), boundary: view.boundary.map(pin) } });
    try {
      await api.saveLayout(scope, pinned);
    } catch (error) {
      set({ error: message(error) });
    }
  },

  async resetLayout() {
    const { scope, view } = get();
    try {
      await api.saveLayout(scope, {});
      if (view) {
        const unpin = (node: View["nodes"][number]) => ({ ...node, pos: null });
        set({ view: { ...view, nodes: view.nodes.map(unpin), boundary: view.boundary.map(unpin) } });
      }
    } catch (error) {
      set({ error: message(error) });
    }
  },
}));
