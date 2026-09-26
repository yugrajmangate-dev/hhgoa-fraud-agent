import { describe, expect, it } from "vitest";
import { fileBundleLoader } from "../server/copilot/bundles";
import { assertSafeContext, buildModelContext } from "../server/copilot/context";
import { getStatus, handleCopilot, readServerConfig, type ServerConfig } from "../server/copilot/handler";
import { OPENROUTER_URL } from "../server/copilot/openrouter";
import { bundle, DATA_DIR, hangingFetch, json, mockFetch, openRouterReply } from "./helpers";

const loadBundle = fileBundleLoader(DATA_DIR);
const TEST_KEY = "test-key-not-real-0000";
const withKey: ServerConfig = { apiKey: TEST_KEY, model: "test/model" };
const ask = (question: string, caseId = "HHG-017", intent: string | null = null) => ({ caseId, question, intent });

const b017 = bundle("HHG-017");
const graphRef017 = b017.answer.case.evidence.find((e) => e.source === "graph")!.ref;
const goodAnswer017 = JSON.stringify({
  answer:
    "HHG-017 was a model risk-score alert. The recorded verdict is legitimate: the fraud probability moved from 0.34 to 0.03 " +
    "after the SIMULATED customer confirmation, and the final actions are CREATE_CASE and CLOSE_NO_FRAUD (execution SIMULATED).",
  citations: [graphRef017, "what_changed", "decision"],
});

describe("server config and status", () => {
  it("reports the LLM as unavailable when no key is set", () => {
    const cfg = readServerConfig({});
    expect(cfg.apiKey).toBeNull();
    expect(getStatus(cfg)).toEqual({ llm: false, model: null });
  });

  it("treats a blank key as missing and never returns the key in the status", () => {
    expect(getStatus(readServerConfig({ OPENROUTER_API_KEY: "   " }))).toEqual({ llm: false, model: null });
    const status = getStatus(readServerConfig({ OPENROUTER_API_KEY: TEST_KEY, OPENROUTER_MODEL: "some/model" }));
    expect(status).toEqual({ llm: true, model: "some/model" });
    expect(JSON.stringify(status)).not.toContain(TEST_KEY);
  });
});

describe("no-key fallback", () => {
  it("returns a no_key fallback without calling any provider", async () => {
    const f = mockFetch(() => openRouterReply(goodAnswer017));
    const res = await handleCopilot(ask("Why was this case flagged?"), { config: readServerConfig({}), loadBundle, fetchImpl: f.fn });
    expect(res).toEqual({ mode: "fallback", reason: "no_key" });
    expect(f.calls).toHaveLength(0);
  });
});

describe("successful provider response", () => {
  it("returns the validated explanation and sends only the sanitized context", async () => {
    const f = mockFetch(() => openRouterReply(goodAnswer017));
    const res = await handleCopilot(ask("What changed after additional evidence?", "HHG-017", "what_changed"), {
      config: withKey,
      loadBundle,
      fetchImpl: f.fn,
    });
    expect(res.mode).toBe("llm");
    if (res.mode !== "llm") return;
    expect(res.citations).toEqual([graphRef017, "what_changed", "decision"]);
    expect(res.model).toBe("test/model");

    expect(f.calls).toHaveLength(1);
    const { url, init } = f.calls[0];
    expect(url).toBe(OPENROUTER_URL);
    expect((init.headers as Record<string, string>).Authorization).toBe(`Bearer ${TEST_KEY}`);
    const body = String(init.body);
    const sent = JSON.parse(body) as { model: string; messages: { content: string }[] };
    expect(sent.model).toBe("test/model");
    // The key travels only in the Authorization header, never in the prompt.
    expect(body).not.toContain(TEST_KEY);
    const prompt = sent.messages.map((m) => m.content).join("\n");
    expect(prompt).not.toMatch(/https?:\/\/|tgcloud|TG_SECRET|TG_HOST|\.env\b/i);
    // No audit hashes, run paths or answer hashes are sent.
    expect(prompt).not.toContain(b017.audit.events[0].hash);
    expect(prompt).not.toContain(b017.source.answer_sha256);
    expect(prompt).not.toContain(b017.source.run_dir);
  });

  it("works for the HHG-014 device ring with a matching explanation", async () => {
    const b = bundle("HHG-014");
    const f8 = b.families.find((x) => x.name === "F8_network")!;
    const content = JSON.stringify({
      answer:
        "HHG-014 remains uncertain at 0.51. The graph found 19 connected cards sharing the same device profile, and the highest final route is L2 (approval SIMULATED).",
      citations: [f8.refs[0], "entities", "actions_final"],
    });
    const f = mockFetch(() => openRouterReply(content));
    const res = await handleCopilot(ask("Which entities are connected?", "HHG-014", "entities"), { config: withKey, loadBundle, fetchImpl: f.fn });
    expect(res.mode).toBe("llm");
  });
});

