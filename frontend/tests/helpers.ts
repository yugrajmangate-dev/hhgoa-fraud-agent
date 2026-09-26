import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { CaseBundle } from "../src/types";

export const DATA_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "public", "data");

export function bundle(caseId: string): CaseBundle {
  return JSON.parse(readFileSync(path.join(DATA_DIR, "cases", `${caseId}.json`), "utf-8")) as CaseBundle;
}

export interface FetchCall {
  url: string;
  init: RequestInit;
}

/** A fetch stand-in that records calls and answers with the given responder. */
export function mockFetch(respond: (url: string, init: RequestInit) => Promise<Response> | Response) {
  const calls: FetchCall[] = [];
  const fn = (async (input: string | URL | Request, init: RequestInit = {}) => {
    const url = String(input);
    calls.push({ url, init });
    return respond(url, init);
  }) as typeof fetch;
  return { fn, calls };
}

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** OpenRouter-shaped success response whose message content is `content`. */
export const openRouterReply = (content: string) => json({ choices: [{ message: { role: "assistant", content } }] });

/** A fetch that never answers until its AbortSignal fires. */
export function hangingFetch() {
  return mockFetch(
    (_url, init) =>
      new Promise<Response>((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => reject(Object.assign(new Error("aborted"), { name: "AbortError" })));
      }),
  );
}
