import { highestRoute, plural, prob, signed, TRIGGER_LABEL, isSimulatedEvidence } from "../format";
import type { AnswerBlock, Citation, CopilotAnswer, CopilotContext, CopilotProvider, IntentId } from "./types";
import { QUICK_QUESTIONS } from "./types";
import { isChangeRequest } from "./guard";

// Grounded deterministic mode: every sentence is assembled from fields of the selected case's
// answer file, trace and audit log. No model is called and nothing is generated beyond templates.

const KEYWORDS: [IntentId, RegExp][] = [
  ["what_changed", /\b(change|changed|after|additional|response|before|stop)\b/i],
  ["route", /\b(route|routes|l1|l2|auto|approv\w*)\b/i],
  ["entities", /\b(entit\w*|connected|linked|device|cards?|prior|ring)\b/i],
  ["graph_evidence", /\b(graph|evidence|support\w*|quer\w*|call|provenance)\b/i],
  ["flagged", /\b(flag\w*|why|trigger\w*|alert|start)\b/i],
];

export function matchIntent(question: string): IntentId | null {
  const exact = QUICK_QUESTIONS.find((q) => q.label.toLowerCase() === question.trim().toLowerCase());
  if (exact) return exact.id;
  for (const [id, re] of KEYWORDS) if (re.test(question)) return id;
  return null;
}

function flagged(ctx: CopilotContext): [AnswerBlock[], Citation[]] {
  const b = ctx.bundle;
  const t = b.trigger;
  const a0 = b.assessment.initial;
  const blocks: AnswerBlock[] = [
    {
      text: `${TRIGGER_LABEL[t.trigger_type] ?? t.trigger_type} opened at ${t.opened_at} (the as_of cut-off for every graph query in this case).`,
    },
    { text: `Alert text: “${t.trigger_text}”` },
  ];
  if (t.risk_score) {
    const riskEvidence = b.answer.case.evidence.find((e) => /risk score/i.test(e.claim));
    blocks.push({
      text: `The bank model scored the flagged transaction ${t.risk_score}.`,
      bullets: riskEvidence ? [{ text: riskEvidence.claim, ref: riskEvidence.ref }] : undefined,
    });
  }
  const contributing = Object.entries(a0.contributions);
  blocks.push({
    text:
      `Initial assessment: fraud probability ${prob(a0.p)} with ${plural(a0.n_support, "supporting family")} and ` +
      `${plural(a0.n_exculpatory, "exculpatory family")}; policy rules fired: ${b.policy.fired.initial.join(", ") || "none"}.`,
    bullets: contributing.length
      ? contributing.map(([name, v]) => {
          const fam = b.families.find((f) => f.name === name);
          return { text: `${name} (${signed(v)} logit): ${fam?.claim ?? "no claim recorded"}`, ref: fam?.refs[0] };
        })
      : [{ text: "No evidence family contributed; the probability is the scorer's fitted base rate." }],
  });
  return [
    blocks,
    [
      { label: "Alert row", source: "trace.case" },
      { label: "Initial assessment", source: "trace.assessment_initial" },
      { label: "Rules fired", source: "trace.policy_fired.initial" },
    ],
  ];
}

function graphEvidence(ctx: CopilotContext): [AnswerBlock[], Citation[]] {
  const b = ctx.bundle;
  const graph = b.answer.case.evidence.filter((e) => e.source === "graph");
  const other = b.answer.case.evidence.filter((e) => e.source !== "graph");
  const blocks: AnswerBlock[] = [
    {
      text:
        `${plural(b.envelopes.length, "graph call")} ran through the gateway to the official TigerGraph MCP server, each with as_of ${b.as_of} injected. ` +
        `${plural(graph.length, "graph claim")} in the answer cite one of them:`,
      bullets: graph.map((e) => ({ text: e.claim, ref: e.ref })),
    },
  ];
  if (other.length) {
    blocks.push({
      text: "Other evidence in the answer file:",
      bullets: other.map((e) => ({
        text: `${e.source}${isSimulatedEvidence(e.ref) ? " (SIMULATED)" : ""}: ${e.claim}`,
        ref: e.ref,
        simulated: isSimulatedEvidence(e.ref),
      })),
    });
  }
  blocks.push({
    text: `Final verdict: ${b.answer.case.verdict}, fraud probability ${prob(b.answer.case.fraud_probability)}, pattern ${b.answer.case.pattern}.`,
  });
  return [blocks, [{ label: "Evidence list", source: "answer.case.evidence" }, { label: "Graph calls", source: "trace.envelopes" }]];
}

function whatChanged(ctx: CopilotContext): [AnswerBlock[], Citation[]] {
  const b = ctx.bundle;
  const nba = b.answer.next_best_actions;
  const p0 = b.assessment.initial.p;
  const p1 = b.answer.case.fraud_probability;
  const before = new Set(nba.initial.map((a) => a.action));
  const after = new Set(nba.final.map((a) => a.action));
  const added = [...after].filter((a) => !before.has(a));
  const dropped = [...before].filter((a) => !after.has(a));
  const blocks: AnswerBlock[] = [];
  if (b.answer.evidence_requests.length) {
    blocks.push({
      text: "Additional evidence (SIMULATED: the dataset contains no customer replies):",
      simulated: true,
      bullets: b.answer.evidence_requests.map((r) => ({
        text: `${r.type}, requested after step ${r.asked_after_step}: ${r.assumed_response}`,
        simulated: true,
      })),
    });
  } else {
    blocks.push({ text: "No additional evidence was requested for this case." });
  }
  blocks.push({
    text: `Fraud probability ${prob(p0)} → ${prob(p1)} (${signed(p1 - p0)}). Rules fired: initial ${b.policy.fired.initial.join(", ") || "none"}; final ${b.policy.fired.final.join(", ") || "none"}.`,
  });
  blocks.push({
    text: `Actions added: ${added.join(", ") || "none"}. Actions dropped: ${dropped.join(", ") || "none"}.`,
  });
  blocks.push({ text: `Recorded what_changed: “${nba.what_changed}”` });
  blocks.push({ text: `Recorded stop_reason: “${b.answer.stop_reason}”` });
  return [
    blocks,
    [
      { label: "Evidence requests", source: "answer.evidence_requests" },
      { label: "Initial vs final actions", source: "answer.next_best_actions" },
      { label: "what_changed / stop_reason", source: "answer.next_best_actions.what_changed, answer.stop_reason" },
    ],
  ];
}

