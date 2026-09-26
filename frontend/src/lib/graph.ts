import type { CaseBundle, Envelope, EvidenceItem, Family } from "../types";

// The case graph draws only relationships present in the committed artifacts:
//  - the edges the agent wrote to TigerGraph for this case (orchestrator PERSIST step):
//    FLAGGED, ON_CARD, INVOLVES, FIRST_FRAUD, CONNECTED_TO, NAMES_DEVICE, SIMILAR_TO;
//  - the alert row in trace.case: customer OWNS card, card MADE the flagged transaction;
//  - family F4 (device): the flagged transaction's device profile;
//  - policy_final.shared_link: the flagged card shares an element with other customers' cards.

export type NodeKind = "case" | "customer" | "card" | "transaction" | "device" | "shared" | "connected" | "prior" | "more";

export interface GNode {
  id: string;
  kind: NodeKind;
  label: string;
  role: string;
  x: number;
  y: number;
}

export interface GEdge {
  from: string;
  to: string;
  labels: string[];
  sources: string[];
}

export interface CaseGraph {
  nodes: GNode[];
  edges: GEdge[];
  width: number;
  height: number;
  hidden: { connected: number; transactions: number };
}

interface Pending {
  id: string;
  kind: NodeKind;
  label: string;
  role: string;
  lane: number;
}

const CAP = 24;
const ROW = 46;
const PER_COL = 12;
const LANE_X = [72, 214, 356, 506, 668, 830];
const CONNECTED_COL_W = 146;
export const NODE_W = 124;
export const NODE_H = 34;

