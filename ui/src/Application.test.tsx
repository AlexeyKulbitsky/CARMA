import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { application, type ApplicationState } from "./api/client";
import { Application } from "./Application";

vi.mock("./App", () => ({ App: () => <div>Architecture map</div> }));
vi.mock("./api/client", () => ({
  configureClient: vi.fn(),
  application: { state: vi.fn(), chooseFolder: vi.fn(), inspect: vi.fn(), open: vi.fn(), forget: vi.fn(),
    update: vi.fn(), cancel: vi.fn(), close: vi.fn() },
}));

const project = { id: "engine", name: "Game", path: "C:/Game", available: true, ready: false, opened_at: null };
const initial: ApplicationState = { managed: true, token: "test", active: null, projects: [], job: null, warnings: [] };

beforeEach(() => { vi.resetAllMocks(); vi.mocked(application.state).mockResolvedValue(initial); });
afterEach(cleanup);

describe("project workflow", () => {
  it("picks a new folder and builds its map through a named configuration", async () => {
    vi.mocked(application.chooseFolder).mockResolvedValue({ path: project.path });
    vi.mocked(application.inspect).mockResolvedValue({ project, choices: [
      { id: "automatic", name: "Automatic CMake setup", kind: "cmake", path: ".carma/cache/build", configuration: "Debug" },
    ] });
    vi.mocked(application.open).mockResolvedValue({ ...initial, active: { ...project, ready: true } });
    render(<Application />);
    fireEvent.click(await screen.findByRole("button", { name: "Open project folder…" }));
    const build = await screen.findByRole("button", { name: "Build map" });
    expect(application.open).not.toHaveBeenCalled();
    fireEvent.click(build);
    await waitFor(() => expect(application.open).toHaveBeenCalledWith(project.path, "automatic"));
    expect(await screen.findByText("Architecture map")).toBeTruthy();
  });

  it("opens an existing map without asking to build it again", async () => {
    const saved = { ...project, ready: true };
    vi.mocked(application.state).mockResolvedValue({ ...initial, projects: [saved] });
    vi.mocked(application.inspect).mockResolvedValue({ project: saved, choices: [] });
    vi.mocked(application.open).mockResolvedValue({ ...initial, active: saved, projects: [saved] });
    render(<Application />);
    fireEvent.click(await screen.findByRole("button", { name: "Open" }));
    expect(await screen.findByText("Architecture map")).toBeTruthy();
    expect(application.open).toHaveBeenCalledWith(project.path);
    expect(screen.queryByRole("button", { name: "Build map" })).toBeNull();
  });

  it("does not silently choose between several build configurations", async () => {
    vi.mocked(application.chooseFolder).mockResolvedValue({ path: project.path });
    vi.mocked(application.inspect).mockResolvedValue({ project, choices: ["debug", "release"].map((id) =>
      ({ id, name: id, kind: "preset", path: id, configuration: null })) });
    render(<Application />);
    fireEvent.click(await screen.findByRole("button", { name: "Open project folder…" }));
    const build = await screen.findByRole("button", { name: "Build map" });
    expect((build as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "release" } });
    expect((build as HTMLButtonElement).disabled).toBe(false);
  });

  it("locates a moved project using a folder dialog and replaces its recent entry", async () => {
    const moved = { ...project, id: "old", available: false };
    vi.mocked(application.state).mockResolvedValue({ ...initial, projects: [moved] });
    vi.mocked(application.chooseFolder).mockResolvedValue({ path: "C:/NewGame" });
    const found = { ...project, path: "C:/NewGame", ready: true };
    vi.mocked(application.inspect).mockResolvedValue({ project: found, choices: [] });
    vi.mocked(application.open).mockResolvedValue({ ...initial, active: found, projects: [found] });
    render(<Application />);
    fireEvent.click(await screen.findByRole("button", { name: "Locate folder…" }));
    expect(await screen.findByText("Architecture map")).toBeTruthy();
    expect(application.open).toHaveBeenCalledWith("C:/NewGame", undefined, "old");
  });
});
