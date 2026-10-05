import { describe, expect, it } from "vitest";
import type { ExecutionFunction } from "../api/client";
import { executionDiagram, executionPositions } from "./diagram";
import { groupSelection, groupVisibleSteps, studyBlocks, studyKey } from "./study";
import type { Exploration, ExplorationView } from "../api/client";
import { callKey, locateCall } from "./store";

const defaults = { anchor: "", calls: [], effects: [], objects: [], note: "" };
const flow = (symbol: string): ExecutionFunction => ({ schema_version: "execution/0.2", groups: [], parameters: [], objects: [], warnings: [], symbol, name: symbol, path: "main.cpp", line: 1,
  entry: "start", exit: "end", nodes: [
    { ...defaults, id: "start", kind: "entry", label: "start", code: "", path: "main.cpp", line: 1, end_line: 1 },
    { ...defaults, id: "call", kind: "action", label: "Init", code: "Init()", path: "main.cpp", line: 2, end_line: 2,
      calls: [{ symbol: "init", name: "Init", candidates: ["init"], expandable: ["init"], bindings: {},
        arguments: [], virtual: false, resolution: "direct", explanation: "", assignments: [] }] },
    { ...defaults, id: "end", kind: "exit", label: "end", code: "", path: "main.cpp", line: 3, end_line: 3 },
  ], edges: [{ source: "start", target: "call", label: "" }, { source: "call", target: "end", label: "" }] });

