import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ComponentTree } from "./api/client";
import { Search, Toolbar } from "./Header";
import { useMap } from "./store";

beforeEach(() => {
  useMap.setState({
    tree: { parent: "root", unassigned: 0, components: [
      { id: "render", name: "Render", kind: "subsystem", lifecycle: "current", symbols: 0, own_symbols: 0, issues: [], children: [] },
      { id: "rendering", name: "Rendering", kind: "subsystem", lifecycle: "current", symbols: 0, own_symbols: 0, issues: [], children: [] },
    ] } satisfies ComponentTree,
    navigate: vi.fn(),
    metric: "refs",
    threshold: 1,
    view: null,
  });
});

describe("map controls", () => {
  it("navigates search results with arrows and Enter", () => {
    render(<Search />);
    const input = screen.getByRole("combobox", { name: "Search components and symbols" });
    fireEvent.change(input, { target: { value: "render" } });
    expect(input.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getAllByRole("option")).toHaveLength(2);
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input.getAttribute("aria-activedescendant")).toBe("search-result-1");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(useMap.getState().navigate).toHaveBeenCalledWith("root", { kind: "node", id: "rendering", reveal: true });
    expect(input.getAttribute("aria-expanded")).toBe("false");
  });

  it("exposes metric selection and the slider value", () => {
    render(<Toolbar />);
    const calls = screen.getByRole("button", { name: "calls" });
    expect(calls.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(calls);
    expect(calls.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("slider", { name: "Minimum calls per connection" })).toBeTruthy();
  });
});
