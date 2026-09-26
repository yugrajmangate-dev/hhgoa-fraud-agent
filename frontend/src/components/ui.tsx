import type { ReactNode } from "react";
import { tone, type Tone } from "../lib/format";

export function Badge({ children, value, t, title }: { children?: ReactNode; value?: string; t?: Tone; title?: string }) {
  return (
    <span className={`badge badge-${t ?? tone(value ?? "")}`} title={title}>
      {children ?? value}
    </span>
  );
}

/** The one label used everywhere for simulated customer replies, actions, approvals and SARs. */
export function Sim({ children = "SIMULATED" }: { children?: ReactNode }) {
  return <span className="sim-tag">{children}</span>;
}

export function Panel({
  title,
  kicker,
  actions,
  children,
  className = "",
  id,
}: {
  title: string;
  kicker?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section className={`panel ${className}`} id={id} aria-labelledby={id ? `${id}-title` : undefined}>
      <header className="panel-head">
        <div>
          <h2 id={id ? `${id}-title` : undefined}>{title}</h2>
          {kicker && <p className="panel-kicker">{kicker}</p>}
        </div>
        {actions && <div className="panel-actions">{actions}</div>}
      </header>
      {children}
    </section>
  );
}

export function Kpi({ label, value, sub, t, help }: { label: string; value: ReactNode; sub?: ReactNode; t?: Tone; help?: string }) {
  return (
    <div className={`kpi ${t ? `kpi-${t}` : ""}`} title={help}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

export function Ref({ children }: { children: string }) {
  return (
    <code className="ref" title={children}>
      {children}
    </code>
  );
}

export function Skeleton({ lines = 3, height }: { lines?: number; height?: number }) {
  return (
    <div className="skeleton-wrap" aria-busy="true" aria-live="polite">
      {height ? (
        <div className="skeleton" style={{ height }} />
      ) : (
        Array.from({ length: lines }, (_, i) => <div key={i} className="skeleton" style={{ width: `${92 - i * 11}%` }} />)
      )}
    </div>
  );
}

export function ErrorState({ title, detail, onRetry }: { title: string; detail: string; onRetry?: () => void }) {
  return (
    <div className="state state-error" role="alert">
      <strong>{title}</strong>
      <p>{detail}</p>
      {onRetry && (
        <button type="button" className="btn" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="state state-empty">{children}</div>;
}
