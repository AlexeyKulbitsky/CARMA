import { ReactFlowProvider } from "@xyflow/react";
import { useEffect } from "react";

import { API_VERSION, PREFIX } from "./api/client";
import { Graph } from "./graph/Graph";
import { Breadcrumbs, Search, Toolbar } from "./Header";
import { scopeFromHash } from "./nav";
import { SidePanel } from "./panels/SidePanel";
import { useMap } from "./store";

export function App({ onProjects, onUpdate, busy = false }: { onProjects?: () => void; onUpdate?: () => void; busy?: boolean }) {
  const open = useMap((s) => s.open);
  const refresh = useMap((s) => s.refresh);
  const error = useMap((s) => s.error);
  const loading = useMap((s) => s.loading);
  const view = useMap((s) => s.view);
  const status = useMap((s) => s.status);

  useEffect(() => {
    const hostWindow = window as Window & { carmaPrepareClose?: () => Promise<{ ok: boolean; message?: string }> };
    hostWindow.carmaPrepareClose = async () => {
      try { await useMap.getState().flushWorkspace(); return { ok: true }; }
      catch (error) { return { ok: false, message: String(error) }; }
    };
    const onHash = () => void open(scopeFromHash(window.location.hash));
    window.addEventListener("hashchange", onHash);
    void useMap.getState().initialize();
    // The core pushes changes: model files edited by hand or through the API, new facts.
    const events = new EventSource(`${PREFIX}/events`);
    const reload = () => void refresh();
    events.addEventListener("model_changed", reload);
    events.addEventListener("facts_changed", reload);
    return () => {
      delete hostWindow.carmaPrepareClose;
      window.removeEventListener("hashchange", onHash);
      events.close();
      void useMap.getState().flushWorkspace().catch(() => undefined);
    };
  }, [open, refresh]);

  return (
    <ReactFlowProvider>
      <div className="app">
        <button type="button" className="skip-link" onClick={() => document.getElementById("map-details")?.focus()}>
          Skip to map details
        </button>
        <header className="top">
          {onProjects && <button className="button" onClick={onProjects} disabled={busy}>Projects</button>}
          <Breadcrumbs />
          <Search />
          <Toolbar />
          {onUpdate && <button className="button" onClick={onUpdate} disabled={busy}>Update map</button>}
        </header>
        {error && (
          <div className="banner banner-error" role="alert">
            {error}
          </div>
        )}
        {status && status.contracts.api !== API_VERSION && (
          <div className="banner banner-warning" role="status">
            The CARMA service uses a different API version. Restart the application.
          </div>
        )}
        <div className="sr-only" role="status" aria-live="polite">
          {loading ? "Loading map" : view ? `Map level: ${view.trail.at(-1)?.name ?? view.scope}` : ""}
        </div>
        <main className={loading ? "main loading" : "main"}>
          <Graph />
          <SidePanel />
        </main>
      </div>
    </ReactFlowProvider>
  );
}
