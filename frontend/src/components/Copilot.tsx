import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import type { CaseBundle } from "../types";
import {
  createProvider,
  QUICK_QUESTIONS,
  STATUS_FALLBACK,
  STATUS_LLM,
  type CopilotAnswer,
  type CopilotStatus,
  type IntentId,
} from "../lib/copilot";

function modeLabel(a: CopilotAnswer): { text: string; cls: string } {
  switch (a.mode) {
    case "llm":
      return { text: `${STATUS_LLM}${a.model ? ` (${a.model})` : ""}`, cls: "mode-llm" };
    case "fallback":
      return { text: `${STATUS_FALLBACK}${a.fallbackReason ? `: ${a.fallbackReason}` : ""}`, cls: "mode-fallback" };
    case "refused":
      return { text: "Refused: decision data is read-only (not sent to any model)", cls: "mode-refused" };
    default:
      return { text: "Grounded deterministic answer", cls: "mode-det" };
  }
}
import { Ref, Sim } from "./ui";

interface Turn {
  id: number;
  question: string;
  answer: CopilotAnswer | null;
  error?: string;
}

export function Copilot({ b }: { b: CaseBundle }) {
  const provider = useMemo(() => createProvider(), []);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const nextId = useRef(1);
  const endRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<CopilotStatus | null>(null);

  useEffect(() => {
    let live = true;
    void provider.refreshStatus().then((s) => {
      if (live) setStatus(s);
    });
    return () => {
      live = false;
    };
  }, [provider]);

  useEffect(() => {
    setTurns([]);
  }, [b.case_id]);
  useEffect(() => {
    if (turns.length) endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [turns]);

  async function ask(question: string, intent: IntentId | null) {
    const q = question.trim();
    if (!q) return;
    const id = nextId.current++;
    setTurns((t) => [...t, { id, question: q, answer: null }]);
    try {
      const answer = await provider.answer(q, intent, { bundle: b });
      setTurns((t) => t.map((x) => (x.id === id ? { ...x, answer } : x)));
    } catch (err) {
      setTurns((t) => t.map((x) => (x.id === id ? { ...x, error: (err as Error).message } : x)));
    }
  }

  function onSubmit(ev: FormEvent) {
    ev.preventDefault();
    const q = draft;
    setDraft("");
    void ask(q, null);
  }

  return (
    <section className="panel copilot" aria-labelledby="copilot-title">
      <header className="panel-head">
        <div>
          <h2 id="copilot-title">Evidence Copilot</h2>
          <p className={`copilot-status ${status?.llm ? "is-llm" : "is-fallback"}`} role="status">
            <span className="dot" aria-hidden="true" />
            {status === null ? "Checking for a server-side LLM…" : status.llm ? `${STATUS_LLM}${status.model ? ` · ${status.model}` : ""}` : STATUS_FALLBACK}
          </p>
          <p className="panel-kicker">
            {status?.llm
              ? `A server-side model explains ${b.case_id}'s recorded evidence only; answers that fail validation fall back to the grounded deterministic mode.`
              : `Grounded deterministic mode: answers are assembled from ${b.case_id}'s answer file, trace and audit log.`}{" "}
            The copilot cannot change verdicts, probabilities, actions, routes or case files.
          </p>
        </div>
      </header>

      <div className="quick" aria-label="Quick questions">
        {QUICK_QUESTIONS.map((q) => (
          <button key={q.id} type="button" className="quick-q" onClick={() => void ask(q.label, q.id)}>
            {q.label}
          </button>
        ))}
      </div>

      <div className="chat" aria-live="polite">
        {turns.length === 0 && <p className="muted chat-empty">Pick a question above, or type one below.</p>}
        {turns.map((t) => (
          <div key={t.id} className="turn">
            <div className="msg msg-q">{t.question}</div>
            <div className="msg msg-a">
              {t.error ? (
                <p className="bad">{t.error}</p>
              ) : !t.answer ? (
                <p className="muted">Reading the case artifacts…</p>
              ) : (
                <>
                  <p className={`ans-mode ${modeLabel(t.answer).cls}`}>{modeLabel(t.answer).text}</p>
                  {t.answer.blocks.map((blk, i) => (
                    <div key={i} className={`ans-block ${blk.simulated ? "is-sim" : ""}`}>
                      <p>
                        {blk.simulated && <Sim />} {blk.text}
                      </p>
                      {blk.bullets && (
                        <ul>
                          {blk.bullets.map((bl, j) => (
                            <li key={j}>
                              {bl.simulated && <Sim />} {bl.text}
                              {bl.ref && (
                                <div>
                                  <Ref>{bl.ref}</Ref>
                                </div>
                              )}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ))}
                  {t.answer.citations.length > 0 && (
                    <p className="cites">
                      Sources:{" "}
                      {t.answer.citations.map((c, i) => (
                        <span key={i} title={c.source}>
                          {c.label}
                          <code>{c.source}</code>
                        </span>
                      ))}
                    </p>
                  )}
                </>
              )}
            </div>
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <form className="chat-input" onSubmit={onSubmit}>
        <label htmlFor="copilot-q" className="sr-only">
          Ask about this case
        </label>
        <input
          id="copilot-q"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={`Ask about ${b.case_id} (grounded answers only)`}
          autoComplete="off"
          maxLength={300}
        />
        <button type="submit" className="btn btn-primary" disabled={!draft.trim()}>
          Ask
        </button>
      </form>
    </section>
  );
}
