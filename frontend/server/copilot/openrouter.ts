import type { FallbackReason } from "../../src/lib/copilot/api";

// Minimal OpenRouter chat-completions client. Runs only on the server: the API key is passed in
// from the server environment and is sent only in the Authorization header to OpenRouter.

export const OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions";

export interface ChatMessage {
  role: "system" | "user";
  content: string;
}

export type ProviderResult = { ok: true; content: string } | { ok: false; reason: FallbackReason };

function reasonForStatus(status: number): FallbackReason {
  if (status === 401 || status === 403) return "auth";
  if (status === 402) return "quota";
  if (status === 429) return "rate_limited";
  return "provider_error";
}

export async function callOpenRouter(opts: {
  apiKey: string;
  model: string;
  messages: ChatMessage[];
  timeoutMs: number;
  fetchImpl: typeof fetch;
}): Promise<ProviderResult> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), opts.timeoutMs);
  try {
    const res = await opts.fetchImpl(OPENROUTER_URL, {
      method: "POST",
      signal: controller.signal,
      headers: {
        Authorization: `Bearer ${opts.apiKey}`,
        "Content-Type": "application/json",
        "X-Title": "HHGoa Analyst Cockpit",
      },
      body: JSON.stringify({
        model: opts.model,
        messages: opts.messages,
        temperature: 0,
        max_tokens: 700,
        response_format: { type: "json_object" },
      }),
    });
    if (!res.ok) return { ok: false, reason: reasonForStatus(res.status) };
    const data = (await res.json()) as {
      error?: { code?: number };
      choices?: { message?: { content?: unknown } }[];
    };
    if (data.error) return { ok: false, reason: reasonForStatus(Number(data.error.code) || 500) };
    const content = data.choices?.[0]?.message?.content;
    if (typeof content !== "string" || !content.trim()) return { ok: false, reason: "invalid_response" };
    return { ok: true, content };
  } catch (err) {
    if (controller.signal.aborted || (err as Error)?.name === "AbortError") return { ok: false, reason: "timeout" };
    return { ok: false, reason: "network" };
  } finally {
    clearTimeout(timer);
  }
}
