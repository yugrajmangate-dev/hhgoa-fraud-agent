import { useMemo, useState } from "react";
import type { CaseBundle } from "../types";
import { buildGraph, evidenceFor, NODE_H, NODE_W, type GNode, type NodeKind } from "../lib/graph";
import { isSimulatedEvidence } from "../lib/format";
import { Panel, Ref, Sim } from "./ui";

const KIND_LABEL: Record<NodeKind, string> = {
  case: "Investigation case",
  customer: "Customer",
  card: "Card",
  transaction: "Transaction",
  device: "Device profile",
  shared: "Shared element",
  connected: "Connected card",
  prior: "Prior closed case",
  more: "Not drawn",
};

const LEGEND: NodeKind[] = ["customer", "card", "transaction", "case", "device", "connected", "prior"];

function trim(s: string, n = 22) {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

export function CaseGraph({ b }: { b: CaseBundle }) {
  const g = useMemo(() => buildGraph(b), [b]);
  const [selectedId, setSelectedId] = useState<string>(b.trigger.flagged_txn_id);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [fit, setFit] = useState(true);
  const half = NODE_W / 2;
  const byId = useMemo(() => new Map(g.nodes.map((n) => [n.id, n])), [g]);
  const selected = byId.get(selectedId) ?? g.nodes[0];
  const focus = hoverId ?? selected?.id;
  const neighbours = useMemo(() => {
    const s = new Set<string>();
    for (const e of g.edges) {
      if (e.from === focus) s.add(e.to);
      if (e.to === focus) s.add(e.from);
    }
    return s;
  }, [g, focus]);

  return (
    <Panel
      title="Interactive graph"
      id="graph"
      kicker="Only relationships recorded in the committed artifacts: the edges written back to TigerGraph for this case, the alert row, device family F4 and the policy's shared link. Select a node to inspect its evidence."
      actions={
        <div className="seg seg-small" role="group" aria-label="Graph zoom">
          <button type="button" className={fit ? "is-active" : ""} aria-pressed={fit} onClick={() => setFit(true)}>
            Fit
          </button>
          <button type="button" className={!fit ? "is-active" : ""} aria-pressed={!fit} onClick={() => setFit(false)}>
            Actual size
          </button>
        </div>
      }
    >
      <div className="graph-layout">
        <div className="graph-canvas" role="group" aria-label="Case entity graph">
          <svg viewBox={`0 0 ${g.width} ${g.height}`} width={fit ? "100%" : g.width} height={fit ? undefined : g.height} style={fit ? { minWidth: Math.min(g.width, Math.max(560, Math.round(g.width * 0.78))) } : undefined} role="img" aria-label={`${g.nodes.length} entities, ${g.edges.length} relationships`}>
            <defs>
              <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" className="arrowhead" />
              </marker>
            </defs>
            {g.edges.map((e) => {
              const a = byId.get(e.from);
              const z = byId.get(e.to);
              if (!a || !z) return null;
              const active = focus === e.from || focus === e.to;
              const mx = (a.x + z.x) / 2;
              const reverse = z.x < a.x;
              const path = reverse
                ? `M ${a.x - half} ${a.y} C ${mx} ${a.y}, ${mx} ${z.y}, ${z.x + half} ${z.y}`
                : `M ${a.x + half} ${a.y} C ${mx} ${a.y}, ${mx} ${z.y}, ${z.x - half} ${z.y}`;
              return (
                <g key={`${e.from}-${e.to}`} className={`edge ${active ? "is-active" : ""}`}>
                  <path d={path} markerEnd="url(#arrow)">
                    <title>{`${e.labels.join(" · ")} (source: ${e.sources.join(", ")})`}</title>
                  </path>
                  {active && (
                    <text x={mx} y={(a.y + z.y) / 2 - 6} textAnchor="middle" className="edge-label">
                      {e.labels.join(" · ")}
                    </text>
                  )}
                </g>
              );
            })}
            {g.nodes.map((n) => (
              <g
                key={n.id}
                className={`node node-${n.kind} ${n.id === selected?.id ? "is-selected" : ""} ${focus && n.id !== focus && !neighbours.has(n.id) ? "is-dim" : ""}`}
                transform={`translate(${n.x - half} ${n.y - NODE_H / 2})`}
                tabIndex={n.kind === "more" ? -1 : 0}
                role="button"
                aria-label={`${n.role}: ${n.label}`}
                aria-pressed={n.id === selected?.id}
                onClick={() => n.kind !== "more" && setSelectedId(n.id)}
                onKeyDown={(ev) => {
                  if ((ev.key === "Enter" || ev.key === " ") && n.kind !== "more") {
                    ev.preventDefault();
                    setSelectedId(n.id);
                  }
                }}
                onMouseEnter={() => setHoverId(n.id)}
                onMouseLeave={() => setHoverId(null)}
                onFocus={() => setHoverId(n.id)}
                onBlur={() => setHoverId(null)}
              >
                <title>{`${n.role}: ${n.label}`}</title>
                <rect width={NODE_W} height={NODE_H} rx={n.kind === "case" || n.kind === "device" || n.kind === "shared" ? NODE_H / 2 : 7} />
                <text x={half} y={NODE_H / 2 + 4} textAnchor="middle">
                  {trim(n.label, n.kind === "device" || n.kind === "shared" ? 18 : 20)}
                </text>
              </g>
            ))}
          </svg>
        </div>
        <ul className="legend" aria-label="Legend">
          {LEGEND.map((k) => (
            <li key={k}>
              <span className={`swatch node-${k}`} /> {KIND_LABEL[k]}
            </li>
          ))}
          {(g.hidden.connected > 0 || g.hidden.transactions > 0) && (
            <li className="muted">
              Showing the first 24 per group; {g.hidden.connected ? `${g.hidden.connected} more connected cards` : ""}
              {g.hidden.connected && g.hidden.transactions ? " and " : ""}
              {g.hidden.transactions ? `${g.hidden.transactions} more transactions` : ""} are listed in the answer file.
            </li>
          )}
        </ul>
        {selected && <NodeInspector b={b} node={selected} edges={g.edges.filter((e) => e.from === selected.id || e.to === selected.id)} byId={byId} />}
      </div>
    </Panel>
  );
}

function NodeInspector({
  b,
  node,
  edges,
  byId,
}: {
  b: CaseBundle;
  node: GNode;
  edges: { from: string; to: string; labels: string[]; sources: string[] }[];
  byId: Map<string, GNode>;
}) {
  const ev = evidenceFor(b, node);
  const empty = !ev.evidence.length && !ev.families.length && !ev.calls.length;
  return (
    <aside className="inspector" aria-live="polite" aria-label="Selected entity">
      <p className="eyebrow">{node.role}</p>
      <h3 className="inspector-id" title={node.label}>
        {node.label}
      </h3>

      <h4>Relationships</h4>
      <ul className="rel-list">
        {edges.map((e) => {
          const other = byId.get(e.from === node.id ? e.to : e.from);
          return (
            <li key={`${e.from}-${e.to}`}>
              <span className="rel-dir">{e.from === node.id ? "→" : "←"}</span> <strong>{e.labels.join(" · ")}</strong>{" "}
              <span className="rel-other" title={other?.label}>
                {other?.label}
              </span>
              <span className="rel-src">source: {e.sources.join(", ")}</span>
            </li>
          );
        })}
      </ul>

      {ev.evidence.length > 0 && (
        <>
          <h4>Evidence in the answer file</h4>
          <ul className="ev-list">
            {ev.evidence.map((e, i) => (
              <li key={i}>
                <span className="ev-src">
                  {e.source}
                  {isSimulatedEvidence(e.ref) && <Sim />}
                </span>
                <p>{e.claim}</p>
                <Ref>{e.ref}</Ref>
              </li>
            ))}
          </ul>
        </>
      )}
      {ev.families.length > 0 && (
        <>
          <h4>Scorer evidence families</h4>
          <ul className="ev-list">
            {ev.families.map((f) => (
              <li key={f.name}>
                <span className="ev-src">
                  {f.name} · weight {f.s.toFixed(3)}
                </span>
                <p>{f.claim}</p>
                {f.refs[0] && <Ref>{f.refs[0]}</Ref>}
              </li>
            ))}
          </ul>
        </>
      )}
      {ev.calls.length > 0 && (
        <>
          <h4>Graph calls that returned this entity</h4>
          <ul className="call-chips">
            {ev.calls.map((c) => (
              <li key={c.call_id} title={c.ref}>
                {c.call_id} · {c.query} · {c.row_count} rows
              </li>
            ))}
          </ul>
        </>
      )}
      {node.kind === "case" && b.persist && (
        <p className="fine">
          Written through the official MCP; read-back <strong>{b.persist.read_back}</strong>; stored answer SHA-256{" "}
          {b.persist.answer_sha256_matches_file ? "matches" : "does not match"} the committed file.
        </p>
      )}
      {empty && node.kind !== "case" && <p className="muted">No evidence item, scorer family or graph call names this entity directly.</p>}
    </aside>
  );
}
