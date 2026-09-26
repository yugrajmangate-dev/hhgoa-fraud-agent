// Wire format between the browser Copilot and the server-side /api/copilot endpoint.
// Contains no secrets: the API key and model settings live only on the server.

export const COPILOT_ENDPOINT = "api/copilot";

export const STATUS_LLM = "LLM enabled — evidence-grounded explanation";
export const STATUS_FALLBACK = "LLM unavailable — deterministic fallback";

/** GET /api/copilot */
export interface CopilotStatus {
  llm: boolean;
  model: string | null;
}

/** POST /api/copilot */
export interface CopilotRequest {
  caseId: string;
  question: string;
  intent: string | null;
}

export type FallbackReason =
  | "no_key"
  | "bad_request"
  | "unknown_case"
  | "context_rejected"
  | "timeout"
  | "auth"
  | "quota"
  | "rate_limited"
  | "provider_error"
  | "network"
  | "invalid_response";

export type CopilotResponse =
  | { mode: "llm"; answer: string; citations: string[]; model: string }
  | { mode: "fallback"; reason: FallbackReason }
  | { mode: "refused" };

export const FALLBACK_TEXT: Record<FallbackReason, string> = {
  no_key: "no API key is configured on the server",
  bad_request: "the request was not valid",
  unknown_case: "the case bundle was not found on the server",
  context_rejected: "the case context failed the safety check",
  timeout: "the model did not answer in time",
  auth: "the provider rejected the server's credentials",
  quota: "the provider quota or credits are exhausted",
  rate_limited: "the provider rate limit was reached",
  provider_error: "the provider returned an error",
  network: "the provider could not be reached",
  invalid_response: "the model's answer failed validation",
};
