// Shared by the browser Copilot and the server-side LLM endpoint. Requests to alter the
// decision are refused rather than answered; no model is ever asked to change a case.

export const CHANGE_REQUEST =
  /\b(mark|change|set|update|override|overrule|approve|reject|delete|modify|edit|rewrite|flip|reclassify|escalate it|block it)\b/i;

/** Quick questions (which carry an intent) are always explanations, never change requests. */
export function isChangeRequest(question: string, intent: string | null | undefined): boolean {
  return !intent && CHANGE_REQUEST.test(question);
}
