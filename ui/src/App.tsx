import { ReactFlowProvider } from "@xyflow/react";
import { useEffect } from "react";

import { API_VERSION, PREFIX } from "./api/client";
import { Graph } from "./graph/Graph";
import { Breadcrumbs, Search, Toolbar } from "./Header";
import { scopeFromHash } from "./nav";
import { SidePanel } from "./panels/SidePanel";
import { useMap } from "./store";

export function App() {
  const open = useMap((s) => s.open);
  const refresh = useMap((s) => s.refresh);
  const error = useMap((s) => s.error);
  const loading = useMap((s) => s.loading);
  const view = useMap((s) => s.view);
  const status = useMap((s) => s.status);

  useEffect(() => {
    const onHash = () => void open(scopeFromHash(window.location.hash));
    window.addEventListener("hashchange", onHash);
    useMap.setState({ scope: scopeFromHash(window.location.hash) });
    void refresh();
    // The core pushes changes: model files edited by hand or through the API, new facts.
    const events = new EventSource(`${PREFIX}/events`);
    const reload = () => void refresh();
    events.addEventListener("model_changed", reload);
    events.addEventListener("facts_changed", reload);
    return () => {
      window.removeEventListener("hashchange", onHash);
      events.close();
    };
  }, [open, refresh]);

  return (
    <ReactFlowProvider>
      <div className="app">
        <button type="button" className="skip-link" onClick={() => document.getElementById("map-details")?.focus()}>
          Skip to map details
        </button>
        <header className="top">
          <Breadcrumbs />
          <Search />
          <Toolbar />
        </header>
        {error && (
          <div className="banner banner-error" role="alert">
            {error}
          </div>
        )}
        {status && status.contracts.api !== API_VERSION && (
          <div className="banner banner-warning" role="status">
            The CARMA server uses an older API. Restart carma serve to show class fields and methods.
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
