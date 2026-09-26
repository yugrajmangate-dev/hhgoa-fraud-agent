import { useMemo, useState } from "react";
import type { CaseBundle } from "../types";
import { buildTimeline, PHASES, type Phase } from "../lib/timeline";
import { shortHash, wallTime } from "../lib/format";
import { Panel, Ref, Sim } from "./ui";

export function Timeline({ b }: { b: CaseBundle }) {
  const items = useMemo(() => buildTimeline(b), [b]);
  const present = PHASES.filter((p) => items.some((i) => i.phase === p));
  const [phase, setPhase] = useState<Phase | "all">("all");
  const [open, setOpen] = useState<string | null>(null);
  const shown = phase === "all" ? items : items.filter((i) => i.phase === phase);

  return (
    <Panel
      title="Evidence timeline"
      id="timeline"
      kicker={
        <>
          {b.audit.n_events} hash-chained audit events from <code>{b.source.run_dir}/audit.jsonl</code>, chain{" "}
          <strong className={b.audit.chain_verified ? "ok" : "bad"}>{b.audit.chain_verified ? "verified" : "broken"}</strong>. Times are
          the run's wall clock (UTC).
        </>
      }
    >
      <div className="chips" role="tablist" aria-label="Filter by phase">
        <button type="button" role="tab" aria-selected={phase === "all"} className={phase === "all" ? "is-active" : ""} onClick={() => setPhase("all")}>
          All
        </button>
        {present.map((p) => (
          <button key={p} type="button" role="tab" aria-selected={phase === p} className={phase === p ? "is-active" : ""} onClick={() => setPhase(p)}>
            {p}
            {p === "Simulated response" && <Sim />}
          </button>
        ))}
      </div>
      <ol className="timeline">
        {shown.map((it) => {
          const isOpen = open === it.key;
          return (
            <li key={it.key} className={`tl-item phase-${it.phase.replace(/\s+/g, "-").toLowerCase()} ${it.simulated ? "is-sim" : ""}`}>
              <button type="button" className="tl-head" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : it.key)}>
                <span className="tl-dot" aria-hidden="true" />
                <span className="tl-phase">{it.phase}</span>
                <span className="tl-title">
                  {it.title}
                  {it.simulated && <Sim />}
                </span>
                <span className="tl-sub">{it.subtitle}</span>
                <span className="tl-time num">{wallTime(it.wall)}</span>
              </button>
              {isOpen && (
                <div className="tl-body">
                  <dl className="kv">
                    <div>
                      <dt>Audit seq</dt>
                      <dd className="num">{it.seqs.length > 1 ? `${it.seqs[0]}–${it.seqs[it.seqs.length - 1]}` : it.seqs[0]}</dd>
                    </div>
                    <div>
                      <dt>Event hash</dt>
                      <dd>
                        <code>{shortHash(it.hash)}…</code>
                      </dd>
                    </div>
                    {it.envelope && (
                      <>
                        <div>
                          <dt>Executed at</dt>
                          <dd className="num">{it.envelope.executed_at}</dd>
                        </div>
                        <div>
                          <dt>Result SHA-256</dt>
                          <dd>
                            <code>{shortHash(it.envelope.result_sha256)}…</code>
                          </dd>
                        </div>
                      </>
                    )}
                  </dl>
                  {it.envelope && (
                    <>
                      <p className="fine">Provenance reference</p>
                      <Ref>{it.envelope.ref}</Ref>
                    </>
                  )}
                  <pre className="json">{JSON.stringify(it.envelope ? it.envelope.params : it.detail, null, 2)}</pre>
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </Panel>
  );
}
