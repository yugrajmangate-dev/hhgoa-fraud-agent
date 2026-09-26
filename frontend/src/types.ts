// Shapes of the static JSON written by scripts/export_data.py. Every field comes from a
// committed artifact: cases/<id>.json (answer), runs/cases/<run>/trace.json and audit.jsonl.

export type Verdict = "fraud" | "legitimate" | "uncertain" | string;
export type Route = "auto" | "L1" | "L2" | string;

export interface IndexRow {
  case_id: string;
  verdict: Verdict;
  fraud_probability: number;
  pattern: string;
  exposure_usd: number;
  status: string;
  sar_file: boolean;
  route: Route;
  trigger_type: string;
  as_of: string;
  evidence_count: number;
  audit_verified: boolean;
  demo: string | null;
}

export interface EvidenceItem {
  source: "graph" | "document" | "customer" | string;
  claim: string;
  ref: string;
  entity_ids: string[];
}

export interface Action {
  action: string;
  route: Route;
  reason: string;
}

export interface EvidenceRequest {
  type: string;
  asked_after_step: number;
  assumed_response: string;
}

export interface Answer {
  case_id: string;
  case: {
    status: string;
    verdict: Verdict;
    fraud_probability: number;
    pattern: string;
    pattern_description: string;
    affected_txn_ids: string[];
    first_suspicious_txn_id: string;
    connected_card_ids: string[];
    connected_device_profiles: string[];
    exposure_usd: number;
    evidence: EvidenceItem[];
    similar_prior_cases: string[];
    summary: string;
    written_to_graph: boolean;
    graph_case_id: string;
  };
  evidence_requests: EvidenceRequest[];
  next_best_actions: { initial: Action[]; final: Action[]; what_changed: string };
  sar: {
    file: boolean;
    reason: string;
    narrative: string;
    subjects: string[];
    total_amount_usd: number;
    activity_dates: string[];
  };
  stop_reason: string;
  tool_calls: number;
  tokens: number;
  latency_s: number;
}

export interface Trigger {
  case_id: string;
  opened_at: string;
  trigger_type: string;
  trigger_text: string;
  flagged_txn_id: string;
  card_id: string;
  customer_id: string;
  risk_score: string;
}

export interface Assessment {
  p: number;
  n_support: number;
  n_exculpatory: number;
  conflict: boolean;
  coverage: number;
  statement: string;
  contributions: Record<string, number>;
}

export interface Family {
  name: string;
  s: number;
  available: boolean;
  entities: string[];
  claim: string;
  refs: string[];
  detail: Record<string, unknown>;
}

export interface Envelope {
  call_id: string;
  tool: string;
  query: string;
  params: Record<string, unknown>;
  executed_at: string;
  row_count: number;
  visible_ids: string[];
  result_sha256: string;
  ref: string;
}

export interface AuditEvent {
  seq: number;
  wall: string;
  event: "state" | "tool_call" | "policy" | "validation" | "write_call" | "persist" | string;
  state?: string;
  detail: Record<string, unknown>;
  hash: string;
  prev: string;
}

export interface CaseBundle {
  case_id: string;
  run_id: string;
  as_of: string;
  source: { answer_file: string; run_dir: string; answer_sha256: string; trace_sha256: string; audit_sha256: string };
  answer: Answer;
  trigger: Trigger;
  assessment: { initial: Assessment; final: Assessment };
  policy: {
    fired: { initial: string[]; final: string[] };
    final: {
      verdict: string;
      pattern: string;
      exposure: number;
      response: string;
      shared_link: boolean;
      shared_element: string | null;
      shared_cards: number | null;
      evidence_request_type: string | null;
    };
  };
  families: Family[];
  linked_cards: string[];
  envelopes: Envelope[];
  knowledge: { chunk_id: string; source: string; section: string; score: number }[];
  audit: { chain_verified: boolean; n_events: number; events: AuditEvent[] };
  persist: {
    graph_case_id: string;
    edges: Record<string, number>;
    read_back: string;
    answer_sha256_matches_file: boolean;
  } | null;
}
