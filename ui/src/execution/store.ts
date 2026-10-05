import { create } from "zustand";
import { api, clientProject, type Camera, type ExecutionCall, type ExecutionFunction, type Exploration, type Position, type SymbolBrief, type StudyAnnotation, type FunctionStudy } from "../api/client";
import { anchor, blockKey, studyKey } from "./study";
import { executionDiagram } from "./diagram";

export function viewKey(entry: string, path?: string | null) { return `${entry}@${path ?? ""}`; }
export function callKey(prefix: string, node: string, index: number) { return `${prefix}/${node}@${index}`; }
export function locateCall(functions: Record<string, ExecutionFunction>, key: string): ExecutionCall | undefined {
  const slash = key.lastIndexOf("/");
  const part = key.slice(slash + 1);
  const at = part.lastIndexOf("@");
  return functions[key.slice(0, slash)]?.nodes.find((n) => n.id === part.slice(0, at))?.calls[Number(part.slice(at + 1))];
}

const empty = (): Exploration => ({ schema_version: "exploration/0.2", mode: "execution", entry: null, entry_path: null, views: {} });
let generation = 0;
let modeRevision = 0;
let timer: ReturnType<typeof setTimeout> | undefined;
let pending: (() => void) | undefined;
let saves: Promise<void> = Promise.resolve();

interface ExecutionState {
  saved: Exploration;
  project: string | null;
  entries: SymbolBrief[];
  functions: Record<string, ExecutionFunction>;
  selected: string | null;
  entity: string | null;
  loading: boolean;
  error: string | null;
  expanding: string | null;
  placing: { prefix: string; group: string | null } | null;
  initialize(): Promise<void>;
  open(symbol: string, path?: string): Promise<void>;
  expand(key: string, symbol: string): Promise<void>;
  collapse(key: string): void;
  setMode(mode: "execution" | "architecture"): void;
  select(id: string | null): void;
  inspect(id: string | null): void;
  pin(id: string, position: Position): void;
  camera(camera: Camera): void;
  annotate(prefix: string, key: string, patch: Partial<StudyAnnotation>): void;
  toggleBlock(prefix: string, group: string, detached?: string): void;
  group(prefix: string, members: string[], title: string): void;
  ungroup(prefix: string, id: string): void;
  place(prefix: string, group: string | null): void;
  cancelPlacement(): void;
  attach(position: Position): void;
  closeInspector(id: string): void;
  moveInspector(id: string, delta: Position): void;
  keepPositions(positions: Record<string, Position>): void;
  flush(): Promise<void>;
}

function saveSoon() {
  if (timer) clearTimeout(timer);
  const { saved, project } = useExecution.getState();
  pending = () => {
    timer = undefined;
    saves = saves.catch(() => undefined).then(() => api.saveExploration(saved, project)).then(() => undefined).catch((error) => {
      if (useExecution.getState().project === project) useExecution.setState({ error: `Could not save your exploration: ${String(error)}` });
      throw error;
    });
    void saves.catch(() => undefined);
  };
  timer = setTimeout(pending, 250);
}

function updateView(patch: Partial<NonNullable<Exploration["views"]>[string]>) {
  const state = useExecution.getState();
  if (!state.saved.entry) return;
  const key = viewKey(state.saved.entry, state.saved.entry_path);
  const previous = state.saved.views?.[key] ?? { expanded: {}, positions: {}, camera: null };
  useExecution.setState({ saved: { ...state.saved, views: { ...state.saved.views, [key]: { ...previous, ...patch } } } });
  saveSoon();
}

function currentView() {
  const saved = useExecution.getState().saved;
  return saved.views?.[viewKey(saved.entry ?? "", saved.entry_path)] ?? { expanded: {}, positions: {}, camera: null };
}
function updateStudy(prefix: string, change: (study: FunctionStudy) => FunctionStudy) {
  const state = useExecution.getState();
  const flow = state.functions[prefix];
  if (!flow) return;
  const key = studyKey(flow);
  const previous = state.saved.studies?.[key] ?? { groups: [], dismissed: [], annotations: {} };
  useExecution.setState({ saved: { ...state.saved, studies: { ...state.saved.studies, [key]: change(previous) } } });
  saveSoon();
}

