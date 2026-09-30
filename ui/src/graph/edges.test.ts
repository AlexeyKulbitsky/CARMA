import { describe, expect, it } from "vitest";

import type { ViewEdge } from "../api/client";
import { cycleGroups, edgeTone, edgeWidth, MAX_WIDTH, maxMetric, visibleEdges } from "./edges";

const edge = (src: string, dst: string, refs: number, extra: Partial<ViewEdge> = {}): ViewEdge => ({
  src, dst, refs, calls: 0, uses: refs, declared: false, issues: [], metrics: {}, ...extra,
});

describe("edges", () => {
  it("scales width from 1 to MAX_WIDTH by the square root of the metric", () => {
    expect(edgeWidth(0, 10)).toBe(1);
    expect(edgeWidth(10, 10)).toBe(MAX_WIDTH);
    expect(edgeWidth(1, 100)).toBeLessThan(edgeWidth(25, 100));
    expect(edgeWidth(500, 100)).toBe(MAX_WIDTH);
  });

  it("hides edges under the threshold, with no value of the metric, or away from the focused node", () => {
    const edges = [edge("a", "b", 5), edge("b", "c", 1), edge("c", "a", 3, { uses: 0 })];
    expect(visibleEdges(edges, "refs", 3, null).map((e) => e.src)).toEqual(["a", "c"]);
    expect(visibleEdges(edges, "calls", 1, null)).toEqual([]);
    expect(visibleEdges(edges, "uses", 1, null).map((e) => e.src)).toEqual(["a", "b"]);
    expect(visibleEdges(edges, "refs", 1, "b").map((e) => `${e.src}${e.dst}`)).toEqual(["ab", "bc"]);
    expect(maxMetric(edges, "refs")).toBe(5);
  });

  it("colors by the most serious issue", () => {
    expect(edgeTone(edge("a", "b", 1, { issues: ["undeclared_dependency", "cycle"] }))).toBe("undeclared");
    expect(edgeTone(edge("a", "b", 1, { issues: ["cycle"], declared: true }))).toBe("cycle");
    expect(edgeTone(edge("a", "b", 1, { declared: true }))).toBe("declared");
    expect(edgeTone(edge("a", "b", 1))).toBe("plain");
  });

  it("groups cycle edges into one entry per cycle", () => {
    const edges = [
      edge("render", "streaming", 1, { issues: ["cycle"] }),
      edge("streaming", "render", 1, { issues: ["undeclared_dependency", "cycle"] }),
      edge("audio", "core", 1, { issues: ["cycle"] }),
      edge("core", "audio", 1, { issues: ["cycle"] }),
      edge("core", "math", 1),
    ];
    expect(cycleGroups(edges)).toEqual([["audio", "core"], ["render", "streaming"]]);
  });
});
