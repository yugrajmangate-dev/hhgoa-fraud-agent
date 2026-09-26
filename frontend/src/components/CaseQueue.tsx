import { useMemo, useState } from "react";
import type { IndexRow } from "../types";
import { prob, tone, usd } from "../lib/format";
import { Badge, EmptyState, ErrorState, Skeleton } from "./ui";

const FILTERS = ["all", "fraud", "uncertain", "legitimate"] as const;
type Filter = (typeof FILTERS)[number];

export function CaseQueue({
  rows,
  error,
  selected,
  onSelect,
  onRetry,
}: {
  rows: IndexRow[] | null;
  error: string | null;
  selected: string;
  onSelect: (id: string) => void;
  onRetry: () => void;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: rows?.length ?? 0 };
    for (const r of rows ?? []) c[r.verdict] = (c[r.verdict] ?? 0) + 1;
    return c;
  }, [rows]);
  const visible = (rows ?? []).filter((r) => filter === "all" || r.verdict === filter);
  const demos = (rows ?? []).filter((r) => r.demo);

  return (
    <nav className="queue" aria-label="Case queue">
      <div className="queue-head">
        <h2>Case queue</h2>
        <span className="muted">{rows ? `${rows.length} committed cases` : "loading…"}</span>
      </div>

      {demos.length > 0 && (
        <div className="demo-picks" aria-label="Demo cases">
          {demos.map((d) => (
            <button
              key={d.case_id}
              type="button"
              className={`demo-pick ${selected === d.case_id ? "is-active" : ""}`}
              onClick={() => onSelect(d.case_id)}
            >
              <span className="demo-id">{d.case_id}</span>
              <span className="demo-kind">{d.demo === "device-ring" ? "Device-ring demo" : "Verification demo"}</span>
            </button>
          ))}
        </div>
      )}

      <div className="seg" role="tablist" aria-label="Filter by verdict">
        {FILTERS.map((f) => (
          <button
            key={f}
            type="button"
            role="tab"
            aria-selected={filter === f}
            className={filter === f ? "is-active" : ""}
            onClick={() => setFilter(f)}
          >
            {f} <span className="seg-count">{counts[f] ?? 0}</span>
          </button>
        ))}
      </div>

      {error ? (
        <ErrorState title="Could not load the case index" detail={error} onRetry={onRetry} />
      ) : !rows ? (
        <Skeleton lines={8} />
      ) : visible.length === 0 ? (
        <EmptyState>No cases match this filter.</EmptyState>
      ) : (
        <ul className="queue-list">
          {visible.map((r) => (
            <li key={r.case_id}>
              <button
                type="button"
                className={`queue-row tone-${tone(r.verdict)} ${selected === r.case_id ? "is-active" : ""} ${r.demo ? "is-demo" : ""}`}
                onClick={() => onSelect(r.case_id)}
                aria-current={selected === r.case_id ? "true" : undefined}
              >
                <div className="qr-top">
                  <span className="qr-id">{r.case_id}</span>
                  {r.demo && <span className="qr-demo">demo</span>}
                  <Badge value={r.verdict} />
                </div>
                <div className="qr-prob" aria-label={`fraud probability ${prob(r.fraud_probability)}`}>
                  <div className="bar">
                    <span style={{ width: `${Math.round(r.fraud_probability * 100)}%` }} />
                  </div>
                  <span className="num">{prob(r.fraud_probability)}</span>
                </div>
                <dl className="qr-meta">
                  <div>
                    <dt>Pattern</dt>
                    <dd title={r.pattern}>{r.pattern}</dd>
                  </div>
                  <div>
                    <dt>Exposure</dt>
                    <dd className="num">{usd(r.exposure_usd)}</dd>
                  </div>
                  <div>
                    <dt>Route</dt>
                    <dd>
                      <Badge value={r.route} />
                    </dd>
                  </div>
                  <div>
                    <dt>SAR</dt>
                    <dd>{r.sar_file ? <span className="sar-yes">file · sim</span> : <span className="muted">no</span>}</dd>
                  </div>
                </dl>
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="queue-foot">
        Routes, SARs and approvals are <strong>simulated</strong>. There is no answer key, so these are the agent's decisions,
        not measured accuracy.
      </p>
    </nav>
  );
}