function route(ctx: CopilotContext): [AnswerBlock[], Citation[]] {
  const b = ctx.bundle;
  const final = b.answer.next_best_actions.final;
  const top = highestRoute(final);
  return [
    [
      {
        text:
          `The highest approval route among the final actions is ${top}. Routes come from the policy engine's output for each action: ` +
          "auto actions are executed only in a sandbox with no network clients; L1 and L2 actions await human approval at that level. " +
          "Execution and approvals are SIMULATED.",
        simulated: true,
      },
      {
        text: "Final actions with the route and reason recorded by the policy engine:",
        bullets: final.map((a) => ({ text: `${a.action} → ${a.route}: ${a.reason}` })),
      },
      { text: `Rules fired in the final decision: ${b.policy.fired.final.join(", ") || "none"}.` },
    ],
    [
      { label: "Final actions and routes", source: "answer.next_best_actions.final" },
      { label: "Rules fired", source: "trace.policy_fired.final" },
    ],
  ];
}

function entities(ctx: CopilotContext): [AnswerBlock[], Citation[]] {
  const b = ctx.bundle;
  const c = b.answer.case;
  const t = b.trigger;
  const f4 = b.families.find((f) => f.name === "F4_device");
  const f8 = b.families.find((f) => f.name === "F8_network");
  const bullets: NonNullable<AnswerBlock["bullets"]> = [
    { text: `Customer ${t.customer_id} owns card ${t.card_id}, which made flagged transaction ${t.flagged_txn_id}.` },
  ];
  if (f4?.claim) bullets.push({ text: `Device (F4): ${f4.claim}`, ref: f4.refs[0] });
  if (b.policy.final.shared_link && b.policy.final.shared_element) {
    bullets.push({ text: `Shared element (policy): ${b.policy.final.shared_element}` });
  }
  if (f8?.claim) bullets.push({ text: `Network (F8): ${f8.claim}`, ref: f8.refs[0] });
  bullets.push({
    text: c.connected_card_ids.length
      ? `${plural(c.connected_card_ids.length, "connected card")} in the answer: ${c.connected_card_ids.slice(0, 12).join(", ")}${c.connected_card_ids.length > 12 ? ", …" : ""}`
      : "No connected cards in the answer.",
  });
  if (c.affected_txn_ids.length) bullets.push({ text: `Affected transactions: ${c.affected_txn_ids.slice(0, 12).join(", ")}${c.affected_txn_ids.length > 12 ? ", …" : ""}` });
  bullets.push({
    text: c.similar_prior_cases.length ? `Similar prior closed cases: ${c.similar_prior_cases.join(", ")}` : "No similar prior closed cases cited.",
  });
  if (b.persist) bullets.push({ text: `Written to the graph as ${b.persist.graph_case_id} (read-back ${b.persist.read_back}).` });
  return [
    [{ text: `Entities connected to ${b.case_id}, as recorded in the answer file and trace:`, bullets }],
    [
      { label: "Answer entities", source: "answer.case" },
      { label: "Families F4/F8", source: "trace.families" },
      { label: "Shared element", source: "trace.policy_final" },
    ],
  ];
}

const HANDLERS: Record<IntentId, (ctx: CopilotContext) => [AnswerBlock[], Citation[]]> = {
  flagged,
  graph_evidence: graphEvidence,
  what_changed: whatChanged,
  route,
  entities,
};

export class DeterministicProvider implements CopilotProvider {
  readonly id = "deterministic";
  readonly label = "Evidence Copilot — grounded deterministic mode";

  async answer(question: string, intent: IntentId | null, ctx: CopilotContext): Promise<CopilotAnswer> {
    if (isChangeRequest(question, intent)) {
      return {
        intent: "unsupported",
        provider: this.id,
        mode: "refused",
        citations: [],
        blocks: [
          {
            text:
              `The Evidence Copilot is read-only. It cannot change ${ctx.bundle.case_id}'s verdict, probability, actions, routes or ` +
              "case files; those come only from the committed investigation run. It can explain them:",
            bullets: QUICK_QUESTIONS.map((q) => ({ text: q.label })),
          },
        ],
      };
    }
    const id = intent ?? matchIntent(question);
    if (!id) {
      return {
        intent: "unsupported",
        provider: this.id,
        mode: "deterministic",
        citations: [],
        blocks: [
          {
            text:
              "In grounded deterministic mode I only answer questions that the case artifacts can answer directly. Try one of these:",
            bullets: QUICK_QUESTIONS.map((q) => ({ text: q.label })),
          },
        ],
      };
    }
    const [blocks, citations] = HANDLERS[id](ctx);
    return { intent: id, blocks, citations, provider: this.id, mode: "deterministic" };
  }
}
