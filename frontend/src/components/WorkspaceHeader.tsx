import type { CaseBundle } from "../types";
import { highestRoute, plural, prob, signed, tone, TRIGGER_LABEL } from "../lib/format";
import { Badge, Kpi, Sim } from "./ui";

export function WorkspaceHeader({ b }: { b: CaseBundle }) {
  const c = b.answer.case;
  const p0 = b.assessment.initial.p;
  const p1 = c.fraud_probability;
  const route = highestRoute(b.answer.next_best_actions.final);
  const audit = b.audit;
  const readBack = b.persist?.read_back ?? "not recorded";
  const auditOk = audit.chain_verified && readBack === "verified" && (b.persist?.answer_sha256_matches_file ?? false);

  return (
    <section className="ws-head" aria-labelledby="ws-title">
      <div className="ws-title-row">
        <div>
          <p className="eyebrow">{TRIGGER_LABEL[b.trigger.trigger_type] ?? b.trigger.trigger_type}</p>
          <h1 id="ws-title">
            {b.case_id}
            <span className="ws-graph-id">{c.graph_case_id}</span>
          </h1>
        </div>
        <div className="ws-badges">
          <Badge value={c.verdict}>verdict: {c.verdict}</Badge>
          <Badge value={c.status}>status: {c.status}</Badge>
          <Badge t="gray">pattern: {c.pattern}</Badge>
        </div>
      </div>

      <div className="trigger">
        <div className="trigger-meta">
          <span>
            <span className="muted">as_of</span> <strong className="num">{b.as_of}</strong>
          </span>
          <span>
            <span className="muted">flagged</span> <strong className="num">{b.trigger.flagged_txn_id}</strong>
          </span>
          <span>
            <span className="muted">card / customer</span>{" "}
            <strong className="num">
              {b.trigger.card_id} / {b.trigger.customer_id}
            </strong>
          </span>
        </div>
        <blockquote>{b.trigger.trigger_text}</blockquote>
        <p className="fine">Every graph query in this case ran with this as_of injected by the gateway; rows after it were rejected.</p>
      </div>

      <div className="kpis">
        <Kpi label="Verdict" value={c.verdict} t={tone(c.verdict)} help="Final verdict in the answer file" />
        <Kpi
          label="Fraud probability"
          value={<span className="num">{prob(p1)}</span>}
          sub={p1 !== p0 ? <span className={p1 > p0 ? "up" : "down"}>{signed(p1 - p0)} from {prob(p0)} initial</span> : "unchanged from initial"}
          help="Final calibrated fraud probability; the change is from the initial assessment"
        />
        <Kpi
          label="Model risk score"
          value={<span className="num">{b.trigger.risk_score || "n/a"}</span>}
          sub={b.trigger.risk_score ? "input, not a verdict" : "not a risk-score alert"}
          help="The bank model's score on the flagged transaction, from the alert row"
        />
        <Kpi label="Approval route" value={route} t={tone(route)} sub={<Sim>SIMULATED approval</Sim>} help="Highest route among the final actions (auto < L1 < L2)" />
        <Kpi
          label="Evidence items"
          value={<span className="num">{c.evidence.length}</span>}
          sub={`from ${plural(b.envelopes.length, "graph call")}`}
          help="Evidence entries in the answer file"
        />
        <Kpi
          label="Audit"
          value={auditOk ? "verified" : "check"}
          t={auditOk ? "green" : "amber"}
          sub={`chain ${audit.chain_verified ? "ok" : "broken"} · ${audit.n_events} events · read-back ${readBack}`}
          help="Hash chain verified by the project's own verifier at export; graph read-back and answer SHA-256 match recorded at persist"
        />
      </div>
    </section>
  );
}
