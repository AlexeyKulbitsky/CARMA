import { afterEach, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ThemeControl } from "./ThemeControl";
import { applyTheme } from "./theme";

afterEach(() => { applyTheme("system"); localStorage.clear(); });

it("keeps a manual theme across a new control and restores system mode", () => {
  const first = render(<ThemeControl />);
  fireEvent.change(screen.getByRole("combobox", { name: "Color theme" }), { target: { value: "dark" } });
  expect(document.documentElement.dataset.theme).toBe("dark");
  first.unmount();
  render(<ThemeControl />);
  expect((screen.getByRole("combobox", { name: "Color theme" }) as HTMLSelectElement).value).toBe("dark");
  fireEvent.change(screen.getByRole("combobox", { name: "Color theme" }), { target: { value: "system" } });
  expect(document.documentElement.dataset.theme).toBeUndefined();
});
