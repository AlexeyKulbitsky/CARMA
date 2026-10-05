import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ExecutionFunction, Exploration } from "../api/client";
import { api } from "../api/client";
import { useExecution, viewKey } from "./store";

vi.mock("../api/client", () => ({ clientProject: () => "project-a", api: {
  exploration: vi.fn(), entrypoints: vi.fn(), execution: vi.fn(), saveExploration: vi.fn(),
} }));

const defaults = { anchor: "", calls: [], effects: [], objects: [], note: "" };
const main: ExecutionFunction = { schema_version: "execution/0.2", groups: [], parameters: [], objects: [], warnings: [], symbol: "main", name: "main", path: "main.cpp", line: 1, entry: "entry", exit: "exit",
  nodes: [{ ...defaults, id: "entry", kind: "entry", label: "main", code: "", path: "main.cpp", line: 1, end_line: 1 },
    { ...defaults, id: "call", kind: "action", label: "Init", code: "Init()", path: "main.cpp", line: 2, end_line: 2,
      calls: [{ symbol: "init", name: "Init", candidates: ["init"], expandable: ["init"], bindings: { this: "Engine" },
        arguments: [], virtual: false, resolution: "direct", explanation: "", assignments: [] }] },
    { ...defaults, id: "exit", kind: "exit", label: "exit", code: "", path: "main.cpp", line: 3, end_line: 3 }], edges: [] };
const init: ExecutionFunction = { ...main, symbol: "init", name: "Init", nodes: main.nodes.filter((n) => n.id !== "call") };

beforeEach(async () => {
  await useExecution.getState().flush();
  vi.resetAllMocks();
  vi.mocked(api.saveExploration).mockResolvedValue({ views: {}, mode: "execution", schema_version: "exploration/0.2" });
  vi.mocked(api.entrypoints).mockResolvedValue({ items: [{ id: "main", name: "main", kind: "function", path: "main.cpp",
    line: 1, signature: "int main()", component: null, external: false }], more: false });
  vi.mocked(api.execution).mockImplementation(async (id) => id === "main" ? main : init);
});

describe("saved execution exploration", () => {
  it("keeps a mode chosen while saved settings are still loading", async () => {
    let resolve!: (saved: Exploration) => void;
    vi.mocked(api.exploration).mockReturnValue(new Promise((r) => { resolve = r; }));
    const pending = useExecution.getState().initialize();
    useExecution.getState().setMode("architecture");
    resolve({ schema_version: "exploration/0.2", mode: "execution", entry: null, views: {} });
    await pending;
    expect(useExecution.getState().saved.mode).toBe("architecture");
    expect(api.execution).not.toHaveBeenCalled();
    await useExecution.getState().flush();
  });
  it("opens the suggested entry and flushes the last expansion and position to the originating project", async () => {
    vi.mocked(api.exploration).mockResolvedValue({ schema_version: "exploration/0.2", mode: "execution", entry: null, views: {} });
    await useExecution.getState().initialize();
    await useExecution.getState().expand("root/call@0", "init");
    useExecution.getState().pin("root/call", { x: 20, y: 40 });
    await useExecution.getState().flush();
    const [saved, project] = vi.mocked(api.saveExploration).mock.calls.at(-1)!;
    expect(project).toBe("project-a");
    expect(saved.views?.[viewKey("main", "main.cpp")]).toMatchObject({ expanded: { "root/call@0": "init" }, positions: { "root/call": { x: 20, y: 40 } } });
    expect(api.execution).toHaveBeenLastCalledWith("init", { this: "Engine" });
  });
  it("reopens saved calls in parent order and preserves the camera", async () => {
    const saved: Exploration = { schema_version: "exploration/0.2", mode: "execution", entry: "main", entry_path: "main.cpp", views: {
      [viewKey("main", "main.cpp")]: { expanded: { "root/call@0": "init" }, positions: {}, camera: { x: 4, y: 8, zoom: .6 } },
    } };
    vi.mocked(api.exploration).mockResolvedValue(saved);
    await useExecution.getState().initialize();
    expect(useExecution.getState().functions["root/call@0"].name).toBe("Init");
    expect(useExecution.getState().saved.views?.[viewKey("main", "main.cpp")]?.camera).toEqual({ x: 4, y: 8, zoom: .6 });
    useExecution.getState().collapse("root/call@0");
    expect(Object.keys(useExecution.getState().functions)).toEqual(["root"]);
    await useExecution.getState().flush();
  });
  it("persists knowledge and a detached block through closing and reopening", async () => {
    vi.mocked(api.exploration).mockResolvedValue({ schema_version: "exploration/0.2", mode: "execution", entry: null, views: {} });
    await useExecution.getState().initialize();
    useExecution.getState().group("root", ["a", "b"], "GLFW Init");
    const id = useExecution.getState().saved.studies!["main@main.cpp"].groups![0].id;
    useExecution.getState().annotate("root", id, { note: "Window setup", status: "understood", color: "#438a60" });
    useExecution.getState().toggleBlock("root", id);
    useExecution.getState().place("root", id);
    useExecution.getState().attach({ x: 1200, y: 600 });
    await useExecution.getState().flush();
    const saved = vi.mocked(api.saveExploration).mock.calls.at(-1)![0];
    vi.mocked(api.exploration).mockResolvedValue(saved);
    await useExecution.getState().initialize();
    expect(useExecution.getState().saved.studies!["main@main.cpp"].annotations![id]).toMatchObject({ note: "Window setup", status: "understood" });
    const view = useExecution.getState().saved.views![viewKey("main", "main.cpp")];
    expect(view.blocks).toContain(`root|${id}`);
    const inspector = Object.keys(view.detached!)[0];
    useExecution.getState().moveInspector(inspector, { x: 20, y: 30 });
    expect(useExecution.getState().saved.views![viewKey("main", "main.cpp")].detached![inspector].position).toEqual({ x: 1220, y: 630 });
    useExecution.getState().closeInspector(inspector);
    expect(useExecution.getState().saved.studies!["main@main.cpp"].annotations![id].note).toBe("Window setup");
    await useExecution.getState().flush();
  });
  it("moves the entire separate area including its nested function details", async () => {
    vi.mocked(api.exploration).mockResolvedValue({ schema_version: "exploration/0.2", mode: "execution", entry: null, views: {} });
    await useExecution.getState().initialize();
    useExecution.getState().place("root", null);
    useExecution.getState().attach({ x: 1500, y: 500 });
    const id = Object.keys(useExecution.getState().saved.views![viewKey("main", "main.cpp")].detached!)[0];
    useExecution.getState().select(`detached:${id}/call`);
    await useExecution.getState().expand("root/call@0", "init");
    useExecution.getState().keepPositions({ [`detached:${id}/entry`]: { x: 1500, y: 500 }, "root/call@0/entry": { x: 1960, y: 680 }, "root/entry": { x: 60, y: 60 } });
    useExecution.getState().moveInspector(id, { x: 100, y: 50 });
    const view = useExecution.getState().saved.views![viewKey("main", "main.cpp")];
    expect(view.positions!["root/call@0/entry"]).toEqual({ x: 2060, y: 730 });
    expect(view.positions!["root/entry"]).toEqual({ x: 60, y: 60 });
    useExecution.getState().closeInspector(id);
    expect(useExecution.getState().saved.views![viewKey("main", "main.cpp")].positions!["root/call@0/entry"]).toBeUndefined();
    await useExecution.getState().flush();
  });
});
