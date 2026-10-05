// The View API (contract 4). Types come from contracts/openapi.yaml: npm run gen:api.
import type { components } from "./schema";

type Schemas = components["schemas"];
export type Status = Schemas["Status"];
export type View = Schemas["View"];
export type ViewNode = Schemas["ViewNode"];
export type ViewMember = Schemas["ViewMember"];
export type ViewEdge = Schemas["ViewEdge"];
export type Crumb = Schemas["Crumb"];
export type ComponentTree = Schemas["ComponentTree"];
export type TreeNode = Schemas["TreeNode"];
export type ComponentCard = Schemas["ComponentCard"];
export type SymbolList = Schemas["SymbolList"];
export type SymbolBrief = Schemas["SymbolBrief"];
export type SymbolCard = Schemas["SymbolCard"];
export type CallList = Schemas["CallList"];
export type RefList = Schemas["RefList"];
export type Position = Schemas["Position"];
export type Workspace = Schemas["Workspace"];
export type Camera = Schemas["Camera"];
export type ApplicationState = Schemas["ApplicationState"];
export type ProjectInspection = Schemas["ProjectInspection"];
export type CachedLayout = Schemas["CachedLayout"];
export type ExecutionFunction = Schemas["ExecutionFunction"];
export type ExecutionNode = Schemas["ExecutionNode"];
export type ExecutionCall = Schemas["ExecutionCall"];
export type ExecutionEntity = Schemas["ExecutionEntity"];
export type Exploration = Schemas["Exploration"];
export type ExplorationView = Schemas["ExplorationView"];
export type FunctionStudy = Schemas["FunctionStudy"];
export type StudyAnnotation = Schemas["StudyAnnotation"];

export const PREFIX = "/api/v0";
export const API_VERSION = "api/0.5";

let token: string | null = null;
let project: string | null = null;
export function configureClient(state: ApplicationState): void {
  token = state.token ?? null;
  project = state.active?.id ?? null;
}
export function clientProject(): string | null { return project; }

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

type Params = Record<string, string | number | string[] | undefined>;

/** Symbol IDs contain spaces, '/' and '#': they always go into the query string, encoded. */
export function apiUrl(path: string, params: Params = {}): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) continue;
    for (const item of Array.isArray(value) ? value : [value]) query.append(key, String(item));
  }
  const text = query.toString();
  return PREFIX + path + (text ? `?${text}` : "");
}

async function request<T>(method: string, path: string, params?: Params, body?: unknown,
                          expectedProject: string | null = project): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers["X-Carma-Token"] = token;
  if (expectedProject) headers["X-Carma-Project"] = expectedProject;
  const response = await fetch(apiUrl(path, params), {
    method,
    headers: Object.keys(headers).length ? headers : undefined,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let code = "http_error";
    let message = response.statusText;
    try {
      const data = await response.json();
      code = data.error?.code ?? code;
      message = data.error?.message ?? message;
    } catch {
      // not a JSON error body
    }
    throw new ApiError(response.status, code, message);
  }
  return (await response.json()) as T;
}

export const api = {
  entrypoints: () => request<SymbolList>("GET", "/execution/entrypoints"),
  execution: (symbol: string, bindings: Record<string, string> = {}, path?: string) =>
    request<ExecutionFunction>("POST", "/execution/view", undefined, { symbol, bindings, path }),
  entity: (id: string) => request<ExecutionEntity>("GET", "/execution/entity", { id }),
  exploration: () => request<Exploration>("GET", "/exploration"),
  saveExploration: (state: Exploration, expected: string | null) =>
    request<Exploration>("PUT", "/exploration", undefined, state, expected),
  status: () => request<Status>("GET", "/status"),
  view: (scope: string) => request<View>("GET", "/view", { scope }),
  components: (parent = "root") => request<ComponentTree>("GET", "/components", { parent }),
  component: (id: string) => request<ComponentCard>("GET", `/components/${encodeURIComponent(id)}`),
  search: (q: string, limit = 12) => request<SymbolList>("GET", "/symbols/search", { q, limit }),
  symbol: (id: string) => request<SymbolCard>("GET", "/symbols", { id }),
  callers: (id: string) => request<CallList>("GET", "/symbols/callers", { id, limit: 100 }),
  callees: (id: string) => request<CallList>("GET", "/symbols/callees", { id, limit: 100 }),
  samples: (scope: string, src: string, dst: string) =>
    request<RefList>("GET", "/edges/samples", { scope, src, dst, limit: 50 }),
  saveLayout: (scope: string, positions: Record<string, Position>) =>
    request<unknown>("PUT", `/layout/${encodeURIComponent(scope)}`, undefined, { positions }),
  workspace: () => request<Workspace>("GET", "/workspace"),
  saveWorkspace: (workspace: Workspace, expected: string | null) =>
    request<Workspace>("PUT", "/workspace", undefined, workspace, expected),
  cachedLayout: (key: string, expected: string | null) =>
    request<CachedLayout>("GET", `/layout-cache/${key}`, undefined, undefined, expected),
  cacheLayout: (layout: CachedLayout, expected: string | null) =>
    request<CachedLayout>("PUT", `/layout-cache/${layout.key}`, undefined, layout, expected),
};

export const application = {
  state: () => request<ApplicationState>("GET", "/app/state"),
  chooseFolder: () => request<Schemas["FolderChoice"]>("POST", "/app/pick-folder"),
  inspect: (path: string) => request<ProjectInspection>("POST", "/app/inspect", undefined, { path }),
  open: (path: string, build_id?: string, replace_id?: string) =>
    request<ApplicationState>("POST", "/app/open", undefined, { path, build_id, replace_id }),
  update: () => request<ApplicationState>("POST", "/app/reindex"),
  cancel: () => request<ApplicationState>("POST", "/app/cancel"),
  close: () => request<ApplicationState>("POST", "/app/close"),
  forget: (id: string) => request<ApplicationState>("POST", "/app/forget", undefined, { id }),
};
