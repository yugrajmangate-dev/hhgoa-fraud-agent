import { useCallback, useEffect, useState } from "react";
import type { CaseBundle, IndexRow } from "./types";
import { loadCase, loadIndex } from "./lib/data";
import { CaseQueue } from "./components/CaseQueue";
import { WorkspaceHeader } from "./components/WorkspaceHeader";
import { CaseGraph } from "./components/CaseGraph";
import { Timeline } from "./components/Timeline";
import { DecisionComparison } from "./components/DecisionComparison";
import { Copilot } from "./components/Copilot";
import { ErrorState, Skeleton } from "./components/ui";

const DEFAULT_CASE = "HHG-017";

function caseFromHash(): string | null {
  const m = /^#?(HHG-\d{3})$/.exec(window.location.hash);
  return m ? m[1] : null;
}

type CaseState = { status: "loading" } | { status: "ready"; bundle: CaseBundle } | { status: "error"; message: string };

export default function App() {
  const [index, setIndex] = useState<IndexRow[] | null>(null);
  const [indexError, setIndexError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string>(caseFromHash() ?? DEFAULT_CASE);
  const [state, setState] = useState<CaseState>({ status: "loading" });
  const [reload, setReload] = useState(0);

  const fetchIndex = useCallback(() => {
    setIndexError(null);
    setIndex(null);
    loadIndex()
      .then(setIndex)
      .catch((e: Error) => setIndexError(e.message));
  }, []);

  useEffect(() => {
    fetchIndex();
  }, [fetchIndex]);

  useEffect(() => {
    const onHash = () => {
      const id = caseFromHash();
      if (id) setSelected(id);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    let live = true;
    setState({ status: "loading" });
    loadCase(selected)
      .then((bundle) => live && setState({ status: "ready", bundle }))
      .catch((e: Error) => live && setState({ status: "error", message: e.message }));
    return () => {
      live = false;
    };
  }, [selected, reload]);

  const select = (id: string) => {
    setSelected(id);
    if (window.location.hash !== `#${id}`) history.replaceState(null, "", `#${id}`);
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <div>
            <strong>HHGoa Analyst Cockpit</strong>
            <span>Agentic fraud investigation on TigerGraph · read-only view of committed run artifacts</span>
          </div>
        </div>
        <div className="sim-banner" role="note">
          <strong>SIMULATED ENVIRONMENT</strong> Customer responses, actions, approvals and SARs are simulated. Nothing here touches a
          real card, customer or regulator.
        </div>
      </header>

      <div className="shell">
        <CaseQueue rows={index} error={indexError} selected={selected} onSelect={select} onRetry={fetchIndex} />

        <main className="workspace" id="main">
          {state.status === "loading" && (
            <div className="loading-block">
              <Skeleton height={150} />
              <Skeleton height={320} />
            </div>
          )}
          {state.status === "error" && (
            <ErrorState title={`Could not load ${selected}`} detail={state.message} onRetry={() => setReload((n) => n + 1)} />
          )}
          {state.status === "ready" && (
            <div className="ws" key={state.bundle.case_id}>
              <WorkspaceHeader b={state.bundle} />
              <CaseGraph b={state.bundle} />
              <div className="ws-split">
                <DecisionComparison b={state.bundle} />
                <div className="ws-rail">
                  <Copilot b={state.bundle} />
                  <p className="provenance fine">
                    Source: <code>{state.bundle.source.answer_file}</code> and <code>{state.bundle.source.run_dir}/</code> (run{" "}
                    {state.bundle.run_id}). Answer SHA-256 <code>{state.bundle.source.answer_sha256.slice(0, 16)}…</code>
                  </p>
                </div>
              </div>
              <Timeline b={state.bundle} />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
