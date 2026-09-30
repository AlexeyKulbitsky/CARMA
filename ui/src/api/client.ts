// The View API (contract 4). Types come from contracts/openapi.yaml: npm run gen:api.
import type { components } from "./schema";

type Schemas = components["schemas"];
export type Status = Schemas["Status"];
export type View = Schemas["View"];
export type ViewNode = Schemas["ViewNode"];
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

export const PREFIX = "/api/v0";

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

async function request<T>(method: string, path: string, params?: Params, body?: unknown): Promise<T> {
  const response = await fetch(apiUrl(path, params), {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
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
};