export function buildGraph(b: CaseBundle): CaseGraph {
  const c = b.answer.case;
  const t = b.trigger;
  const nodes = new Map<string, Pending>();
  const edges = new Map<string, GEdge>();
  const add = (id: string, kind: NodeKind, lane: number, label: string, role: string) => {
    if (!nodes.has(id)) nodes.set(id, { id, kind, lane, label, role });
    return id;
  };
  const link = (from: string, to: string, label: string, source: string) => {
    const key = `${from}->${to}`;
    const e = edges.get(key) ?? { from, to, labels: [], sources: [] };
    if (!e.labels.includes(label)) e.labels.push(label);
    if (!e.sources.includes(source)) e.sources.push(source);
    edges.set(key, e);
  };

  const graphCaseId = b.persist?.graph_case_id || c.graph_case_id || b.case_id;
  const caseNode = add(graphCaseId, "case", 3, graphCaseId, "Investigation case");
  add(t.customer_id, "customer", 0, t.customer_id, "Customer");
  add(t.card_id, "card", 1, t.card_id, "Card");
  add(t.flagged_txn_id, "transaction", 2, t.flagged_txn_id, "Flagged transaction");
  link(t.customer_id, t.card_id, "OWNS", "trace.case (alert row)");
  link(t.card_id, t.flagged_txn_id, "MADE", "trace.case (alert row)");
  link(caseNode, t.flagged_txn_id, "FLAGGED", "graph write-back");
  link(caseNode, t.card_id, "ON_CARD", "graph write-back");

  const affected = c.affected_txn_ids.filter((x) => x !== t.flagged_txn_id);
  for (const x of affected.slice(0, CAP)) {
    add(x, "transaction", 2, x, "Affected transaction");
    link(caseNode, x, "INVOLVES", "graph write-back");
  }
  if (c.affected_txn_ids.includes(t.flagged_txn_id)) link(caseNode, t.flagged_txn_id, "INVOLVES", "graph write-back");
  if (c.first_suspicious_txn_id && nodes.has(c.first_suspicious_txn_id)) {
    link(caseNode, c.first_suspicious_txn_id, "FIRST_FRAUD", "graph write-back");
  }

  const f4 = b.families.find((f) => f.name === "F4_device");
  const rawProfile = f4?.detail?.profile;
  const profile = typeof rawProfile === "string" ? rawProfile : "";
  if (profile) {
    add(`device:${profile}`, "device", 4, profile, "Device profile");
    link(t.flagged_txn_id, `device:${profile}`, "FROM_DEVICE", "family F4 (device)");
    link(caseNode, `device:${profile}`, "NAMES_DEVICE", "graph write-back");
  }
  for (const d of c.connected_device_profiles) {
    add(`device:${d}`, "device", 4, d, "Device profile");
    link(caseNode, `device:${d}`, "NAMES_DEVICE", "graph write-back");
  }

  const shared = b.policy.final.shared_link && b.policy.final.shared_element ? b.policy.final.shared_element : "";
  if (shared) {
    const [type, ...rest] = shared.split(" ");
    const value = rest.join(" ");
    const existing = type === "DeviceProfile" && nodes.get(`device:${value}`);
    const id = existing ? `device:${value}` : `shared:${shared}`;
    if (existing) existing.role = "Device profile (shared with other customers' cards)";
    else add(id, "shared", 4, value || shared, `Shared ${type}`);
    link(t.card_id, id, `shares ${type}`, "policy_final.shared_link");
  }

  for (const p of c.similar_prior_cases) {
    add(p, "prior", 4, p, "Similar prior closed case");
    link(caseNode, p, "SIMILAR_TO", "graph write-back");
  }

  for (const k of c.connected_card_ids.slice(0, CAP)) {
    add(k, "connected", 5, k, "Connected card");
    link(caseNode, k, "CONNECTED_TO", "graph write-back");
  }

  const hidden = {
    connected: Math.max(0, c.connected_card_ids.length - CAP),
    transactions: Math.max(0, affected.length - CAP),
  };
  if (hidden.connected) add("more:connected", "more", 5, `+${hidden.connected} more cards`, "Not drawn (listed in the answer file)");
  if (hidden.transactions) add("more:transactions", "more", 2, `+${hidden.transactions} more`, "Not drawn (listed in the answer file)");

  // Deterministic lane layout; connected cards wrap into extra columns of PER_COL.
  const byLane = new Map<number, Pending[]>();
  for (const n of nodes.values()) byLane.set(n.lane, [...(byLane.get(n.lane) ?? []), n]);
  const connected = byLane.get(5) ?? [];
  const connectedCols = Math.max(1, Math.ceil(connected.length / PER_COL));
  const tallest = Math.max(1, ...[...byLane.entries()].map(([lane, l]) => (lane === 5 ? Math.min(PER_COL, l.length) : l.length)));
  // The investigation case sits in its own band above the entity rows, so the
  // customer -> card -> transaction -> device chain reads left to right without crossing it.
  const TOP = 84;
  const body = Math.max(200, tallest * ROW + 60);
  const height = TOP + body;
  const mid = TOP + body / 2;
  const placed: GNode[] = [];
  for (const [lane, list] of byLane) {
    list.forEach((n, i) => {
      const { lane: _lane, ...rest } = n;
      void _lane;
      if (lane === 3) {
        placed.push({ ...rest, x: LANE_X[3], y: TOP / 2 + 4 });
      } else if (lane === 5) {
        const col = Math.floor(i / PER_COL);
        const inCol = Math.min(PER_COL, list.length - col * PER_COL);
        placed.push({ ...rest, x: LANE_X[5] + col * CONNECTED_COL_W, y: mid + ((i % PER_COL) - (inCol - 1) / 2) * ROW });
      } else {
        placed.push({ ...rest, x: LANE_X[lane], y: mid + (i - (list.length - 1) / 2) * ROW });
      }
    });
  }
  const width = (connected.length ? LANE_X[5] + (connectedCols - 1) * CONNECTED_COL_W : LANE_X[4]) + NODE_W / 2 + 24;
  return { nodes: placed, edges: [...edges.values()], width, height, hidden };
}

export interface NodeEvidence {
  evidence: EvidenceItem[];
  families: Family[];
  calls: Envelope[];
}

/** Evidence items, scorer families and graph calls that name this node's entity ID. */
export function evidenceFor(b: CaseBundle, node: GNode): NodeEvidence {
  const ids = new Set([node.id, node.label]);
  const hit = (list: readonly string[]) => list.some((x) => ids.has(x));
  return {
    evidence: b.answer.case.evidence.filter((e) => hit(e.entity_ids)),
    families: b.families.filter(
      (f) =>
        hit(f.entities) ||
        (f.name === "F4_device" && f.detail?.profile === node.label) ||
        ((node.kind === "shared" || node.role.includes("shared with")) && f.name === "F8_network"),
    ),
    calls: b.envelopes.filter((e) => hit(e.visible_ids)),
  };
}
