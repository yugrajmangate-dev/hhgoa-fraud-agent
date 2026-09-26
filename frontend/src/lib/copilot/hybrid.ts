import { highestRoute, prob } from "../format";
import {
  COPILOT_ENDPOINT,
  FALLBACK_TEXT,
  type CopilotRequest,
  type CopilotResponse,
  type CopilotStatus,
  type FallbackReason,
} from "./api";
import { DeterministicProvider } from "./deterministic";
import type { CopilotAnswer, CopilotContext, CopilotProvider, IntentId } from "./types";

// Browser-side provider. It holds no key and no model settings: it only calls this app's own
// /api/copilot endpoint, which decides on the server whether an LLM is available. The
// deterministic answer is always computed first and is used whenever the LLM is unavailable,
// times out, errors, or returns an answer that fails validation. Decision data is never taken
// from the model: the recorded verdict, probability and route are appended from the case file.

const STATUS_TIMEOUT_MS = 5_000;
const ANSWER_TIMEOUT_MS = 25_000;

export interface HybridOptions {
  endpoint?: string;
  fetchImpl?: typeof fetch;
  answerTimeoutMs?: number;
}

async function fetchJson<T>(fetchImpl: typeof fetch, url: string, init: RequestInit, timeoutMs: number): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetchImpl(url, { ...init, signal: controller.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

function isResponse(x: unknown): x is CopilotResponse {
  if (!x || typeof x !== "object") return false;
  const r = x as Record<string, unknown>;
  if (r.mode === "refused") return true;
  if (r.mode === "fallback") return typeof r.reason === "string";
  return r.mode === "llm" && typeof r.answer === "string" && Array.isArray(r.citations) && typeof r.model === "string";
}

export class HybridProvider implements CopilotProvider {
  readonly id = "hybrid";
  readonly label = "Evidence Copilot";
  private readonly deterministic = new DeterministicProvider();
  private readonly endpoint: string;
  private readonly fetchImpl: typeof fetch;
  private readonly answerTimeoutMs: number;
  private status: CopilotStatus | null = null;

  constructor(opts: HybridOptions = {}) {
    this.endpoint = opts.endpoint ?? `${import.meta.env.BASE_URL}${COPILOT_ENDPOINT}`;
    this.fetchImpl = opts.fetchImpl ?? ((input, init) => fetch(input, init));
    this.answerTimeoutMs = opts.answerTimeoutMs ?? ANSWER_TIMEOUT_MS;
  }

  /** Asks the server whether an LLM is configured. Any failure means "unavailable". */
  async refreshStatus(): Promise<CopilotStatus> {
    try {
      const s = await fetchJson<CopilotStatus>(this.fetchImpl, this.endpoint, { method: "GET" }, STATUS_TIMEOUT_MS);
      this.status = { llm: s?.llm === true, model: typeof s?.model === "string" ? s.model : null };
    } catch {
      this.status = { llm: false, model: null };
    }
    return this.status;
  }

  async answer(question: string, intent: IntentId | null, ctx: CopilotContext): Promise<CopilotAnswer> {
    const det = await this.deterministic.answer(question, intent, ctx);
    if (det.mode === "refused") return det; // decision-changing requests never leave the browser

    const status = this.status ?? (await this.refreshStatus());
    const fallback = (reason: FallbackReason): CopilotAnswer => ({ ...det, mode: "fallback", fallbackReason: FALLBACK_TEXT[reason] });
    if (!status.llm) return fallback("no_key");

    let res: unknown;
    try {
      const body: CopilotRequest = { caseId: ctx.bundle.case_id, question, intent };
      res = await fetchJson<unknown>(
        this.fetchImpl,
        this.endpoint,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
        this.answerTimeoutMs,
      );
    } catch (err) {
      return fallback((err as Error)?.name === "AbortError" ? "timeout" : "network");
    }
    if (!isResponse(res)) return fallback("invalid_response");
    if (res.mode === "refused") return { ...det, mode: "refused" };
    if (res.mode === "fallback") return fallback(res.reason in FALLBACK_TEXT ? res.reason : "provider_error");

    const b = ctx.bundle;
    return {
      intent: det.intent,
      provider: "server-llm",
      mode: "llm",
      model: res.model,
      blocks: [
        { text: res.answer },
        {
          text:
            `Recorded decision (from ${b.source.answer_file}, unchanged by the Copilot): verdict ${b.answer.case.verdict}, ` +
            `fraud probability ${prob(b.answer.case.fraud_probability)}, highest route ${highestRoute(b.answer.next_best_actions.final)}.`,
        },
      ],
      citations: res.citations.map((c) => ({ label: c, source: "model citation, validated on the server" })),
    };
  }
}
