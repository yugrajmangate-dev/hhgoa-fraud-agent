import type { Action, Route } from "../types";

export const ROUTE_RANK: Record<string, number> = { auto: 0, L1: 1, L2: 2 };

export function highestRoute(actions: readonly Action[]): Route {
  if (!actions.length) return "none";
  return actions.reduce<Route>(
    (best, a) => ((ROUTE_RANK[a.route] ?? -1) > (ROUTE_RANK[best] ?? -1) ? a.route : best),
    actions[0].route,
  );
}

export const TRIGGER_LABEL: Record<string, string> = {
  risk_score: "Model risk-score alert",
  customer_report: "Customer report",
  analyst_request: "Analyst request",
};

export type Tone = "red" | "green" | "amber" | "blue" | "gray";

export function tone(value: string): Tone {
  switch (value) {
    case "fraud":
    case "closed_fraud":
    case "L2":
      return "red";
    case "legitimate":
    case "closed_legitimate":
      return "green";
    case "uncertain":
    case "escalated":
    case "L1":
      return "amber";
    case "auto":
    case "open":
      return "blue";
    default:
      return "gray";
  }
}

export const usd = (n: number) =>
  `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
export const prob = (n: number) => n.toFixed(2);
export const signed = (n: number) => `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(2)}`;
export const shortHash = (h: string) => h.slice(0, 12);

/** Run timestamps are UTC ISO strings; show them as UTC to stay faithful to the log. */
export function wallTime(iso: string): string {
  const m = /T(\d{2}:\d{2}:\d{2})(\.\d+)?/.exec(iso);
  return m ? `${m[1]}${m[2] ? m[2].slice(0, 4) : ""} UTC` : iso;
}

export const isSimulatedEvidence = (ref: string) => ref.startsWith("evidence_request");

export const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
