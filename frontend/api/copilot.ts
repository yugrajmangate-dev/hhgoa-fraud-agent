import path from "node:path";
import { fileBundleLoader } from "../server/copilot/bundles";
import { getStatus, handleCopilot, readServerConfig } from "../server/copilot/handler";

// Vercel serverless function (Web-standard handlers) for /api/copilot. Set OPENROUTER_API_KEY and,
// optionally, OPENROUTER_MODEL as server environment variables in the Vercel project; never as
// VITE_* variables. Without a key, GET reports the LLM as unavailable and POST returns a fallback,
// so the static app keeps answering deterministically. Not exercised in a live deployment yet.

const loadBundle = fileBundleLoader(path.join(process.cwd(), "public", "data"));
const json = (body: unknown) =>
  new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });

export function GET(): Response {
  return json(getStatus(readServerConfig(process.env)));
}

export async function POST(request: Request): Promise<Response> {
  const text = await request.text();
  if (text.length > 8 * 1024) return json({ mode: "fallback", reason: "bad_request" });
  let body: unknown = null;
  try {
    body = JSON.parse(text);
  } catch {
    return json({ mode: "fallback", reason: "bad_request" });
  }
  try {
    return json(await handleCopilot(body, { config: readServerConfig(process.env), loadBundle }));
  } catch {
    return json({ mode: "fallback", reason: "provider_error" });
  }
}
