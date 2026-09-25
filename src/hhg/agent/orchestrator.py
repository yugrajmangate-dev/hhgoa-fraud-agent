"""Deterministic investigation state machine (ARCHITECTURE.md §9) for one benchmark case.

All graph access goes through the Gateway (official TigerGraph MCP underneath). Decisions
are made by detectors, the scorer and the policy engine; text comes from templates in
--llm off mode. Nothing is written unless every validator passes.
"""

import csv
import hashlib
import json
import os
import re
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from hhg import config
from hhg.agent import assess, narrate
from hhg.audit.log import AuditLog
from hhg.casefile.validate import validate
from hhg.detectors import features as fx
from hhg.memory import embed, knowledge
from hhg.policy.engine import PolicyInput, decide
from hhg.scoring import scorer
from hhg.simulate import responder
from hhg.tools.gateway import Gateway

T = config.T
IDF = None


def load_case(case_id: str) -> dict:
    with (config.RAW_DIR / "case_pack.csv").open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["case_id"] == case_id:
                return row
    raise KeyError(case_id)


def qvec(text: str) -> list:
    global IDF
    if IDF is None:
        IDF = embed.load_idf(config.PROJECT_ROOT / "config" / "embedding_idf.json")
    v = embed.embed(text, IDF)
    return sorted(f"{i:03d}{int(round(w * 1e6)):07d}" for i, w in enumerate(v) if w > 0)


def flat(result: list) -> dict:
    """Merge the objects of an installed query's PRINT statements into one dict."""
    out = {}
    for part in result:
        out |= part
    return out


