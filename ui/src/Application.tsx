import { useEffect, useRef, useState } from "react";

import { App } from "./App";
import { application, configureClient, type ApplicationState, type ProjectInspection } from "./api/client";
import { useMap } from "./store";
import { useExecution } from "./execution/store";

function ErrorMessage({ message }: { message: string }) {
  const [first, ...details] = message.split("\n");
  return <div className="banner banner-error" role="alert">{first}
    {details.some((d) => d.trim()) && <details><summary>Details</summary><pre>{details.join("\n")}</pre></details>}
  </div>;
}

export function Application() {
  const [state, setState] = useState<ApplicationState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [inspection, setInspection] = useState<ProjectInspection | null>(null);
  const [choice, setChoice] = useState("");
  const [relocated, setRelocated] = useState<string | undefined>();
  const [working, setWorking] = useState(false);
  const [revision, setRevision] = useState("");
  const lastReady = useRef("");
  const epoch = useRef(0);
  const current = useRef<ApplicationState | null>(null);

  function accept(next: ApplicationState) {
    configureClient(next);
    current.current = next;
    setState(next);
    if (next.job?.status === "ready" && next.job.id !== lastReady.current) {
      lastReady.current = next.job.id;
      setRevision(next.job.id);
      setInspection(null);
      window.history.replaceState(null, "", window.location.pathname);
    }
  }

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      const generation = ++epoch.current;
      try {
        const next = await application.state();
        if (active && generation === epoch.current) accept(next);
      } catch (e) {
        if (active) setError(`Could not connect to CARMA: ${String(e)}`);
      }
      if (active) timer = setTimeout(poll, current.current?.job?.status === "running" ? 500 : 2000);
    };
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, []);

  async function action(operation: () => Promise<ApplicationState>) {
    ++epoch.current;
    setWorking(true);
    setError(null);
    try { accept(await operation()); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setWorking(false); }
  }

  async function inspectFolder(path?: string, replaceId?: string) {
    setWorking(true);
    setError(null);
    try {
      const folder = path ?? (await application.chooseFolder()).path;
      if (!folder) return;
      const found = await application.inspect(folder);
      setRelocated(replaceId);
      if (found.project.ready) {
        await action(() => replaceId ? application.open(folder, undefined, replaceId) : application.open(folder));
      } else {
        setInspection(found);
        setChoice(found.choices.length === 1 ? found.choices[0].id : "");
      }
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setWorking(false); }
  }

  if (state && !state.managed) return <App />;
  const job = state?.job;
  const busy = working || job?.status === "running";
  const jobError = job?.status === "failed" ? job.error : null;
  const progress = job?.status === "running" && <div className="project-progress" role="status" aria-live="polite">
    <div><strong>{job.stage === "indexing" ? "Building the code map" : "Preparing your project"}</strong>
      <p>{job.message}</p></div>
    <div className="progress-actions">
      {job.total > 0 ? <><progress value={job.done} max={job.total} /> <span>{job.done} / {job.total}</span></> : <progress />}
      <button className="button" disabled={working} onClick={() => void action(application.cancel)}>Cancel</button>
    </div>
  </div>;

  if (state?.active) return <div className="application">
    {(error || jobError) && <ErrorMessage message={error ?? jobError!} />}
    {state.warnings.map((warning) => <div className="banner banner-warning" key={warning}>{warning}</div>)}
    {progress}
    <div className="application-map"><App key={`${state.active.id}:${revision}`} busy={busy}
      onProjects={() => void action(async () => { await Promise.all([useMap.getState().flushWorkspace(), useExecution.getState().flush()]); return application.close(); })}
      onUpdate={() => void action(async () => { await Promise.all([useMap.getState().flushWorkspace(), useExecution.getState().flush()]); return application.update(); })} /></div>
  </div>;

  return <main className="project-home">
    <div className="project-home-inner">
      <header className="project-heading"><span className="project-logo">C</span><div><h1>CARMA</h1><p>Your code, mapped.</p></div></header>
      {(error || jobError) && <ErrorMessage message={error ?? jobError!} />}
      {!state ? <p role="status">Starting CARMA…</p> : <>
        <button className="button primary open-project" disabled={busy} onClick={() => void inspectFolder()}>Open project folder…</button>
        <p className="muted">Choose a codebase to build its map, or reopen a saved project.</p>
        {progress}
        {inspection && <section className="project-setup" aria-labelledby="setup-title">
          <h2 id="setup-title">{inspection.project.name}</h2><p className="project-path">{inspection.project.path}</p>
          {inspection.choices.length ? <>
            <p>CARMA will prepare the project, index the code and create its architecture map.</p>
            <label className="build-choice">Build configuration
              <select value={choice} onChange={(e) => setChoice(e.target.value)} disabled={busy}>
                <option value="" disabled>Choose a configuration…</option>
                {inspection.choices.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </label>
            <button className="button primary" disabled={busy || !choice}
              onClick={() => void action(() => relocated ? application.open(inspection.project.path, choice, relocated)
                : application.open(inspection.project.path, choice))}>Build map</button>
          </> : <p role="status">No supported C++ build settings were found. Select a CMake project or a project with an existing compilation database.</p>}
          <button className="button" disabled={busy} onClick={() => setInspection(null)}>Back</button>
        </section>}
        <section className="recent-projects" aria-labelledby="recent-title"><h2 id="recent-title">Recent projects</h2>
          {!state.projects.length && <p className="muted">Projects you open will appear here.</p>}
          <ul>{state.projects.map((p) => <li key={p.id}>
            <div><strong>{p.name}</strong><p className="project-path">{p.path}</p>
              <span className="muted small">{!p.available ? "Folder moved or unavailable" : p.ready ? "Saved map ready" : "Needs preparation"}</span>
            </div><div className="recent-actions">
              <button className="button" disabled={busy} onClick={() => void inspectFolder(p.available ? p.path : undefined, p.available ? undefined : p.id)}>
                {p.available ? "Open" : "Locate folder…"}</button>
              <button className="link small" disabled={busy} onClick={() => void action(() => application.forget(p.id))}>Remove from list</button>
            </div>
          </li>)}</ul>
        </section>
      </>}
    </div>
  </main>;
}