describe("execution diagrams", () => {
  it("keeps separate call sites and connects expanded bodies as details", () => {
    const key = callKey("root", "call", 0);
    const functions = { root: flow("main"), [key]: flow("init") };
    const diagram = executionDiagram(functions);
    expect(new Set(diagram.nodes.map((n) => n.id)).size).toBe(6);
    expect(diagram.edges.find((e) => e.detail)).toMatchObject({ source: "root/call", target: `${key}/start` });
    expect(diagram.edges.some((e) => e.source === "root/call" && e.target === "root/end" && !e.detail)).toBe(true);
    expect(locateCall(functions, key)?.symbol).toBe("init");
  });
  it("opens details strictly right without changing main positions", () => {
    const root = flow("main"), init = flow("init"), key = callKey("root", "call", 0);
    const before = executionPositions(executionDiagram({ root }));
    const after = executionPositions(executionDiagram({ root, [key]: init }));
    Object.keys(before).forEach((id) => expect(after[id]).toEqual(before[id]));
    expect(after[`${key}/start`].y).toBe(after["root/call"].y);
    expect(after[`${key}/start`].x).toBeGreaterThan(after["root/call"].x);
  });
  it("preserves early-return exits when projecting and opening a group", () => {
    const root = flow("main");
    root.nodes.splice(2, 0, { ...root.nodes[1], id: "failure", kind: "return", label: "return false", code: "return false" });
    root.edges.push({ source: "call", target: "failure", label: "false" }, { source: "failure", target: "end", label: "return" });
    root.groups = [{ id: "guard", label: "Initialize", members: ["call", "failure"], origin: "comment" }];
    const view: ExplorationView = { expanded: {}, positions: {}, blocks: ["root|guard"] };
    const diagram = executionDiagram({ root }, undefined, view);
    expect(diagram.nodes.filter((n) => n.scope === "root")).toHaveLength(3);
    expect(diagram.edges).toContainEqual(expect.objectContaining({ source: "root/guard", target: "root/end", label: "return false", detail: false }));
    expect(diagram.edges).toContainEqual(expect.objectContaining({ source: "root|guard/failure", target: "root/end", label: "return", detail: false }));
    const positions = executionPositions(diagram, view);
    expect(positions["root|guard/call"].y).toBe(positions["root/guard"].y);
  });
  it("shares notes across separate views while retaining independent disclosure", () => {
    const root = flow("main");
    root.groups = [{ id: "group", label: "Setup", members: ["call", "end"], origin: "comment" }];
    const saved: Exploration = { schema_version: "exploration/0.2", mode: "execution", studies: { [studyKey(root)]: { annotations: {
      group: { title: "GLFW Init", note: "Window context", status: "understood", color: "#438a60" } } } } };
    const view: ExplorationView = { expanded: {}, positions: {}, detached: { one: { function: "root", group: null, position: { x: 2000, y: 600 } } }, blocks: ["detached:one|group"] };
    const diagram = executionDiagram({ root }, saved, view);
    const summaries = diagram.nodes.filter((n) => n.group?.id === "group");
    expect(summaries).toHaveLength(2);
    expect(summaries[0].annotation).toEqual(summaries[1].annotation);
    expect(diagram.scopes.some((s) => s.id === "root|group")).toBe(false);
    expect(diagram.scopes.some((s) => s.id === "detached:one|group")).toBe(true);
    expect(executionPositions(diagram, view)["detached:one/start"]).toEqual({ x: 2000, y: 600 });
  });
  it("retains unbound knowledge after source edits", () => {
    const root = flow("main");
    const knowledge = studyBlocks(root, { groups: [{ id: "custom", title: "Old setup", members: ["old1", "old2"] }],
      annotations: { old1: { title: "", color: "", note: "Still needed", status: "question" } } });
    expect(knowledge.stale).toEqual(["Old setup"]);
    expect(knowledge.unbound).toEqual(["old1"]);
    expect(knowledge.blocks).toHaveLength(0);
  });
  it("rejects disjoint selection and scopes with multiple entrances", () => {
    const root = flow("main");
    expect(groupSelection(root, [["a"], ["b"], ["c"]], [0, 2]).error).toBeTruthy();
    root.edges = [{ source: "start", target: "a", label: "" }, { source: "start", target: "b", label: "" }];
    expect(groupSelection(root, [["a"], ["b"]], [0, 1]).error).toContain("control-flow");
  });
  it("uses canvas-selected consecutive steps for the same safe grouping rule", () => {
    const root = flow("main");
    root.nodes.splice(2, 0, { ...root.nodes[1], id: "middle", label: "Configure", code: "Configure()" },
      { ...root.nodes[1], id: "last", label: "Start", code: "Start()" });
    root.edges = [{ source: "start", target: "call", label: "" }, { source: "call", target: "middle", label: "" },
      { source: "middle", target: "last", label: "" }, { source: "last", target: "end", label: "" }];
    const items = executionDiagram({ root }).nodes;
    expect(groupVisibleSteps(root, items, ["root/call", "root/middle"]).members).toEqual(["call", "middle"]);
    expect(groupVisibleSteps(root, items, ["root/call", "root/last"]).error).toContain("consecutive");
  });
  it("folds nested call details with their scope and opens calls inside separate views", () => {
    const root = flow("main"), init = flow("init"), key = callKey("root", "call", 0);
    root.nodes.splice(2, 0, { ...root.nodes[1], id: "other", label: "Other", code: "Other()" });
    root.groups = [{ id: "phase", label: "Setup", members: ["call", "other"], origin: "comment" }];
    const folded = executionDiagram({ root, [key]: init }, undefined, { expanded: { [key]: "init" }, positions: {}, origins: { [key]: "root|phase" } });
    expect(folded.scopes.some((s) => s.id === key)).toBe(false);
    const opened = executionDiagram({ root, [key]: init }, undefined, { expanded: {}, positions: {}, origins: { [key]: "root|phase" }, blocks: ["root|phase"] });
    expect(opened.scopes.some((s) => s.id === key)).toBe(true);
    const detached = executionDiagram({ root, [key]: init }, undefined, { expanded: {}, positions: {}, origins: { [key]: "detached:one" },
      detached: { one: { function: "root", group: "phase", position: { x: 1500, y: 100 } } } });
    expect(detached.scopes.find((s) => s.id === key)).toMatchObject({ source: "detached:one/call", detached: "one" });
    expect(detached.nodes.filter((n) => n.scope === key).every((n) => n.detached === "one")).toBe(true);
  });
});
