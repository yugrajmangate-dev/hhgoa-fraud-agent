import type { Action, CaseBundle } from "../types";
import { highestRoute, prob, signed, tone, usd } from "../lib/format";
import { Badge, Panel, Sim } from "./ui";

function ActionList({ actions, other, kind }: { actions: Action[]; other: Set<string>; kind: "initial" | "final" }) {
  return (
    <ul className="actions">
      {actions.map((a) => {
        const status = other.has(a.action) ? "kept" : kind === "initial" ? "dropped" : "added";
        return (
          <li key={a.action} className={`act act-${status}`}>
            <div className="act-top">
              <strong>{a.action}</strong>
              <Badge value={a.route} />
              <span className={`act-status s-${status}`}>{status}</span>
            </div>
            <p>{a.reason}</p>
          </li>
        );
      })}
    </ul>
  );
}

export function DecisionComparison({ b }: { b: CaseBundle }) {
  const nba = b.answer.next_best_actions;
  const p0 = b.assessment.initial.p;
  const p1 = b.answer.case.fraud_probability;
  const initialSet = new Set(nba.initial.map((a) => a.action));
  const finalSet = new Set(nba.final.map((a) => a.action));
  const sar = b.answer.sar;
  const route = highestRoute(nba.final);

  return (
    <Panel title="Decision comparison" id="decision" kicker="Initial versus final decision, exactly as recorded in the answer file and trace.">
      <div className="prob-compare" aria-label={`Fraud probability ${prob(p0)} initially, ${prob(p1)} finally`}>
        {[
          ["Initial", p0],
          ["Final", p1],
        ].map(([label, p]) => (
          <div key={label as string} className="pc-row">
            <span className="pc-label">{label as string}</span>
            <div className="pc-track">
              <span className="pc-fill" style={{ width: `${Math.round((p as number) * 100)}%` }} />
            </div>
            <span className="num pc-val">{prob(p as number)}</span>
          </div>
        ))}
        <p className="fine">
          Change {signed(p1 - p0)}. Rules fired: initial <strong>{b.policy.fired.initial.join(", ") || "none"}</strong>, final{" "}
          <strong>{b.policy.fired.final.join(", ") || "none"}</strong>.
        </p>
      </div>

      {b.answer.evidence_requests.length > 0 ? (
        <div className="sim-panel" role="note">
          <div className="sim-panel-head">
            <Sim /> Additional evidence: customer response
          </div>
          {b.answer.evidence_requests.map((r, i) => (
            <p key={i}>
              <strong>{r.type}</strong> (requested after step {r.asked_after_step}): {r.assumed_response}
            </p>
          ))}
          <p className="fine">The dataset contains no customer replies. This response is a deterministic, recorded assumption.</p>
        </div>
      ) : (
        <p className="muted">No additional evidence was requested for this case.</p>
      )}

      <div className="compare-cols">
        <div>
          <h3>
            Initial actions <span className="muted">({nba.initial.length})</span>
          </h3>
          <ActionList actions={nba.initial} other={finalSet} kind="initial" />
        </div>
        <div>
          <h3>
            Final actions <span className="muted">({nba.final.length})</span> <Sim>SIMULATED execution</Sim>
          </h3>
          <ActionList actions={nba.final} other={initialSet} kind="final" />
        </div>
      </div>

      <div className="text-cols">
        <div className="quote-card">
          <h4>what_changed</h4>
          <p>{nba.what_changed}</p>
        </div>
        <div className="quote-card">
          <h4>stop_reason</h4>
          <p>{b.answer.stop_reason}</p>
        </div>
      </div>

      <div className="route-explain">
        <h3>Approval routes</h3>
        <p>
          Highest final route: <Badge value={route} />. Each route is the policy engine's output for that action, with the reason
          it recorded. <strong>auto</strong> actions run only in a sandbox with no network clients; <strong>L1</strong> and{" "}
          <strong>L2</strong> actions await human approval at that level. All execution and approvals here are <Sim />.
        </p>
        <table>
          <thead>
            <tr>
              <th>Action</th>
              <th>Route</th>
              <th>Execution</th>
            </tr>
          </thead>
          <tbody>
            {nba.final.map((a) => (
              <tr key={a.action}>
                <td>{a.action}</td>
                <td>
                  <Badge value={a.route} />
                </td>
                <td className={`t-${tone(a.route)}`}>{a.route === "auto" ? "SIMULATED: auto-executed in sandbox" : `SIMULATED: awaiting ${a.route} approval`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="sar-card">
        <div className="sar-head">
          <Sim /> <strong>Suspicious activity report</strong> <span className="muted">· never sent to a regulator</span>
        </div>
        <p>
          Decision: <strong>{sar.file ? "file" : "do not file"}</strong> · {sar.reason}
        </p>
        {sar.file && (
          <>
            <p className="fine">
              Total {usd(sar.total_amount_usd)} · {sar.subjects.length} subjects · {sar.activity_dates.length} activity dates
            </p>
            <blockquote>{sar.narrative}</blockquote>
          </>
        )}
      </div>
    </Panel>
  );
}
