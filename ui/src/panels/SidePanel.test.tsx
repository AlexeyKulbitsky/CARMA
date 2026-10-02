import { ReactFlowProvider } from "@xyflow/react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { View, ViewNode } from "../api/client";
import { useMap } from "../store";
import { SidePanel } from "./SidePanel";

const node = (id: string, name: string): ViewNode => ({
  id, name, type: "file", kind: null, lifecycle: null, intent_short: "", symbols: 2,
  children: 0, file: null, issues: [], pos: null, metrics: {}, members: [],
});

const view: View = {
  scope: "root", level: "components", component: "root", trail: [{ scope: "root", name: "root" }],
  nodes: [node("file:alpha", "Alpha"), node("file:beta", "Beta")], boundary: [], grouped_by: null,
  edges: [{ src: "file:alpha", dst: "file:beta", refs: 3, calls: 1, uses: 2, declared: true, issues: [], metrics: {} }],
};

beforeEach(() => useMap.setState({ view, selection: null, metric: "refs", threshold: 1 }));

describe("map details", () => {
  it("provides a keyboard reachable list of nodes and connections, and returns to the overview", async () => {
    render(<ReactFlowProvider><SidePanel /></ReactFlowProvider>);
    fireEvent.click(screen.getByText("Browse map: 2 nodes, 1 connection"));
    expect(screen.getByRole("button", { name: "Alpha → Beta" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Alpha" }));
    expect(screen.getByRole("heading", { name: "Alpha" })).toBeTruthy();
    await waitFor(() => expect(document.activeElement?.id).toBe("selection-details"));
    fireEvent.click(screen.getByRole("button", { name: "Level overview" }));
    expect(screen.getByRole("heading", { name: "root" })).toBeTruthy();
  });
});
