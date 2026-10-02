// Map state: the open level, what is selected, how edges are measured. Everything comes from the View API.
import { create } from "zustand";

import { api, ApiError, clientProject, type Camera, type ComponentTree, type Position, type Status, type View, type Workspace } from "./api/client";
import { initialThreshold, metricThresholds, type Metric } from "./graph/edges";
import { hashForScope, ROOT, scopeFromHash } from "./nav";

export type Selection =
  | { kind: "node"; id: string; symbol?: string; reveal?: boolean }
  | { kind: "edge"; src: string; dst: string }
  | null;

interface MapState {
  workspace: Workspace;
  project: string | null;
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
  initialize(): Promise<void>;
  saveCamera(camera: Camera): void;
  flushWorkspace(): Promise<void>;
}

let request = 0;
let initialization = 0;
let saveTimer: ReturnType<typeof setTimeout> | undefined;
let saves: Promise<void> = Promise.resolve();
const emptyWorkspace = (): Workspace => ({ schema_version: "workspace/0.1", scope: ROOT, views: {} });

function saveViewingState(): void {
  const state = useMap.getState();
  const workspace: Workspace = { ...state.workspace, scope: state.scope, views: { ...state.workspace.views,
    [state.scope]: { ...state.workspace.views[state.scope], metric: state.metric, threshold: state.threshold } } };
  useMap.setState({ workspace });
  const expected = state.project;
  const source = state.status?.project_root;
  if (saveTimer) clearTimeout(saveTimer);
  const save = () => {
    saveTimer = undefined;
    saves = saves.catch(() => undefined).then(() => api.saveWorkspace(workspace, expected)).then(() => undefined).catch((error) => {
      if (useMap.getState().status?.project_root === source) useMap.setState({ error: `Could not save your view: ${message(error)}` });
      throw error;
    });
    // A later save may recover; callers of flushWorkspace still receive the failure.
    void saves.catch(() => undefined);
  };
  pendingSave = save;
  saveTimer = setTimeout(save, 250);
}
let pendingSave: (() => void) | undefined;

function message(error: unknown): string {
  if (error instanceof ApiError) return `${error.message} (${error.code})`;
  return error instanceof Error ? error.message : String(error);
}

export const useMap = create<MapState>()((set, get) => ({
  workspace: emptyWorkspace(),
  project: null,
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

  async initialize() {
    const generation = ++initialization;
    ++request;
    set({ view: null, status: null, tree: null, selection: null, pendingSelection: null, loading: true,
      workspace: emptyWorkspace(), project: clientProject(), metric: "refs", threshold: 1, error: null });
    let restoreError: string | null = null;
    const workspace = await api.workspace().catch((error) => {
      restoreError = `Could not restore your view: ${message(error)}`;
      return emptyWorkspace();
    });
    if (generation !== initialization) return;
    const scope = window.location.hash && window.location.hash !== "#/" ? scopeFromHash(window.location.hash) : workspace.scope;
    set({ workspace, scope });
    window.history.replaceState(null, "", hashForScope(scope));
    await get().refresh();
    if (restoreError) set({ error: restoreError });
  },

  async open(scope) {
    const id = ++request;
    const previousScope = get().view?.scope;
    set({ scope, loading: true, error: null,
      ...(previousScope !== scope ? { view: null, selection: null } : {}) });
    try {
      const view = await api.view(scope);
      if (id !== request) return;
      const saved = get().workspace.views[scope];
      const metric = saved?.metric ?? get().metric;
      const choices = metricThresholds(view.edges, metric);
      const preserved = choices.find((value) => value >= get().threshold) ?? choices.at(-1)!;
      set({ view, loading: false, selection: get().pendingSelection, pendingSelection: null,
        metric, threshold: saved?.threshold ?? (previousScope === scope ? preserved : initialThreshold(view.edges, metric)) });
      saveViewingState();
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
      const selection: Selection = { kind: "node", id: card.place.node, symbol: id, reveal: true };
      if (card.place.scope === get().scope) set({ selection });
      else get().navigate(card.place.scope, selection);
    } catch (error) {
      set({ error: message(error) });
    }
  },

  async refresh() {
    const generation = initialization;
    let metadataError: string | null = null;
    const [status, tree] = await Promise.all([api.status(), api.components()]).catch((error) => {
      metadataError = message(error);
      return [null, null] as const;
    });
    if (generation !== initialization) return;
    if (status && tree) set({ status, tree });
    const { scope, selection } = get();
    set({ pendingSelection: selection });
    await get().open(scope);
    if (metadataError) set((state) => ({ error: state.error ?? metadataError }));
  },

  select(selection) {
    set({ selection });
  },

  setMetric(metric) {
    set({ metric, threshold: initialThreshold(get().view?.edges ?? [], metric) });
    saveViewingState();
  },

  setThreshold(threshold) {
    set({ threshold });
    saveViewingState();
  },

  saveCamera(camera) {
    const { workspace, scope, metric, threshold } = get();
    set({ workspace: { ...workspace, views: { ...workspace.views, [scope]: { camera, metric, threshold } } } });
    saveViewingState();
  },

  async flushWorkspace() {
    if (saveTimer) {
      clearTimeout(saveTimer);
      pendingSave?.();
    }
    await saves;
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