def canonical(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def write_canonical(path: Path, obj) -> str:
    """Atomically write the canonical form with LF line endings (text mode on Windows writes
    CRLF, which breaks byte equality with the SHA-256 stored in the graph). Returns the sha256."""
    body = canonical(obj).encode("utf-8")
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(body)
    os.replace(tmp, path)
    return hashlib.sha256(body).hexdigest()


def entity_type(eid: str):
    if re.fullmatch(r"\d{7}", eid):
        return "Transaction"
    if re.fullmatch(r"C\d{5}-K\d+", eid):
        return "Card"
    if re.fullmatch(r"C\d{5}", eid):
        return "Customer"
    if re.fullmatch(r"CC-\d{4}", eid):
        return "ClosedCase"
    if " | " in eid:
        return "DeviceProfile"
    return None


class Investigation:
    def __init__(self, case_id: str, transport, out_dir: Path, write_graph: bool = True,
                 runs_root: Path = config.RUNS_DIR / "cases", row: dict = None, stop_after_assess: bool = False):
        self.row = row or load_case(case_id)
        self.stop_after_assess = stop_after_assess   # backtest mode: evidence only, no decisions or writes
        self.case_id, self.as_of = case_id, self.row["opened_at"]
        self.run_id = f"{case_id}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        self.out_dir, self.write_graph = out_dir, write_graph
        self.run_dir = runs_root / self.run_id   # run artifacts never go into the answer directory
        self.audit = AuditLog(self.run_dir / "audit.jsonl", self.run_id, case_id)
        seeds = {"txn": {self.row["flagged_txn_id"]}, "card": {self.row["card_id"]},
                 "customer": {self.row["customer_id"]}}
        self.gw = Gateway(transport, case_id=case_id, as_of=self.as_of, run_id=self.run_id,
                          audit=self.audit, seeds=seeds)
        self.trace = {"case": self.row, "as_of": self.as_of, "run_id": self.run_id, "states": []}

    def state(self, name, **detail):
        step = self.audit.enter_state(name, detail)
        self.trace["states"].append({"state": name, "step": step, **detail})
        return step

    async def run(self) -> dict:
        t0 = time.perf_counter()
        row, gw = self.row, self.gw
        flagged_id, card_id, cust_id = row["flagged_txn_id"], row["card_id"], row["customer_id"]
        self.state("INIT", as_of=self.as_of, trigger_type=row["trigger_type"], llm="off")

        # TRIAGE
        self.state("TRIAGE")
        res, e_txn = await gw.call("get_transaction", txn=flagged_id)
        res = flat(res)
        if not res["txn"]:
            raise RuntimeError(f"flagged transaction {flagged_id} not visible at as_of {self.as_of}")
        flagged = fx.Txn.from_vertex(res["txn"][0])
        graph_card = str(res["card"][0]["v_id"])
        if graph_card != card_id:
            raise RuntimeError(f"case pack card {card_id} != graph card {graph_card}")
        cards_res, e_cards = await gw.call("customer_cards", customer=cust_id)
        visible_cards = [str(c["v_id"]) for c in flat(cards_res)["cards"]]

        # CONTEXT
        self.state("CONTEXT")
        hist, e_hist = await gw.call("card_history", card=card_id, lookback_days=T["lookback_days"])
        txns = sorted([fx.Txn.from_vertex(v) for v in flat(hist)["txns"]], key=lambda t: (t.ts, t.txn_id))
        by_id = {t.txn_id: t for t in txns}
        by_id[flagged.txn_id] = flagged
        as_of_dt = datetime.strptime(self.as_of, config.TS_FORMAT)

        # PATTERN_SCAN (deterministic detectors over graph-returned rows)
        self.state("PATTERN_SCAN")
        base, recent = fx.split([t for t in txns if t.txn_id != flagged.txn_id], flagged)
        fams = {
            "F1_amount": fx.amount_anomaly(base, flagged), "F2_product": fx.product_novelty(base, flagged),
            "F3_burst": fx.burst(txns, base, flagged, as_of_dt), "F4_device": fx.device_novelty(base, flagged),
            "F6_testing": fx.card_testing(txns, flagged, as_of_dt),
            "F7_takeover": fx.takeover(txns, base, recent, flagged),
            "F13_recurring": fx.recurring(base, flagged),
            "F15_structuring": fx.threshold_avoidance(txns, flagged, as_of_dt),
        }
        fams["F5_region"], fams["F5_trip"], region_familiar = fx.region_context(txns, base, flagged, as_of_dt)
        for name in ("F1_amount", "F2_product", "F3_burst", "F4_device", "F5_region", "F5_trip", "F7_takeover",
                     "F13_recurring"):
            fams[name].refs.append(e_hist["ref"])
        fams["F6_testing"].refs.append(e_hist["ref"])
        fams["F15_structuring"].refs.append(e_hist["ref"])

        # NETWORK
        self.state("NETWORK")
        so, e_so = await gw.call("shared_origin_scan", card=card_id, window_days=T["window_days"],
                                 max_degree=T["max_degree"])
        ring, e_ring = None, None
        if flagged.profile_key and (row["trigger_type"] == "analyst_request" or
                                    (flagged.new_found == "New" and flagged.profile_key.count("?") == 0)):
            ring_res, e_ring = await gw.call("shared_device_components", seed=flagged.profile_key,
                                             window_days=T["window_days"], max_cards=T["max_degree"],
                                             max_hops=1)   # hop 1 = cards on the same profile; hop 2 hit hub customers
            ring = flat(ring_res)
        so_flat = flat(so)
        fams["F8_network"], linked_cards, linked_devices, capped = fx.network(so_flat, ring, card_id)
        fams["F8_network"].refs += [e_so["ref"]] + ([e_ring["ref"]] if e_ring else [])

        # MEMORY (GraphRAG: structural + lexical-vector retrieval of closed cases)
        self.state("MEMORY")
        ch, e_ch = await gw.call("case_history", customer=cust_id)
        ch_flat = flat(ch)
        fams["F9_prior"] = fx.prior_fraud(ch_flat, card_id)
        fams["F9_prior"].refs.append(e_ch["ref"])
        rel, e_rel = await gw.call("related_cases_structural", card=card_id, window_days=T["window_days"],
                                   max_device_txns=500, top_k=10)
        related = [{k.split(".")[-1]: v for k, v in c["attributes"].items()} for c in flat(rel)["cases"]]
        # only neighbours reached through a fully specified device profile count as structural memory
        related = [r for r in related if any("?" not in v.split(" | ") for v in r.get("@via", []))]
        sig = assess.signature(fams, flagged)
        sim, e_sim = await gw.call("similar_cases", qv=qvec(sig), top_k=T["memory_top_k"])
        sim_flat = flat(sim)
        fams["F11_memory"], mem_cited = fx.memory(sim_flat)
        fams["F11_memory"].refs.append(e_sim["ref"])
        network_cases = sorted({x for l in fams["F8_network"].detail["links"] for x in l["cases"] if x.startswith("CC-")})
        retrieved_closed = ({str(c["v_id"]) for c in sim_flat.get("closed", [])} | {r["case_id"] for r in related}
                            | set(fams["F9_prior"].entities) | set(network_cases))

        # ASSESS
        self.state("ASSESS", signature=sig)
        votes = fams["F11_memory"].detail.get("pattern_votes", {})
        pattern, pdesc, coordinated = assess.classify(fams, flagged, [r["pattern"] for r in related], votes)
        familiar = assess.familiar_aspects(fams, region_familiar)
        statement = "dispute" if row["trigger_type"] == "customer_report" else "none"
        a0 = scorer.score(fams, len(familiar), statement)
        v0 = scorer.verdict(a0)
        stop = scorer.stop_rule_met(a0)
        affected0 = assess.episode(pattern, fams, txns, flagged, self.as_of)
        exposure0 = round(sum(by_id[t].amt for t in affected0), 2)
        if self.stop_after_assess:
            return {"case_id": self.case_id, "as_of": self.as_of, "p": a0.p, "pattern": pattern,
                    "familiar": len(familiar), "tool_calls": gw.read_calls,
                    "families": {k: {"s": f.s, "available": f.available,
                                     "detail": json.loads(json.dumps(f.detail, default=str))} for k, f in fams.items()},
                    "flagged": {"channel": flagged.channel, "new_found": flagged.new_found, "proxy": flagged.proxy,
                                "product_cd": flagged.product_cd, "amt": flagged.amt, "addr1": flagged.addr1,
                                "profile_complete": bool(flagged.profile_key) and "?" not in flagged.profile_key.split(" | ")},
                    "recent_channels": sorted({t.channel for t in txns if (flagged.ts - t.ts).days <= 7}),
                    "memory": fams["F11_memory"].detail,
                    "sim_scores": sorted([float({kk.split(".")[-1]: vv for kk, vv in c["attributes"].items()}["@score"])
                                          for c in sim_flat.get("closed", [])], reverse=True)[:5],
                    "episode": affected0}

        # DECIDE_INITIAL + EVIDENCE_GATE
        recurring = fams["F13_recurring"].s > 0
        dispute = row["trigger_type"] == "customer_report"
        need_request = (not stop) and (recurring or not (dispute or fams["F6_testing"].s > 0))
        shared_links = fams["F8_network"].detail["links"]
        top_link = sorted(shared_links, key=lambda l: (-len(l["fraud_cards"]), l["element"]))[0] if shared_links else None
        base_input = dict(
            trigger_type=row["trigger_type"], pattern=pattern, card_testing=fams["F6_testing"].s > 0,
            cleared_over_100=bool(fams["F6_testing"].detail.get("cleared_over_100")), recurring_match=recurring,
            shared_link=bool(top_link) or (fams["F8_network"].s >= 1.0 and bool(linked_cards)),
            shared_element=(f"{top_link['kind']} {top_link['element']}" if top_link else
                            (f"DeviceProfile {flagged.profile_key}" if linked_cards else "")),
            shared_cards=len(linked_cards),
            coordinated_cross_customer=coordinated,
            confirmed_fraud_cards=0, credentials_compromised=False,
            customer_visible_cards=len(visible_cards),
            online_device_signal=flagged.channel == "online" and (fams["F4_device"].s > 0 or fams["F7_takeover"].s > 0))
        req_type = responder.request_type(flagged.channel, base_input["online_device_signal"],
                                          row["trigger_type"]) if need_request else ""
        pin0 = PolicyInput(p=a0.p, n_support=a0.n_support, n_exculpatory=a0.n_exculpatory, conflict=a0.conflict,
                           verdict=v0, exposure=exposure0 if v0 != "legitimate" else 0.0,
                           response="none", evidence_requested=need_request, evidence_request_type=req_type,
                           **base_input)
        self.state("DECIDE_INITIAL", p=a0.p, verdict=v0, pattern=pattern, stop_rule=stop)
        initial = decide(pin0)
        self.audit.append("policy", {"phase": "initial", "input": asdict(pin0), "fired": initial.fired,
                                     "guards": initial.guards})
        self.state("EVIDENCE_GATE", request=need_request)

        requests, response, a1, v1, pin1, final = [], "none", a0, v0, pin0, initial
        if need_request:
            step = self.state("REQUEST_EVIDENCE")
            clearance = ("travel" if fams["F5_trip"].s > 0 or fams["F5_region"].s > 0 else
                         "new_phone" if fams["F4_device"].s > 0 else "intent" if fams["F1_amount"].s > 0 else "")
            self.state("SIMULATE_RESPONSE")
            response, assumed = responder.respond(a0.p, req_type, flagged_id=flagged_id, pattern_hint=pattern,
                                                  region=flagged.addr1, recurring=recurring,
                                                  clearance_reason=clearance)
            requests = [{"type": req_type, "asked_after_step": step, "assumed_response": assumed}]
            self.state("REASSESS", response=response)
            a1 = scorer.update_with_response(a0, response)
            v1 = scorer.verdict(a1, response)
            pin1 = PolicyInput(p=a1.p, n_support=a1.n_support, n_exculpatory=a1.n_exculpatory, conflict=a1.conflict,
                               verdict=v1, exposure=exposure0 if v1 != "legitimate" else 0.0, response=response,
                               evidence_requested=True, evidence_request_type=req_type, **base_input)
            self.state("DECIDE_FINAL")
            final = decide(pin1)
            self.audit.append("policy", {"phase": "final", "input": asdict(pin1), "fired": final.fired,
                                         "guards": final.guards})

        verdict = v1
        pattern_final = "none" if verdict == "legitimate" else pattern
        affected = [] if verdict == "legitimate" else affected0
        exposure = round(sum(abs(by_id[t].amt) for t in affected), 2)
        connected = [] if verdict == "legitimate" else [c for c in linked_cards if c != card_id][:25]
        devices = [] if verdict == "legitimate" else linked_devices[:5]
        final_names = [a["action"] for a in final.actions]
        status = ("escalated" if "ESCALATE_TO_ANALYST" in final_names else
                  {"fraud": "closed_fraud", "legitimate": "closed_legitimate"}.get(verdict, "open"))

        # knowledge retrieval for the rules and pattern that drove the decision (document evidence)
        rules = sorted({t for a in initial.actions + final.actions for t in re.findall(r"R\d+|§\d[ab]?", a["reason"])})
        kq = " ".join(rules) + " " + narrate.PATTERN_TEXT[pattern_final]
        ks, e_ks = await gw.call("knowledge_search", qv=qvec(kq), top_k=6)
        chunks = [{k.split(".")[-1]: v for k, v in c["attributes"].items()} for c in flat(ks)["chunks"]]

        # evidence list (claims templated from detector outputs; refs resolve to provenance envelopes)
        evidence = []
        if dispute:
            evidence.append({"claim": f"Customer message in the alert: {row['trigger_text']}", "source": "customer",
                             "ref": f"case_pack:{self.case_id}.trigger_text", "entity_ids": [flagged_id, cust_id]})
        evidence.append({"claim": f"Bank model risk score on transaction {flagged_id} is {flagged.risk_score:.2f} "
                                  f"(an input, not a verdict; weight 0 in the evidence scorer)", "source": "graph",
                         "ref": e_txn["ref"], "entity_ids": [flagged_id]})
        contrib = a1.contributions
        for name, fam in fams.items():
            c = contrib.get(name, 0.0)
            if fam.available and (abs(c) >= T["theta"] or name in ("F8_network", "F11_memory")) and fam.claim:
                evidence.append({"claim": f"{fam.claim} (contribution {c:+.2f} logit)", "source": "graph",
                                 "ref": fam.refs[0], "entity_ids": sorted(set(fam.entities))[:20]})
        if familiar:
            evidence.append({"claim": "Familiar aspects: " + "; ".join(familiar) +
                                      f" (contribution {contrib.get('F14_familiar', 0):+.2f} logit)",
                             "source": "graph", "ref": e_hist["ref"], "entity_ids": [flagged_id]})
        if requests:
            evidence.append({"claim": requests[0]["assumed_response"], "source": "customer",
                             "ref": "evidence_request:1", "entity_ids": [flagged_id]})
        cited_rules = {knowledge.rule_vertex_id(r) for r in rules}
        for ch_ in chunks:
            if ch_["section"].replace("§", "S") in cited_rules or ch_["section"] == pattern_final:
                evidence.append({"claim": f"Policy/pattern text retrieved: {ch_['text'][:220]}",
                                 "source": "document", "ref": f"document:README#{ch_['section']}",
                                 "entity_ids": [ch_["chunk_id"]]})

        key_evidence = [e["claim"].split(" (contribution")[0] for e in evidence
                        if e["source"] == "graph" and "contribution +" in e["claim"]]
        # cite only closed cases that informed the decision, in priority order
        memory_used = False   # scorer v2 gives F11 weight 0 and patterns come from detector rules (backtest)
        # structural neighbours inform the decision only in the device-ring branch of classify()
        ring_related = [r["case_id"] for r in related if r.get("@overlap", 0) > 0] if coordinated else []
        ordered = (list(fams["F9_prior"].entities) + network_cases + ring_related +
                   (mem_cited if memory_used else []))
        similar = list(dict.fromkeys(ordered))[: T["memory_cite_max"]]
        trigger_desc = {"risk_score": f"a bank model risk score of {flagged.risk_score:.2f}",
                        "customer_report": "a customer report disputing the transaction",
                        "analyst_request": "an analyst request about a shared device profile"}[row["trigger_type"]]
        facts = {
            "flagged": flagged_id, "flagged_amt": flagged.amt, "channel": flagged.channel, "card": card_id,
            "customer": cust_id, "trigger_desc": trigger_desc, "verdict": verdict, "p": a1.p, "p_initial": a0.p,
            "pattern": pattern_final, "n_affected": len(affected), "exposure": exposure,
            "key_evidence": key_evidence, "response": response, "request_type": req_type or "none",
            "final_actions": final_names, "initial_actions": [a["action"] for a in initial.actions],
            "stop_rule": stop, "n_indep": max(a0.n_support, a0.n_exculpatory), "affected": affected,
            "connected_cards": connected, "device_profiles": devices,
            "channel_desc": "online (card not present)" if flagged.channel == "online" else "card present (in person)",
            "why": "; ".join(key_evidence[:2]) or "of the customer's denial and the policy conditions cited",
        }
        sar_file = "FILE_REPORT" in final_names
        if affected:
            dates = sorted(by_id[t].ts.strftime("%Y-%m-%d") for t in affected)
            facts["first_date"], facts["last_date"] = dates[0], dates[-1]
        sar_reason = next((a["reason"] for a in final.actions if a["action"] == "FILE_REPORT"),
                          "§3a: no report; fraud is not confirmed or strongly suspected together with exposure over "
                          "$1,000, a shared origin, or an undocumented coordinated pattern")
        answer = {
            "case_id": self.case_id,
            "case": {
                "status": status, "verdict": verdict, "fraud_probability": a1.p, "pattern": pattern_final,
                "pattern_description": pdesc if pattern_final == "undocumented" else "",
                "affected_txn_ids": affected, "first_suspicious_txn_id": affected[0] if affected else "",
                "connected_card_ids": connected, "connected_device_profiles": devices, "exposure_usd": exposure,
                "evidence": evidence, "similar_prior_cases": similar, "summary": narrate.summary(facts),
                "written_to_graph": False, "graph_case_id": "",
            },
            "evidence_requests": requests,
            "next_best_actions": {"initial": initial.actions, "final": final.actions,
                                  "what_changed": narrate.what_changed(facts)},
            "sar": {"file": sar_file, "reason": sar_reason,
                    "narrative": narrate.sar_narrative(facts) if sar_file else "",
                    "subjects": ([cust_id, card_id] + connected) if sar_file else [],
                    "total_amount_usd": exposure if sar_file else 0,
                    "activity_dates": [facts["first_date"], facts["last_date"]] if sar_file else []},
            "stop_reason": narrate.stop_reason(facts),
            "tool_calls": gw.read_calls, "tokens": 0,
            "latency_s": round(time.perf_counter() - t0, 2),
        }
        ctx = {"as_of": self.as_of, "flagged": flagged_id,
               "txn_ts": {t: by_id[t].ts.strftime(config.TS_FORMAT) for t in by_id},
               "txn_amt": {t: by_id[t].amt for t in by_id}, "known_ids": gw.known_ids(),
               "retrieved_closed": retrieved_closed, "policy_initial": asdict(pin0), "policy_final": asdict(pin1),
               "tool_calls": gw.read_calls, "envelope_refs": {e["ref"] for e in gw.envelopes}}

        # NARRATE (templates) + VALIDATE
        self.state("NARRATE", mode="template")
        self.state("VALIDATE")
        problems = validate(answer, ctx)
        self.audit.append("validation", {"problems": problems})
        self.trace.update({"families": {k: asdict(v) for k, v in fams.items()}, "familiar": familiar,
                           "assessment_initial": asdict(a0), "assessment_final": asdict(a1),
                           "policy_initial": asdict(pin0), "policy_final": asdict(pin1),
                           "policy_fired": {"initial": initial.fired, "final": final.fired},
                           "envelopes": gw.envelopes, "signature": sig, "linked_cards": linked_cards,
                           "capped_elements": capped, "knowledge": chunks, "visible_cards": visible_cards})
        if problems:
            self.state("FAILED", problems=problems)
            self._write_outputs(answer, final_ok=False)
            raise RuntimeError(f"validation failed: {problems}")

        # PERSIST
        self.state("PERSIST")
        if self.write_graph:
            answer = await self.persist(answer, flagged, fams, pattern_final)
        self._write_outputs(answer, final_ok=True)
        self.state("DONE", written_to_graph=answer["case"]["written_to_graph"])
        return answer

    async def persist(self, answer: dict, flagged, fams: dict, pattern: str) -> dict:
        manifest_sha = hashlib.sha256(config.RAW_MANIFEST.read_bytes()).hexdigest()
        key = "|".join([self.case_id, self.as_of, config.POLICY_VERSION, config.SCORER_VERSION, manifest_sha])
        gid = f"INV-{self.case_id}-{hashlib.sha256(key.encode()).hexdigest()[:10]}"
        staged = json.loads(json.dumps(answer))
        staged["case"]["written_to_graph"], staged["case"]["graph_case_id"] = True, gid
        body = canonical(staged)
        digest = hashlib.sha256(body.encode()).hexdigest()
        c = staged["case"]
        emb = [round(float(x), 6) for x in embed.embed(c["summary"] + " " + " ".join(
            e["claim"] for e in c["evidence"]), embed.load_idf(config.PROJECT_ROOT / "config" / "embedding_idf.json"))]
        gw = self.gw
        try:
            await gw.add_nodes("InvestigationCase", "graph_case_id", [{
                "graph_case_id": gid, "case_id": self.case_id, "run_id": self.run_id, "case_as_of": self.as_of,
                "status": c["status"], "verdict": c["verdict"], "fraud_probability": c["fraud_probability"],
                "pattern": c["pattern"], "pattern_description": c["pattern_description"], "summary": c["summary"],
                "exposure_usd": c["exposure_usd"], "sar_file": staged["sar"]["file"], "answer_json": body,
                "answer_sha256": digest, "policy_version": config.POLICY_VERSION,
                "scorer_version": config.SCORER_VERSION, "data_manifest_sha256": manifest_sha,
                "superseded": False, "simulated": True, "created_wall": datetime.now(timezone.utc).isoformat(),
                "embedding": emb}])
            await gw.write_query("clear_case_edges", c=gid)
            ev_nodes = [{"evidence_id": f"{gid}-E{i:02d}", "claim": e["claim"], "source": e["source"],
                         "ref": e["ref"], "ordinal": i} for i, e in enumerate(c["evidence"], 1)]
            act_nodes = [{"action_rec_id": f"{gid}-{ph[0].upper()}{i:02d}", "phase": ph, "ordinal": i,
                          "action": a["action"], "route": a["route"], "reason": a["reason"],
                          "execution": "simulated_executed" if a["route"] == "auto" else "pending_approval"}
                         for ph in ("initial", "final") for i, a in enumerate(staged["next_best_actions"][ph], 1)]
            await gw.add_nodes("EvidenceItem", "evidence_id", ev_nodes)
            await gw.add_nodes("ActionRecommendation", "action_rec_id", act_nodes)

            def e(src_t, tgt_t, tgts, **attrs):
                return [{"source_type": src_t, "source_id": gid, "target_type": tgt_t, "target_id": t, **attrs}
                        for t in tgts]
            expected = {}
            plan = [("FLAGGED", e("InvestigationCase", "Transaction", [self.row["flagged_txn_id"]])),
                    ("INVOLVES", e("InvestigationCase", "Transaction", c["affected_txn_ids"])),
                    ("ON_CARD", e("InvestigationCase", "Card", [self.row["card_id"]])),
                    ("CONNECTED_TO", e("InvestigationCase", "Card", c["connected_card_ids"])),
                    ("FIRST_FRAUD", e("InvestigationCase", "Transaction",
                                      [c["first_suspicious_txn_id"]] if c["first_suspicious_txn_id"] else [])),
                    ("HAS_PATTERN", e("InvestigationCase", "FraudPattern", [pattern])),
                    ("NAMES_DEVICE", e("InvestigationCase", "DeviceProfile",
                                       sorted(set(c["connected_device_profiles"]) |
                                              ({flagged.profile_key} if flagged.profile_key else set())))),
                    ("SIMILAR_TO", [dict(x, score=1.0, method="retrieved") for x in
                                    e("InvestigationCase", "ClosedCase", c["similar_prior_cases"])]),
                    ("HAS_EVIDENCE", e("InvestigationCase", "EvidenceItem", [n["evidence_id"] for n in ev_nodes])),
                    ("HAS_ACTION", e("InvestigationCase", "ActionRecommendation",
                                     [n["action_rec_id"] for n in act_nodes]))]
            for etype, edges in plan:
                await gw.add_edges(etype, edges)
                expected[etype] = expected.get(etype, 0) + len(edges)
            about = {}
            for n, ev in zip(ev_nodes, c["evidence"]):
                for eid in ev["entity_ids"]:
                    tt = entity_type(eid)
                    if tt:
                        about.setdefault(tt, []).append({"source_type": "EvidenceItem", "source_id": n["evidence_id"],
                                                         "target_type": tt, "target_id": eid})
            for tt, edges in sorted(about.items()):
                await gw.add_edges("EVIDENCE_ABOUT", edges)
            cites = [{"source_type": "ActionRecommendation", "source_id": n["action_rec_id"],
                      "target_type": "PolicyRule", "target_id": knowledge.rule_vertex_id(r)}
                     for n in act_nodes for r in sorted(set(re.findall(r"R10|R[1-9]|§3a|§3b|§6", n["reason"])))]
            await gw.add_edges("CITES_RULE", cites)
            check = await gw.write_query("verify_case", c=gid)
            check = flat(check)
            stored = {k.split(".")[-1]: v for k, v in check["case_vertex"][0]["attributes"].items()}
            counts = check["edge_counts"]
            mismatch = {k: (v, counts.get(k)) for k, v in expected.items() if v and counts.get(k) != v}
            if stored.get("answer_sha256") != digest or mismatch:
                raise RuntimeError(f"read-back mismatch: sha_ok={stored.get('answer_sha256') == digest} {mismatch}")
            self.audit.append("persist", {"graph_case_id": gid, "answer_sha256": digest, "edges": expected,
                                          "read_back": "verified"})
            return staged
        except Exception as exc:  # honest failure: keep written_to_graph false
            self.audit.append("persist_failed", {"graph_case_id": gid, "error": str(exc)[:500]})
            self.trace["persist_error"] = str(exc)[:500]
            return answer

    def _write_outputs(self, answer: dict, final_ok: bool):
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "trace.json").write_text(json.dumps(self.trace, indent=1, default=str), encoding="utf-8")
        target = self.run_dir / f"{self.case_id}.json" if not final_ok else self.out_dir / f"{self.case_id}.json"
        write_canonical(target, answer)   # bytes == hashed canonical form
        if final_ok:
            write_canonical(self.run_dir / f"{self.case_id}.json", answer)
