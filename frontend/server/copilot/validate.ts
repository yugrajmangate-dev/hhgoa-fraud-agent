import { FORBIDDEN, type ModelContext } from "./context";

// A model answer is used only if it is well-formed and stays inside the evidence: every citation
// must be a provenance ref or field from the context, it may not introduce decimal numbers that
// are not in the context (for example a different probability), and it may not state a verdict
// other than the recorded one. Anything else falls back to the deterministic answer.

const MAX_ANSWER = 3000;
const MAX_CITATIONS = 12;
const VERDICTS = ["fraud", "legitimate", "uncertain"];

export type Validation = { ok: true; answer: string; citations: string[] } | { ok: false; why: string };

function parseJsonObject(content: string): unknown {
  const trimmed = content.trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
  try {
    return JSON.parse(trimmed);
  } catch {
    const start = trimmed.indexOf("{");
    const end = trimmed.lastIndexOf("}");
    if (start >= 0 && end > start) {
      try {
        return JSON.parse(trimmed.slice(start, end + 1));
      } catch {
        return null;
      }
    }
    return null;
  }
}

export function validateModelAnswer(content: string, ctx: ModelContext): Validation {
  const parsed = parseJsonObject(content) as { answer?: unknown; citations?: unknown } | null;
  if (!parsed || typeof parsed !== "object") return { ok: false, why: "not JSON" };
  const { answer, citations } = parsed;
  if (typeof answer !== "string" || !answer.trim()) return { ok: false, why: "missing answer" };
  if (answer.length > MAX_ANSWER) return { ok: false, why: "answer too long" };
  if (!Array.isArray(citations) || citations.length === 0 || citations.length > MAX_CITATIONS) {
    return { ok: false, why: "citations missing or too many" };
  }
  if (!citations.every((c) => typeof c === "string" && ctx.allowedCitations.has(c))) {
    return { ok: false, why: "unknown citation" };
  }
  if (FORBIDDEN.test(answer)) return { ok: false, why: "forbidden content" };

  for (const m of answer.matchAll(/-?\d+\.\d+/g)) {
    const n = Number(m[0]);
    if (!ctx.numbers.some((x) => Math.abs(x - n) < 1e-9)) return { ok: false, why: `number ${m[0]} not in the evidence` };
  }
  for (const m of answer.matchAll(/\bverdict\b[^.\n]{0,60}?\b(fraud|legitimate|uncertain)\b/gi)) {
    if (m[1].toLowerCase() !== ctx.verdict) return { ok: false, why: "contradicts the recorded verdict" };
  }
  if (VERDICTS.includes(ctx.verdict)) {
    const claimed = /\b(?:is|was|should be|now)\s+(?:classified|marked|judged)\s+(?:as\s+)?(fraud|legitimate|uncertain)\b/i.exec(answer);
    if (claimed && claimed[1].toLowerCase() !== ctx.verdict) return { ok: false, why: "contradicts the recorded verdict" };
  }
  return { ok: true, answer: answer.trim(), citations: citations as string[] };
}