export const useExecution = create<ExecutionState>()((set, get) => ({
  saved: empty(), project: null, entries: [], functions: {}, selected: null, entity: null,
  loading: true, error: null, expanding: null, placing: null,
  async initialize() {
    const epoch = ++generation;
    const startingModeRevision = modeRevision;
    set({ saved: empty(), project: clientProject(), entries: [], functions: {}, selected: null, entity: null,
      loading: true, error: null, expanding: null, placing: null });
    try {
      let [saved, entries] = await Promise.all([api.exploration(), api.entrypoints()]);
      if (epoch !== generation) return;
      if (modeRevision !== startingModeRevision) saved = { ...saved, mode: get().saved.mode };
      set({ saved, entries: entries.items, loading: false });
      const entry = saved.entry ?? entries.items[0]?.id;
      const path = saved.entry ? saved.entry_path ?? undefined : entries.items[0]?.path ?? undefined;
      if (entry && saved.mode === "execution") await get().open(entry, path);
    } catch (error) {
      if (epoch === generation) set({ loading: false, error: String(error) });
    }
  },
  async open(symbol, path) {
    const epoch = ++generation;
    const saved = { ...get().saved, entry: symbol, entry_path: path ?? null };
    set({ saved, loading: true, error: null, selected: null, entity: null, functions: {}, expanding: null, placing: null });
    try {
      const root = await api.execution(symbol, {}, path);
      if (epoch !== generation) return;
      const functions: Record<string, ExecutionFunction> = { root };
      const requested = saved.views?.[viewKey(symbol, path)]?.expanded ?? {};
      const expanded: Record<string, string> = {};
      let failed = false;
      for (const [key, target] of Object.entries(requested).sort((a, b) => a[0].split("/").length - b[0].split("/").length)) {
        const call = locateCall(functions, key);
        if (!call || !(call.candidates ?? []).includes(target)) { failed = true; continue; }
        try { functions[key] = await api.execution(target, call.bindings); expanded[key] = target; }
        catch { failed = true; }
        if (epoch !== generation) return;
      }
      set({ functions, loading: false, error: failed ? "Some saved calls could not be reopened after source changes." : null });
      updateView({ expanded });
    } catch (error) {
      if (epoch === generation) set({ loading: false, error: String(error) });
    }
  },
  async expand(key, symbol) {
    if (get().expanding) return;
    const epoch = generation;
    const call = locateCall(get().functions, key);
    if (!call) return;
    const origin = executionDiagram(get().functions, get().saved, currentView()).nodes.find((n) => n.id === get().selected)?.scope;
    set({ expanding: key, error: null });
    try {
      const flow = get().functions[key]?.symbol === symbol ? get().functions[key] : await api.execution(symbol, call.bindings);
      if (epoch !== generation) return;
      set({ functions: { ...get().functions, [key]: flow }, expanding: null, selected: `${key}/${flow.entry}` });
      const saved = get().saved;
      const old = saved.views?.[viewKey(saved.entry!, saved.entry_path)]?.expanded ?? {};
      const view = currentView();
      const previousOrigin = view.origins?.[key];
      updateView({ expanded: { ...old, [key]: symbol }, origins: { ...view.origins, ...(origin ? { [key]: origin } : {}) },
        positions: origin && previousOrigin && previousOrigin !== origin ? Object.fromEntries(Object.entries(view.positions ?? {}).filter(([id]) => !id.startsWith(key + "/") && !id.startsWith(key + "|"))) : view.positions });
    } catch (error) { if (epoch === generation) set({ expanding: null, error: String(error) }); }
  },
  collapse(key) {
    const keep = (id: string) => id !== key && !id.startsWith(key + "/");
    const functions = Object.fromEntries(Object.entries(get().functions).filter(([id]) => keep(id)));
    set({ functions, selected: null });
    const saved = get().saved;
    const previous = saved.views?.[viewKey(saved.entry!, saved.entry_path)]?.expanded ?? {};
    const view = currentView();
    updateView({ expanded: Object.fromEntries(Object.entries(previous).filter(([id]) => keep(id))),
      origins: Object.fromEntries(Object.entries(view.origins ?? {}).filter(([id]) => keep(id))),
      detached: Object.fromEntries(Object.entries(view.detached ?? {}).filter(([, value]) => keep(value.function))) });
  },
  setMode(mode) {
    ++modeRevision;
    set({ saved: { ...get().saved, mode } }); saveSoon();
    if (mode === "execution" && !get().functions.root) {
      const entry = get().saved.entry ?? get().entries[0]?.id;
      if (entry) void get().open(entry, get().saved.entry_path ?? get().entries[0]?.path ?? undefined);
    }
  },
  select(selected) { set({ selected, entity: null }); },
  inspect(entity) { set({ entity }); },
  pin(id, position) {
    const saved = get().saved;
    const positions = saved.views?.[viewKey(saved.entry!, saved.entry_path)]?.positions ?? {};
    updateView({ positions: { ...positions, [id]: position } });
  },
  camera(camera) { updateView({ camera }); },
  annotate(prefix, key, patch) {
    updateStudy(prefix, (study) => ({ ...study, annotations: { ...study.annotations,
      [key]: { title: "", note: "", status: "unread", color: "", ...study.annotations?.[key], ...patch } } }));
  },
  toggleBlock(prefix, group, detached) {
    const key = blockKey(detached ? `detached:${detached}` : prefix, group);
    const blocks = currentView().blocks ?? [];
    const closing = blocks.includes(key);
    updateView({ blocks: closing ? blocks.filter((id) => id !== key) : [...blocks, key] });
    if (closing) set({ selected: null });
  },
  group(prefix, members, title) {
    if (!title.trim() || members.length < 2) return;
    const flow = get().functions[prefix];
    if (!flow) return;
    const anchors = new Map(flow.nodes.map((n) => [n.id, anchor(n)]));
    const matching = flow.groups?.find((g) => g.members.length === members.length && g.members.every((id) => members.includes(anchors.get(id) ?? "")));
    const id = matching?.id ?? `custom:${crypto.randomUUID()}`;
    if (matching) get().annotate(prefix, id, { title: title.trim() });
    else updateStudy(prefix, (study) => ({ ...study, groups: [...study.groups ?? [], { id, members, title: title.trim() }] }));
    const item = executionDiagram(get().functions, get().saved, currentView()).nodes.find((n) => n.prefix === prefix && n.group?.id === id);
    set({ selected: item?.id ?? null });
  },
  ungroup(prefix, id) {
    updateStudy(prefix, (study) => ({ ...study, groups: (study.groups ?? []).filter((g) => g.id !== id),
      dismissed: [...new Set([...study.dismissed ?? [], id])] }));
    const key = blockKey(prefix, id);
    updateView({ blocks: (currentView().blocks ?? []).filter((b) => b !== key) });
    set({ selected: null });
  },
  place(prefix, group) { set({ placing: { prefix, group } }); },
  cancelPlacement() { set({ placing: null }); },
  attach(position) {
    const placing = get().placing;
    if (!placing) return;
    const id = crypto.randomUUID();
    updateView({ detached: { ...currentView().detached, [id]: { function: placing.prefix, group: placing.group, position } } });
    set({ placing: null, selected: null });
  },
  closeInspector(id) {
    const view = currentView();
    const nodes = new Set(executionDiagram(get().functions, get().saved, view).nodes.filter((n) => n.detached === id).map((n) => n.id));
    updateView({ detached: Object.fromEntries(Object.entries(view.detached ?? {}).filter(([key]) => key !== id)),
      blocks: (view.blocks ?? []).filter((key) => !key.startsWith(`detached:${id}|`)),
      positions: Object.fromEntries(Object.entries(view.positions ?? {}).filter(([key]) => !nodes.has(key))) });
    set({ selected: null });
  },
  moveInspector(id, delta) {
    const view = currentView();
    const inspector = view.detached?.[id];
    if (!inspector) return;
    const nodes = new Set(executionDiagram(get().functions, get().saved, view).nodes.filter((n) => n.detached === id).map((n) => n.id));
    updateView({ detached: { ...view.detached, [id]: { ...inspector, position: { x: inspector.position.x + delta.x, y: inspector.position.y + delta.y } } },
      positions: Object.fromEntries(Object.entries(view.positions ?? {}).map(([key, pos]) => [key,
        nodes.has(key) ? { x: pos.x + delta.x, y: pos.y + delta.y } : pos])) });
  },
  keepPositions(positions) {
    const previous = currentView().positions ?? {};
    const added = Object.fromEntries(Object.entries(positions).filter(([id]) => !previous[id]));
    if (Object.keys(added).length) updateView({ positions: { ...previous, ...added } });
  },
  async flush() {
    if (timer) { clearTimeout(timer); pending?.(); }
    await saves;
  },
}));