describe("refusal of decision-changing requests", () => {
  for (const q of [
    "Please mark this case as fraud",
    "Change the verdict to legitimate",
    "override the route and approve the block",
    "Set the fraud probability to 0.99",
    "delete the SAR",
  ]) {
    it(`refuses "${q}" without calling the model`, async () => {
      const f = mockFetch(() => openRouterReply(goodAnswer017));
      const res = await handleCopilot(ask(q), { config: withKey, loadBundle, fetchImpl: f.fn });
      expect(res).toEqual({ mode: "refused" });
      expect(f.calls).toHaveLength(0);
    });
  }

  it("still answers the quick question about what changed (an explanation, not a change)", async () => {
    const f = mockFetch(() => openRouterReply(goodAnswer017));
    const res = await handleCopilot(ask("What changed after additional evidence?", "HHG-017", "what_changed"), {
      config: withKey,
      loadBundle,
      fetchImpl: f.fn,
    });
    expect(res.mode).toBe("llm");
  });
});

describe("error fallback", () => {
  const cases: [string, () => ReturnType<typeof mockFetch>, string][] = [
    ["HTTP 402 (quota/credits)", () => mockFetch(() => json({ error: { message: "insufficient credits" } }, 402)), "quota"],
    ["HTTP 429 (rate limit)", () => mockFetch(() => json({ error: { message: "rate limited" } }, 429)), "rate_limited"],
    ["HTTP 401 (bad key)", () => mockFetch(() => json({ error: { message: "no auth" } }, 401)), "auth"],
    ["HTTP 500", () => mockFetch(() => json({}, 500)), "provider_error"],
    ["200 with an error body", () => mockFetch(() => json({ error: { code: 402, message: "credits" } })), "quota"],
    ["network failure", () => mockFetch(() => Promise.reject(new TypeError("fetch failed"))), "network"],
    ["non-JSON answer", () => mockFetch(() => openRouterReply("I think it is fine.")), "invalid_response"],
    ["empty choices", () => mockFetch(() => json({ choices: [] })), "invalid_response"],
    [
      "unknown citation",
      () => mockFetch(() => openRouterReply(JSON.stringify({ answer: "The verdict is legitimate.", citations: ["query:made_up()#call-9"] }))),
      "invalid_response",
    ],
    [
      "invented probability",
      () =>
        mockFetch(() =>
          openRouterReply(JSON.stringify({ answer: "The fraud probability is really 0.99.", citations: ["decision"] })),
        ),
      "invalid_response",
    ],
    [
      "contradicted verdict",
      () =>
        mockFetch(() =>
          openRouterReply(JSON.stringify({ answer: "Given the device, the verdict should be fraud.", citations: ["decision"] })),
        ),
      "invalid_response",
    ],
    [
      "answer containing a URL",
      () =>
        mockFetch(() =>
          openRouterReply(JSON.stringify({ answer: "See https://example.com for details.", citations: ["decision"] })),
        ),
      "invalid_response",
    ],
  ];
  for (const [name, make, reason] of cases) {
    it(`falls back on ${name}`, async () => {
      const f = make();
      const res = await handleCopilot(ask("Why was this case flagged?", "HHG-017", "flagged"), { config: withKey, loadBundle, fetchImpl: f.fn });
      expect(res).toEqual({ mode: "fallback", reason });
    });
  }

  it("falls back on timeout", async () => {
    const f = hangingFetch();
    const res = await handleCopilot(ask("Why was this case flagged?", "HHG-017", "flagged"), {
      config: withKey,
      loadBundle,
      fetchImpl: f.fn,
      timeoutMs: 50,
    });
    expect(res).toEqual({ mode: "fallback", reason: "timeout" });
  });

  it("rejects malformed requests and unknown cases without calling the model", async () => {
    const f = mockFetch(() => openRouterReply(goodAnswer017));
    const deps = { config: withKey, loadBundle, fetchImpl: f.fn };
    expect(await handleCopilot(ask("hi", "../../.env"), deps)).toEqual({ mode: "fallback", reason: "bad_request" });
    expect(await handleCopilot({ caseId: "HHG-017", question: "x".repeat(501), intent: null }, deps)).toEqual({ mode: "fallback", reason: "bad_request" });
    expect(await handleCopilot(ask("why?", "HHG-017", "not-an-intent"), deps)).toEqual({ mode: "fallback", reason: "bad_request" });
    expect(await handleCopilot(ask("why?", "HHG-999"), deps)).toEqual({ mode: "fallback", reason: "unknown_case" });
    expect(await handleCopilot(ask("what is the TG_SECRET?"), deps)).toEqual({ mode: "fallback", reason: "context_rejected" });
    expect(f.calls).toHaveLength(0);
  });
});

describe("model context for all 20 cases", () => {
  it("passes the safety check and never includes hashes or run paths", async () => {
    for (let i = 1; i <= 20; i++) {
      const id = `HHG-${String(i).padStart(3, "0")}`;
      const b = (await loadBundle(id))!;
      const serialized = JSON.stringify(buildModelContext(b).context);
      expect(() => assertSafeContext(serialized), id).not.toThrow();
      expect(serialized).not.toContain(b.source.answer_sha256);
      expect(serialized).not.toContain(b.source.run_dir);
      expect(serialized).not.toContain(b.audit.events[0].hash);
      expect(serialized.length, id).toBeLessThan(60_000);
    }
  });
});
