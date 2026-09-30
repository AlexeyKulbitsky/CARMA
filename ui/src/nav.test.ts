import { describe, expect, it } from "vitest";

import { crumbLabel, drillScope, flattenTree, hashForScope, scopeFromHash } from "./nav";

describe("nav", () => {
  it("round-trips scopes through the URL hash", () => {
    for (const scope of ["root", "render", "render._self", "_unassigned", "scene.components"]) {
      expect(scopeFromHash(hashForScope(scope))).toBe(scope);
    }
    expect(scopeFromHash("")).toBe("root");
    expect(scopeFromHash("#")).toBe("root");
  });

  it("labels breadcrumbs", () => {
    expect(crumbLabel({ scope: "root", name: "root" }, "gd-engine")).toBe("gd-engine");
    expect(crumbLabel({ scope: "render._self", name: "Render" }, "x")).toBe("own symbols of Render");
    expect(crumbLabel({ scope: "render", name: "Render" }, "x")).toBe("Render");
  });

  it("knows which nodes open a level", () => {
    expect(drillScope("render", "component")).toBe("render");
    expect(drillScope("render._self", "self")).toBe("render._self");
    expect(drillScope("_unassigned", "unassigned")).toBe("_unassigned");
    expect(drillScope("cxx a/B#", "symbol")).toBeNull();
    expect(drillScope("file:src/a.h", "file")).toBeNull();
  });

  it("flattens the component tree with the level that shows each component", () => {
    const leaf = { id: "render.backend", name: "Backend", kind: "component" as const, lifecycle: "current" as const,
      symbols: 1, own_symbols: 1, issues: [], children: [] };
    const tree = [{ ...leaf, id: "render", name: "Render", kind: "subsystem" as const, children: [leaf] }];
    expect(flattenTree(tree).map((c) => [c.id, c.parent])).toEqual([["render", "root"], ["render.backend", "render"]]);
  });
});
