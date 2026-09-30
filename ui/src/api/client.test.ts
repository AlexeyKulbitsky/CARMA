import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, apiUrl } from "./client";

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("puts symbol IDs into the query string, encoded", () => {
    const url = apiUrl("/symbols", { id: "cxx golden/render/Renderer#DrawScene()." });
    expect(url).toBe("/api/v0/symbols?id=cxx+golden%2Frender%2FRenderer%23DrawScene%28%29.");
    expect(new URLSearchParams(url.split("?")[1]).get("id")).toBe("cxx golden/render/Renderer#DrawScene().");
    expect(apiUrl("/symbols/search", { q: "a", kind: ["class", "struct"], limit: undefined })).toBe(
      "/api/v0/symbols/search?q=a&kind=class&kind=struct",
    );
  });

  it("turns the error body of the API into an ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ error: { code: "not_found", message: "unknown: nope", details: [] } }), { status: 404 })));
    const failure = api.view("nope");
    await expect(failure).rejects.toBeInstanceOf(ApiError);
    await expect(failure).rejects.toMatchObject({ status: 404, code: "not_found", message: "unknown: nope" });
  });

  it("sends pinned positions as JSON", async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await api.saveLayout("render._self", { a: { x: 1, y: 2 } });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v0/layout/render._self");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual({ positions: { a: { x: 1, y: 2 } } });
  });
});
