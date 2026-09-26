import type { CaseBundle } from "../../src/types";
import { highestRoute } from "../../src/lib/format";

// Builds the ONLY case information a model ever sees: a whitelist of fields from the exported,
// already-sanitized case bundle. No audit hashes, file paths, run directories, raw dataset rows,
// knowledge-chunk text, credentials or hostnames. Anything that still matches FORBIDDEN aborts
// the call before it leaves the server.

export const FORBIDDEN = /https?:\/\/|tgcloud|\.env\b|TG_[A-Z]+|OPENROUTER|api[_-]?key|secret|password|BEGIN [A-Z ]*PRIVATE KEY/i;

const MAX_TEXT = 600;
const MAX_IDS = 25;
const clip = (s: string) => (s.length > MAX_TEXT ? `${s.slice(0, MAX_TEXT)}…` : s);
const simulatedRef = (ref: string) => ref.startsWith("evidence_request");

export const CONTEXT_FIELDS = [
  "trigger",
  "decision",
  "evidence",
  "evidence_requests",
  "actions_initial",
  "actions_final",
  "what_changed",
  "stop_reason",
  "sar",
  "scorer_families",
  "graph_calls",
  "entities",
  "audit",
] as const;

export interface ModelContext {
  context: Record<string, unknown>;
  /** Citations the model may use: every provenance ref in the context plus the context field names. */
  allowedCitations: Set<string>;
  /** Every decimal number that appears in the context (the model may not introduce new ones). */
  numbers: number[];
  verdict: string;
}

export function buildModelContext(b: CaseBundle): ModelContext {
  const c = b.answer.case;
  const nba = b.answer.next_best_actions;
  const p0 = b.assessment.initial.p;
  const p1 = c.fraud_probability;
  const context: Record<string, unknown> = {
    case_id: b.case_id,
    as_of: b.as_of,
    trigger: {
      type: b.trigger.trigger_type,
      opened_at: b.trigger.opened_at,
      text: clip(b.trigger.trigger_text),
      flagged_txn_id: b.trigger.flagged_txn_id,
      card_id: b.trigger.card_id,
      customer_id: b.trigger.customer_id,
      model_risk_score: b.trigger.risk_score || null,
    },
    decision: {
      verdict: c.verdict,
      status: c.status,
      fraud_probability_initial: p0,
      fraud_probability_final: p1,
      fraud_probability_change: Number((p1 - p0).toFixed(2)),
      pattern: c.pattern,
      pattern_description: clip(c.pattern_description),
      exposure_usd: c.exposure_usd,
      highest_final_route: highestRoute(nba.final),
      rules_fired_initial: b.policy.fired.initial,
      rules_fired_final: b.policy.fired.final,
    },
    evidence: c.evidence.map((e) => ({ source: e.source, claim: clip(e.claim), ref: e.ref, simulated: simulatedRef(e.ref) })),
    evidence_requests: b.answer.evidence_requests.map((r) => ({
      type: r.type,
      asked_after_step: r.asked_after_step,
      assumed_response: clip(r.assumed_response),
      simulated: true,
    })),
    actions_initial: nba.initial.map((a) => ({ action: a.action, route: a.route, reason: clip(a.reason) })),
    actions_final: nba.final.map((a) => ({ action: a.action, route: a.route, reason: clip(a.reason), execution_simulated: true })),
    what_changed: clip(nba.what_changed),
    stop_reason: clip(b.answer.stop_reason),
    sar: { file: b.answer.sar.file, reason: clip(b.answer.sar.reason), simulated: true },
    scorer_families: b.families
      .filter((f) => f.available && f.claim)
      .map((f) => ({ name: f.name, weight: f.s, claim: clip(f.claim), refs: f.refs.slice(0, 3) })),
    graph_calls: b.envelopes.map((e) => ({ call_id: e.call_id, query: e.query, row_count: e.row_count, ref: e.ref })),
    entities: {
      connected_card_count: c.connected_card_ids.length,
      connected_card_ids: c.connected_card_ids.slice(0, MAX_IDS),
      connected_device_profiles: c.connected_device_profiles,
      shared_element: b.policy.final.shared_link ? b.policy.final.shared_element : null,
      affected_txn_count: c.affected_txn_ids.length,
      affected_txn_ids: c.affected_txn_ids.slice(0, MAX_IDS),
      similar_prior_cases: c.similar_prior_cases,
    },
    audit: {
      chain_verified: b.audit.chain_verified,
      events: b.audit.n_events,
      graph_case_id: b.persist?.graph_case_id ?? c.graph_case_id,
      read_back: b.persist?.read_back ?? null,
    },
  };

  const refs = new Set<string>(CONTEXT_FIELDS);
  for (const e of c.evidence) refs.add(e.ref);
  for (const f of b.families) f.refs.forEach((r) => refs.add(r));
  for (const e of b.envelopes) refs.add(e.ref);

  const text = JSON.stringify(context);
  const numbers = [...new Set((text.match(/-?\d+\.\d+/g) ?? []).map(Number))];
  return { context, allowedCitations: refs, numbers, verdict: c.verdict };
}

/** Throws if anything in the serialized context looks like a secret, URL or hostname. */
export function assertSafeContext(serialized: string): void {
  const hit = FORBIDDEN.exec(serialized);
  if (hit) throw new Error(`context rejected: matched ${hit[0].slice(0, 3)}…`);
}
