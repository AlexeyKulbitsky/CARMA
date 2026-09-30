import { describe, expect, it } from "vitest";

import { elkGraph, layoutKey, withPinned } from "./layout";

const boxes = [
  { id: "a", width: 220, height: 72 },
  { id: "b", width: 220, height: 72 },
];

describe("layout", () => {
  it("keys the cache by the node and edge sets, not by their order", () => {
    const key = layoutKey("root", "components", boxes, [{ source: "a", target: "b" }]);
    expect(layoutKey("root", "components", [...boxes].reverse(), [{ source: "a", target: "b" }])).toBe(key);
    expect(layoutKey("root", "components", boxes, [{ source: "b", target: "a" }])).not.toBe(key);
    expect(layoutKey("root", "symbols", boxes, [{ source: "a", target: "b" }])).not.toBe(key);
    expect(layoutKey("render", "components", boxes, [{ source: "a", target: "b" }])).not.toBe(key);
  });

  it("gives ELK only edges between known, different nodes", () => {
    const graph = elkGraph(boxes, [
      { source: "a", target: "b" },
      { source: "a", target: "a" },
      { source: "a", target: "gone" },
    ]);
    expect(graph.children).toHaveLength(2);
    expect(graph.edges).toEqual([{ id: "e0", sources: ["a"], targets: ["b"] }]);
  });

  it("lets pinned positions win", () => {
    expect(withPinned({ a: { x: 1, y: 1 }, b: { x: 2, y: 2 } }, { b: { x: 9, y: 9 } })).toEqual({
      a: { x: 1, y: 1 },
      b: { x: 9, y: 9 },
    });
  });
});
