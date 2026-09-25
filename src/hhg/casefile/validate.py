"""Answer-file validation: README schema (ARCHITECTURE.md §11.1) plus semantic validators
(§11.3). A non-empty problem list blocks the file and graph write."""

import json
import re
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator

from hhg import config
from hhg.policy.engine import ORDER, PolicyInput, decide, route

SCHEMA = json.loads((Path(__file__).parent / "case_answer.schema.json").read_text(encoding="utf-8"))
RULE_TAG = re.compile(r"R(10|[1-9])\b|§3a|§3b|§6")
ID_TOKEN = re.compile(r"\b(\d{7}|C\d{5}-K\d+|C\d{5}|CC-\d{4}|HHG-\d{3})\b")


def sentences(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!])\s+(?=[A-Z0-9$])", text.strip()) if s])


def schema_errors(answer: dict) -> list:
    return [f"schema: {'/'.join(map(str, e.absolute_path))}: {e.message}"
            for e in Draft202012Validator(SCHEMA).iter_errors(answer)]


def semantic_errors(answer: dict, ctx: dict) -> list:
    """ctx: as_of, txn_ts {id: ts str}, txn_amt {id: amt}, known_ids (set), retrieved_closed (set),
    flagged, policy_initial (PolicyInput dict), policy_final, tool_calls, envelope_refs (set)."""
    p, case, sar, nba = [], answer["case"], answer["sar"], answer["next_best_actions"]
    as_of = ctx["as_of"]
    # V-IDS: every transaction referenced is visible at as_of
    for tid in case["affected_txn_ids"] + ([case["first_suspicious_txn_id"]] if case["first_suspicious_txn_id"] else []):
        ts = ctx["txn_ts"].get(tid)
        if ts is None:
            p.append(f"V-IDS: transaction {tid} not returned by any tool call")
        elif ts > as_of:
            p.append(f"V-IDS: transaction {tid} ts {ts} after as_of {as_of}")
    for cid in case["connected_card_ids"] + sar["subjects"]:
        if cid not in ctx["known_ids"]:
            p.append(f"V-IDS: {cid} not seen in this case's tool results")
    # V-EXPOSURE
    total = round(sum(abs(ctx["txn_amt"][t]) for t in case["affected_txn_ids"] if t in ctx["txn_amt"]), 2)
    if abs(total - case["exposure_usd"]) > 0.005:
        p.append(f"V-EXPOSURE: exposure {case['exposure_usd']} != sum {total}")
    # V-EPISODE
    if case["verdict"] == "fraud" and ctx["flagged"] not in case["affected_txn_ids"]:
        p.append("V-EPISODE: fraud verdict without the flagged transaction in affected_txn_ids")
    if case["affected_txn_ids"]:
        first = min(case["affected_txn_ids"], key=lambda t: (ctx["txn_ts"].get(t, "9"), t))
        if case["first_suspicious_txn_id"] != first:
            p.append(f"V-EPISODE: first_suspicious_txn_id should be {first}")
    elif case["first_suspicious_txn_id"]:
        p.append("V-EPISODE: first_suspicious_txn_id set with no affected transactions")
    # V-SAR
    final_actions = [a["action"] for a in nba["final"]]
    if sar["file"] != ("FILE_REPORT" in final_actions):
        p.append("V-SAR: sar.file disagrees with FILE_REPORT in final actions")
    if sar["file"]:
        if abs(sar["total_amount_usd"] - case["exposure_usd"]) > 0.005:
            p.append("V-SAR: total_amount_usd != exposure_usd")
        dates = sorted(ctx["txn_ts"][t][:10] for t in case["affected_txn_ids"])
        if dates and sar["activity_dates"] != [dates[0], dates[-1]]:
            p.append(f"V-SAR: activity_dates should be {[dates[0], dates[-1]]}")
        n = sentences(sar["narrative"])
        if not 6 <= n <= 12:
            p.append(f"V-SAR: narrative has {n} sentences (6-12 required)")
    # V-NBA
    for phase in ("initial", "final"):
        names = [a["action"] for a in nba[phase]]
        if names != [a for a in ORDER if a in names]:
            p.append(f"V-NBA: {phase} not in canonical order")
        for a in nba[phase]:
            if a["route"] != route(a["action"], case["exposure_usd"]):
                p.append(f"V-NBA: wrong route for {a['action']} in {phase}")
            if not RULE_TAG.search(a["reason"]):
                p.append(f"V-NBA: reason without rule citation in {phase}: {a['action']}")
    if not answer["evidence_requests"]:
        if nba["final"] != nba["initial"]:
            p.append("V-NBA: no evidence requested but final != initial")
        if nba["what_changed"] != "nothing":
            p.append("V-NBA: what_changed must be 'nothing' when final == initial")
    # V-POLICY: re-derive both lists from the recorded inputs
    for phase, key in (("initial", "policy_initial"), ("final", "policy_final")):
        if decide(PolicyInput(**ctx[key])).actions != nba[phase]:
            p.append(f"V-POLICY: {phase} actions do not reproduce from recorded policy input")
    # V-MEMORY
    extra = set(case["similar_prior_cases"]) - ctx["retrieved_closed"]
    if extra:
        p.append(f"V-MEMORY: not retrieved: {sorted(extra)}")
    # V-EVIDENCE
    for ev in case["evidence"]:
        if ev["source"] == "graph" and ev["ref"] not in ctx["envelope_refs"]:
            p.append(f"V-EVIDENCE: unknown graph ref {ev['ref']}")
    # V-TEXT: IDs in free text must be known
    for field in ("summary", "stop_reason"):
        for tok in ID_TOKEN.findall(answer[field] if field == "stop_reason" else case[field]):
            if tok not in ctx["known_ids"] and tok != answer["case_id"]:
                p.append(f"V-TEXT: unknown ID {tok} in {field}")
    if not 2 <= sentences(case["summary"]) <= 6:
        p.append("V-TEXT: summary must be 2-6 sentences")
    # V-STATUS
    expected = ("escalated" if "ESCALATE_TO_ANALYST" in final_actions else
                {"fraud": "closed_fraud", "legitimate": "closed_legitimate"}.get(case["verdict"], "open"))
    if case["status"] != expected:
        p.append(f"V-STATUS: status should be {expected}")
    # V-COUNTS
    if answer["tool_calls"] != ctx["tool_calls"]:
        p.append("V-COUNTS: tool_calls does not match the audit log")
    return p


def validate(answer: dict, ctx: dict) -> list:
    errs = schema_errors(answer)
    return errs if errs else semantic_errors(answer, ctx)
