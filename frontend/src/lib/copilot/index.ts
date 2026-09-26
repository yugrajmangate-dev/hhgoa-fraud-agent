import { HybridProvider } from "./hybrid";

export * from "./types";
export * from "./api";
export { matchIntent, DeterministicProvider } from "./deterministic";
export { HybridProvider } from "./hybrid";

/**
 * The Copilot always starts from the deterministic, case-grounded answer. If the server reports
 * an LLM (an API key configured on the server only), the server's validated explanation is shown
 * instead; otherwise, or on any error, the deterministic answer is used. No key reaches the browser.
 */
export function createProvider(): HybridProvider {
  return new HybridProvider();
}
