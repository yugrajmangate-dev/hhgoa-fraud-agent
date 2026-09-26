import { describe, expect, it } from "vitest";
import { DeterministicProvider, FALLBACK_TEXT, HybridProvider } from "../src/lib/copilot";
import type { CaseBundle } from "../src/types";
import { bundle, hangingFetch, json, mockFetch } from "./helpers";

const ENDPOINT = "http://cockpit.test/api/copilot";

function frozen(id: string): CaseBundle {
  const deepFreeze = <T>(o: T): T => {
    if (o && typeof o === "object") {
      Object.freeze(o);
      Object.values(o as Record<string, unknown>).forEach(deepFreeze);
    }
    return o;
  };
  return deepFreeze(bundle(id));
}

/** Simulates this app's /api/copilot endpoint: `status` for GET, `answer` for POST. */
function server(status: unknown, answer: (body: unknown) => Response | Promise<Response>) {
  return mockFetch((_url, init) => (init.method === "POST" ? answer(JSON.parse(String(init.body))) : json(status)));
}

describe("HybridProvider: no-key fallback", () => {
  it("uses the deterministic answer and labels it as a fallback when the server has no LLM", async () => {
    const b = frozen("HHG-017");
    const s = server({ llm: false, model: null }, () => json({ mode: "llm", answer: "should not be used", citations: [], model: "x" }));
    const p = new HybridProvider({ endpoint: ENDPOINT, fetchImpl: s.fn });
    expect(await p.refreshStatus()).toEqual({ llm: false, model: null });
    const a = await p.answer("Why was this case flagged?", "flagged", { bundle: b });
    const det = await new DeterministicProvider().answer("Why was this case flagged?", "flagged", { bundle: b });
    expect(a.mode).toBe("fallback");
    expect(a.fallbackReason).toBe(FALLBACK_TEXT.no_key);
    expect(a.blocks).toEqual(det.blocks);
    expect(s.calls.filter((c) => c.init.method === "POST")).toHaveLength(0);
  });

  it("falls back when the endpoint does not exist (static hosting)", async () => {
    const f = mockFetch(() => new Response("not found", { status: 404 }));
    const p = new HybridProvider({ endpoint: ENDPOINT, fetchImpl: f.fn });
    const a = await p.answer("Which entities are connected?", "entities", { bundle: frozen("HHG-014") });
    expect(a.mode).toBe("fallback");
    expect(a.blocks[0].text).toContain("Entities connected to HHG-014");
  });
});

describe("HybridProvider: successful provider response", () => {
  it("shows the server's explanation plus the recorded decision taken from the case file", async () => {
    const b = frozen("HHG-017");
    const s = server({ llm: true, model: "test/model" }, (body) => {
      expect(body).toEqual({ caseId: "HHG-017", question: "What changed after additional evidence?", intent: "what_changed" });
      return json({ mode: "llm", answer: "The SIMULATED confirmation moved the probability from 0.34 to 0.03.", citations: ["what_changed"], model: "test/model" });
    });
    const p = new HybridProvider({ endpoint: ENDPOINT, fetchImpl: s.fn });
    const a = await p.answer("What changed after additional evidence?", "what_changed", { bundle: b });
    expect(a.mode).toBe("llm");
    expect(a.model).toBe("test/model");
    expect(a.blocks[0].text).toContain("0.34 to 0.03");
    expect(a.blocks[1].text).toContain("verdict legitimate, fraud probability 0.03, highest route auto");
    expect(a.citations.map((c) => c.label)).toEqual(["what_changed"]);
    // The request carried no key or model settings from the browser.
    const post = s.calls.find((c) => c.init.method === "POST")!;
    expect(JSON.stringify(post.init)).not.toMatch(/Authorization|OPENROUTER|Bearer/i);
  });
});

describe("HybridProvider: refusal of decision-changing requests", () => {
  it("refuses in the browser without any network call, and case data is unchanged", async () => {
    const b = frozen("HHG-017");
    const s = server({ llm: true, model: "test/model" }, () => json({ mode: "llm", answer: "x", citations: ["decision"], model: "m" }));
    const p = new HybridProvider({ endpoint: ENDPOINT, fetchImpl: s.fn });
    const a = await p.answer("Please mark this case as fraud and block the card", null, { bundle: b });
    expect(a.mode).toBe("refused");
    expect(a.blocks[0].text).toContain("read-only");
    expect(s.calls).toHaveLength(0);
    expect(b.answer.case.verdict).toBe("legitimate");
    expect(b.answer.case.fraud_probability).toBe(0.03);
  });
});

describe("HybridProvider: error fallback", () => {
  const deterministicFirstLine = async (b: CaseBundle) =>
    (await new DeterministicProvider().answer("Why is the route Auto, L1, or L2?", "route", { bundle: b })).blocks[0].text;

  for (const reason of ["timeout", "quota", "rate_limited", "invalid_response", "provider_error"] as const) {
    it(`uses the deterministic answer when the server reports ${reason}`, async () => {
      const b = frozen("HHG-014");
      const s = server({ llm: true, model: "m" }, () => json({ mode: "fallback", reason }));
      const a = await new HybridProvider({ endpoint: ENDPOINT, fetchImpl: s.fn }).answer("Why is the route Auto, L1, or L2?", "route", { bundle: b });
      expect(a.mode).toBe("fallback");
      expect(a.fallbackReason).toBe(FALLBACK_TEXT[reason]);
      expect(a.blocks[0].text).toBe(await deterministicFirstLine(b));
    });
  }

  it("times out in the browser and falls back", async () => {
    const hang = hangingFetch();
    const f = mockFetch((url, init) => (init.method === "POST" ? hang.fn(url, init) : json({ llm: true, model: "m" })));
    const a = await new HybridProvider({ endpoint: ENDPOINT, fetchImpl: f.fn, answerTimeoutMs: 50 }).answer(
      "Why was this case flagged?",
      "flagged",
      { bundle: frozen("HHG-017") },
    );
    expect(a.mode).toBe("fallback");
    expect(a.fallbackReason).toBe(FALLBACK_TEXT.timeout);
  });

  it("falls back on a malformed server payload or HTTP error", async () => {
    for (const reply of [json({ mode: "llm", answer: 42 }), json({ unexpected: true }), json({}, 500)]) {
      const s = server({ llm: true, model: "m" }, () => reply);
      const a = await new HybridProvider({ endpoint: ENDPOINT, fetchImpl: s.fn }).answer("Why was this case flagged?", "flagged", {
        bundle: frozen("HHG-017"),
      });
      expect(a.mode).toBe("fallback");
    }
  });
});
