import { DeterministicProvider } from "./deterministic";
import type { CopilotAnswer, CopilotContext, CopilotProvider, IntentId } from "./types";

export * from "./types";
export { matchIntent } from "./deterministic";

/**
 * Placeholder for a future LLM-backed provider. It is NOT wired into the UI and makes no calls.
 *
 * If it is ever enabled, it must call a server-side endpoint that holds the API key (never the
 * browser), send only the selected case's exported artifacts as context, and return text only.
 * The UI must keep treating answers as commentary: they never change verdicts, probabilities,
 * actions, routes or case files.
 */
export class ServerLlmProvider implements CopilotProvider {
  readonly id = "server-llm";
  readonly label = "Evidence Copilot — LLM mode (not configured)";

  constructor(readonly endpoint: string) {}

  async answer(_question: string, _intent: IntentId | null, _ctx: CopilotContext): Promise<CopilotAnswer> {
    void _question;
    void _intent;
    void _ctx;
    throw new Error("LLM mode is not configured in this build. The cockpit runs in grounded deterministic mode only.");
  }
}

/** The only provider this build uses. */
export function createProvider(): CopilotProvider {
  return new DeterministicProvider();
}
