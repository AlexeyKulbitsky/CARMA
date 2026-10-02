import { fireEvent, render, screen } from "@testing-library/react";
import { ReactFlowProvider } from "@xyflow/react";
import { describe, expect, it, vi } from "vitest";

import type { ViewNode } from "../api/client";
import { useMap } from "../store";
import { cardHeight, cardMeta, cardWidth, NodeCard } from "./NodeCard";

const node = (extra: Partial<ViewNode>): ViewNode => ({
  id: "render", name: "Render", type: "component", kind: "subsystem", lifecycle: "current", intent_short: "",
  symbols: 24, children: 1, file: null, issues: [], pos: null, metrics: {}, ...extra, members: extra.members ?? [],
});

function show(n: ViewNode, boundary = false, selected = false) {
  const props = { id: n.id, data: { node: n, boundary }, selected, type: "card" as const, dragging: false, zIndex: 0,
    isConnectable: false, positionAbsoluteX: 0, positionAbsoluteY: 0, selectable: true, deletable: false, draggable: true };
  return render(
    <ReactFlowProvider>
      <NodeCard {...props} />
    </ReactFlowProvider>,
  );
}

describe("NodeCard", () => {
  it("shows a component with its counts, intent and issues", () => {
    const { container } = show(node({ intent_short: "Draws the scene.", issues: ["stale", "empty"] }));
    expect(screen.getByText("Render")).toBeTruthy();
    expect(screen.getByText("subsystem · 24 symbols · 1 inside")).toBeTruthy();
    expect(screen.getByText("Draws the scene.")).toBeTruthy();
    expect([...container.querySelectorAll(".badge-issue")].map((b) => b.textContent)).toEqual(["stale", "empty"]);
  });

  it("labels the own symbols of a parent and marks planned, boundary and selected nodes", () => {
    const { container } = show(node({ id: "render._self", type: "self", lifecycle: "planned" }), true, true);
    expect(screen.getByText("own symbols of Render")).toBeTruthy();
    const card = container.querySelector(".card")!;
    expect(card.className).toContain("card-planned");
    expect(card.className).toContain("card-boundary");
    expect(card.className).toContain("card-focused");
    expect(screen.getByText("planned")).toBeTruthy();
  });

  it("describes symbol nodes by kind and file", () => {
    expect(cardMeta(node({ type: "symbol", kind: "class", file: "src/render/Renderer.h" }))).toBe("class · Renderer.h");
    expect(cardMeta(node({ type: "file", symbols: 1 }))).toBe("file · 1 symbol");
  });

  it("shows class fields and methods inside the block and opens the selected member", () => {
    const showSymbol = vi.fn();
    useMap.setState({ showSymbol });
    const klass = node({ id: "cxx Renderer#", name: "Renderer", type: "symbol", kind: "class", members: [
      { id: "cxx Renderer#m_items.", name: "m_items", kind: "field", signature: "Items m_items", access: "private" },
      { id: "cxx Renderer#Draw().", name: "Draw", kind: "method", signature: "void Draw()", access: "public" },
    ] });
    show(klass);
    expect(screen.getByText("Fields")).toBeTruthy();
    expect(screen.getByText("Methods")).toBeTruthy();
    expect(screen.getByText("Items m_items")).toBeTruthy();
    expect(screen.getByText("void Draw()")).toBeTruthy();
    expect(cardWidth(klass)).toBe(300);
    expect(cardHeight(klass)).toBeGreaterThan(58);
    fireEvent.click(screen.getByRole("button", { name: "public method void Draw()" }));
    expect(showSymbol).toHaveBeenCalledWith("cxx Renderer#Draw().");
  });
});
