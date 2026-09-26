import type { CaseBundle } from "../../types";

export type IntentId = "flagged" | "graph_evidence" | "what_changed" | "route" | "entities";

export interface QuickQuestion {
  id: IntentId;
  label: string;
}

export const QUICK_QUESTIONS: QuickQuestion[] = [
  { id: "flagged", label: "Why was this case flagged?" },
  { id: "graph_evidence", label: "What graph evidence supports the decision?" },
  { id: "what_changed", label: "What changed after additional evidence?" },
  { id: "route", label: "Why is the route Auto, L1, or L2?" },
  { id: "entities", label: "Which entities are connected?" },
];

/** One citable fact in an answer: the text shown and the artifact field it came from. */
export interface Citation {
  label: string;
  source: string;
}

export interface AnswerBlock {
  text: string;
  simulated?: boolean;
  bullets?: { text: string; ref?: string; simulated?: boolean }[];
}

/**
 * deterministic: templated from the case data (default when no LLM is configured);
 * llm: server-side model explanation that passed validation;
 * fallback: the LLM was tried but failed, so the deterministic answer is shown;
 * refused: a request to change the decision, which is never sent to any model.
 */
export type AnswerMode = "deterministic" | "llm" | "fallback" | "refused";

export interface CopilotAnswer {
  intent: IntentId | "unsupported";
  blocks: AnswerBlock[];
  citations: Citation[];
  provider: string;
  mode: AnswerMode;
  /** Why the LLM answer was not used (for mode "fallback"). */
  fallbackReason?: string;
  /** Model id reported by the server (for mode "llm"). */
  model?: string;
}

/**
 * Read-only context handed to a provider. The bundle is deep-frozen by the data loader, and
 * providers return text only: they have no way to change verdicts, probabilities, actions,
 * routes or case files.
 */
export interface CopilotContext {
  readonly bundle: Readonly<CaseBundle>;
}

export interface CopilotProvider {
  readonly id: string;
  readonly label: string;
  answer(question: string, intent: IntentId | null, ctx: CopilotContext): Promise<CopilotAnswer>;
}
