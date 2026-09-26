import type { AuditEvent, CaseBundle, Envelope } from "../types";

// Groups the real hash-chained audit events into investigation phases. Nothing is added:
// every item is one audit event (consecutive graph write calls are collapsed into one item).

export type Phase =
  | "Init"
  | "Triage"
  | "Graph investigation"
  | "Assessment"
  | "Policy decision"
  | "Evidence request"
  | "Simulated response"
  | "Narrative"
  | "Verification"
  | "Persistence"
  | "Done";

export const PHASES: Phase[] = [
  "Init",
  "Triage",
  "Graph investigation",
  "Assessment",
  "Policy decision",
  "Evidence request",
  "Simulated response",
  "Narrative",
  "Verification",
  "Persistence",
  "Done",
];

const STATE_PHASE: Record<string, Phase> = {
  INIT: "Init",
  TRIAGE: "Triage",
  CONTEXT: "Graph investigation",
  PATTERN_SCAN: "Graph investigation",
  NETWORK: "Graph investigation",
  MEMORY: "Graph investigation",
  ASSESS: "Assessment",
  REASSESS: "Assessment",
  DECIDE_INITIAL: "Policy decision",
  DECIDE_FINAL: "Policy decision",
  EVIDENCE_GATE: "Evidence request",
  REQUEST_EVIDENCE: "Evidence request",
  SIMULATE_RESPONSE: "Simulated response",
  NARRATE: "Narrative",
  VALIDATE: "Verification",
  PERSIST: "Persistence",
  DONE: "Done",
};

export interface TimelineItem {
  key: string;
  phase: Phase;
  title: string;
  subtitle: string;
  seqs: number[];
  wall: string;
  hash: string;
  envelope?: Envelope;
  simulated: boolean;
  detail: Record<string, unknown>;
}

function phaseOf(e: AuditEvent, current: Phase): Phase {
  if (e.event === "state" && e.state) return STATE_PHASE[e.state] ?? current;
  if (e.event === "tool_call") return (e.detail.tool as string) === "knowledge_search" ? current : "Graph investigation";
  if (e.event === "policy") return "Policy decision";
  if (e.event === "validation") return "Verification";
  if (e.event === "write_call" || e.event === "persist") return "Persistence";
  return current;
}

function stateSubtitle(e: AuditEvent): string {
  const d = e.detail;
  const parts: string[] = [];
  if (typeof d.step === "number") parts.push(`step ${d.step}`);
  if (d.as_of) parts.push(`as_of ${String(d.as_of)}`);
  if (d.llm) parts.push(`llm ${String(d.llm)}`);
  if (typeof d.p === "number") parts.push(`p ${d.p.toFixed(2)}`);
  if (d.verdict) parts.push(`verdict ${String(d.verdict)}`);
  if (d.pattern) parts.push(`pattern ${String(d.pattern)}`);
  if (d.request !== undefined) parts.push(d.request ? "evidence requested" : "no request");
  if (d.response) parts.push(`simulated response: ${String(d.response)}`);
  if (d.mode) parts.push(`narrative ${String(d.mode)}`);
  if (d.written_to_graph !== undefined) parts.push(d.written_to_graph ? "written to graph" : "not written");
  return parts.join(" · ");
}

export function buildTimeline(b: CaseBundle): TimelineItem[] {
  const env = new Map(b.envelopes.map((e) => [e.call_id, e]));
  const items: TimelineItem[] = [];
  let phase: Phase = "Init";
  for (const e of b.audit.events) {
    phase = phaseOf(e, phase);
    const base = { key: `e${e.seq}`, phase, seqs: [e.seq], wall: e.wall, hash: e.hash, detail: e.detail, simulated: false };
    if (e.event === "state") {
      items.push({
        ...base,
        title: e.state ?? "state",
        subtitle: stateSubtitle(e),
        simulated: e.state === "SIMULATE_RESPONSE" || (e.state === "REASSESS" && Boolean(e.detail.response)),
      });
    } else if (e.event === "tool_call") {
      const d = e.detail;
      items.push({
        ...base,
        title: `${String(d.call_id)} · ${String(d.query)}`,
        subtitle: `${String(d.row_count)} row${d.row_count === 1 ? "" : "s"} · result ${String(d.result_sha256).slice(0, 12)}`,
        envelope: env.get(String(d.call_id)),
      });
    } else if (e.event === "policy") {
      const fired = (e.detail.fired as string[]) ?? [];
      items.push({ ...base, title: `Policy engine (${String(e.detail.phase)})`, subtitle: `rules fired: ${fired.join(", ") || "none"}` });
    } else if (e.event === "validation") {
      const problems = (e.detail.problems as unknown[]) ?? [];
      items.push({ ...base, title: "Answer validation", subtitle: problems.length ? `${problems.length} problem(s)` : "no problems" });
    } else if (e.event === "write_call") {
      const last = items[items.length - 1];
      const d = e.detail;
      const what = d.tool
        ? `${String(d.tool)} ${String(d.vertex_type ?? d.edge_type ?? "")} ×${String(d.n ?? "")}`
        : `${String(d.query)}`;
      if (last && last.title === "Graph write-back") {
        last.seqs.push(e.seq);
        last.subtitle += ` · ${what}`;
        last.hash = e.hash;
      } else {
        items.push({ ...base, title: "Graph write-back", subtitle: what });
      }
    } else if (e.event === "persist") {
      const d = e.detail;
      items.push({ ...base, title: "Persisted and read back", subtitle: `${String(d.graph_case_id)} · read-back ${String(d.read_back)}` });
    }
  }
  return items;
}
