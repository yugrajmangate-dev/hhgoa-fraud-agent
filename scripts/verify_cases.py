"""Independent verification of the 20 benchmark answer files.

Re-checks every file against the README answer schema, the raw dataset (data/raw/, read
only, independent of the graph), the policy engine, the run's audit chain and provenance,
and TigerGraph read-back. Writes reports/phase2_verification.json.

    PYTHONPATH=src python scripts/verify_cases.py [--no-graph]
Exit code 0 only if every check on every case passes.
"""

import csv
import glob
import hashlib
import json
import re
import sys
from pathlib import Path

import pandas as pd
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from hhg import config  # noqa: E402
from hhg.audit.log import verify as verify_chain  # noqa: E402
from hhg.etl.card_id import derive_card_ids  # noqa: E402
from hhg.policy.engine import ORDER, PolicyInput, decide, route  # noqa: E402

SCHEMA = json.loads((ROOT / "src/hhg/casefile/case_answer.schema.json").read_text(encoding="utf-8"))
EXPECTED = [f"HHG-{n:03d}.json" for n in range(1, 21)]
RULE = re.compile(r"R(10|[1-9])\b|§3a|§3b|§6")


def load_raw():
    cols = ["TransactionID", "TransactionAmt", "customer_id", "card6", "ts"]
    t = pd.read_csv(config.RAW_DIR / "transactions.csv", usecols=cols, dtype=str, keep_default_na=False)
    t["card_id"] = derive_card_ids(t["customer_id"], t["card6"])
    cc = pd.read_csv(config.RAW_DIR / "closed_cases_history.csv", dtype=str, keep_default_na=False)
    with (config.RAW_DIR / "case_pack.csv").open(encoding="utf-8", newline="") as f:
        cp = {r["case_id"]: r for r in csv.DictReader(f)}
    chunks = pd.read_csv(config.STAGING_DIR / "knowledge.tsv", sep="\t", dtype=str, keep_default_na=False)
    return {"ts": dict(zip(t["TransactionID"], t["ts"])), "amt": dict(zip(t["TransactionID"], t["TransactionAmt"].astype(float))),
            "card_first": t.groupby("card_id")["ts"].min().to_dict(), "customers": set(t["customer_id"]),
            "closed": dict(zip(cc["case_id"], cc["closed_at"])), "cp": cp, "sections": set(chunks["section"])}


def check_case(name: str, raw: dict, conn) -> list:
    p, path = [], config.CASES_DIR / name
    body = path.read_bytes()
    a = json.loads(body)
    cid = name[:-5]
    as_of = raw["cp"][cid]["opened_at"]
    p += [f"schema: {'/'.join(map(str, e.absolute_path))}: {e.message}" for e in Draft202012Validator(SCHEMA).iter_errors(a)]
    if p:
        return p
    c, sar, nba = a["case"], a["sar"], a["next_best_actions"]
    if a["case_id"] != cid:
        p.append("case_id does not match file name")
    # IDs against the raw data, visible at as_of
    txn_ids = set(c["affected_txn_ids"]) | ({c["first_suspicious_txn_id"]} - {""})
    for ev in c["evidence"]:
        txn_ids |= {e for e in ev["entity_ids"] if re.fullmatch(r"\d{7}", e)}
    for t in txn_ids:
        if t not in raw["ts"]:
            p.append(f"txn {t} not in dataset")
        elif raw["ts"][t] > as_of:
            p.append(f"txn {t} after as_of")
    cards = set(c["connected_card_ids"]) | {s for s in sar["subjects"] if "-K" in s}
    for ev in c["evidence"]:
        cards |= {e for e in ev["entity_ids"] if re.fullmatch(r"C\d{5}-K\d+", e)}
    for k in cards:
        if k not in raw["card_first"]:
            p.append(f"card {k} not in dataset")
        elif raw["card_first"][k] > as_of:
            p.append(f"card {k} has no visible transaction at as_of")
    for s in sar["subjects"]:
        if re.fullmatch(r"C\d{5}", s) and s not in raw["customers"]:
            p.append(f"customer {s} not in dataset")
    for k in set(c["similar_prior_cases"]) | {e for ev in c["evidence"] for e in ev["entity_ids"] if e.startswith("CC-")}:
        if k not in raw["closed"]:
            p.append(f"closed case {k} not in dataset")
        elif raw["closed"][k] > as_of:
            p.append(f"closed case {k} closed after as_of")
    # exposure, episode, SAR
    total = round(sum(abs(raw["amt"][t]) for t in c["affected_txn_ids"] if t in raw["amt"]), 2)
    if abs(total - c["exposure_usd"]) > 0.005:
        p.append(f"exposure {c['exposure_usd']} != {total}")
    if c["verdict"] == "legitimate" and (c["affected_txn_ids"] or c["exposure_usd"] or sar["file"]):
        p.append("legitimate verdict with affected txns, exposure or SAR")
    final_actions = [x["action"] for x in nba["final"]]
    if sar["file"] != ("FILE_REPORT" in final_actions):
        p.append("sar.file disagrees with FILE_REPORT in final")
    if sar["file"]:
        dates = sorted(raw["ts"][t][:10] for t in c["affected_txn_ids"])
        if sar["activity_dates"] != [dates[0], dates[-1]]:
            p.append("SAR activity_dates mismatch")
        if abs(sar["total_amount_usd"] - c["exposure_usd"]) > 0.005:
            p.append("SAR total != exposure")
    # actions: routes, order, citations, initial/final rule
    for ph in ("initial", "final"):
        names = [x["action"] for x in nba[ph]]
        if names != [x for x in ORDER if x in names]:
            p.append(f"{ph} not in canonical order")
        for x in nba[ph]:
            if x["route"] != route(x["action"], c["exposure_usd"]):
                p.append(f"{ph} route wrong for {x['action']}")
            if not RULE.search(x["reason"]):
                p.append(f"{ph} reason without rule citation: {x['action']}")
    if not a["evidence_requests"] and (nba["final"] != nba["initial"] or nba["what_changed"] != "nothing"):
        p.append("no evidence requested but final != initial or what_changed != 'nothing'")
    for r in a["evidence_requests"]:
        if not r["assumed_response"].startswith("Simulated: "):
            p.append("assumed_response not marked Simulated")
    # run artifacts: audit chain, provenance, policy reproduction, counts
    runs = sorted(glob.glob(str(config.RUNS_DIR / "cases" / f"{cid}-*")))
    run = next((r for r in reversed(runs) if (Path(r) / f"{cid}.json").exists()
                and (Path(r) / f"{cid}.json").read_bytes() == body), None)
    if not run:
        return p + ["no run directory produced this exact file"]
    ok, n = verify_chain(Path(run) / "audit.jsonl")
    if not ok:
        p.append(f"audit chain broken at event {n}")
    trace = json.loads((Path(run) / "trace.json").read_text(encoding="utf-8"))
    refs = {e["ref"] for e in trace["envelopes"]}
    for ev in c["evidence"]:
        if ev["source"] == "graph" and ev["ref"] not in refs:
            p.append(f"graph evidence ref without provenance envelope: {ev['ref'][:60]}")
        if ev["source"] == "graph" and "as_of=" + as_of not in ev["ref"]:
            p.append("graph evidence ref missing the case as_of")
        if ev["source"] == "document" and ev["ref"].split("#", 1)[1] not in raw["sections"]:
            p.append(f"document ref to unknown section {ev['ref']}")
        if ev["source"] == "customer" and not (ev["ref"].startswith("evidence_request:") or ev["ref"].startswith(f"case_pack:{cid}")):
            p.append(f"customer evidence ref not a request or the trigger: {ev['ref']}")
    for ph, key in (("initial", "policy_initial"), ("final", "policy_final")):
        if decide(PolicyInput(**trace[key])).actions != nba[ph]:
            p.append(f"{ph} actions do not reproduce from the recorded policy input")
    events = [json.loads(l) for l in (Path(run) / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    if a["tool_calls"] != sum(e["event"] == "tool_call" for e in events):
        p.append("tool_calls != tool_call events in the audit log")
    if trace["as_of"] != as_of:
        p.append("trace as_of differs from case_pack opened_at")
    # graph persistence and read-back (independent query)
    if not c["written_to_graph"] or not c["graph_case_id"]:
        p.append("case not written to graph")
    elif conn is not None:
        res = conn.runInstalledQuery("verify_investigation_case", {"as_of": as_of, "c": c["graph_case_id"]})
        flat = {}
        for part in res:
            flat |= part
        v = {k.split(".")[-1]: val for k, val in flat["case_vertex"][0]["attributes"].items()} if flat["case_vertex"] else {}
        if v.get("answer_sha256") != hashlib.sha256(body).hexdigest():
            p.append("graph answer_sha256 != sha256 of the file")
        if v.get("case_id") != cid or str(v.get("case_as_of")) != as_of or v.get("superseded") or not v.get("simulated"):
            p.append("graph vertex attributes mismatch")
        edges = flat.get("edge_counts", {})
        want = {"FLAGGED": 1, "ON_CARD": 1, "INVOLVES": len(c["affected_txn_ids"]), "CONNECTED_TO": len(c["connected_card_ids"]),
                "HAS_EVIDENCE": len(c["evidence"]), "HAS_ACTION": len(nba["initial"]) + len(nba["final"]),
                "SIMILAR_TO": len(c["similar_prior_cases"])}
        bad = {k: (w, edges.get(k, 0)) for k, w in want.items() if edges.get(k, 0) != w}
        if bad:
            p.append(f"graph edge counts mismatch {bad}")
    return p


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    present = sorted(f.name for f in config.CASES_DIR.iterdir()) if config.CASES_DIR.exists() else []
    report = {"files_expected": 20, "files_present": len(present),
              "exact_file_set": present == EXPECTED, "extra": sorted(set(present) - set(EXPECTED)),
              "missing": sorted(set(EXPECTED) - set(present)), "cases": {}}
    raw = load_raw()
    conn = None
    if "--no-graph" not in argv:
        from hhg.graph.admin import connect
        conn = connect()
    for name in EXPECTED:
        if name in present:
            report["cases"][name[:-5]] = check_case(name, raw, conn)
    failed = {k: v for k, v in report["cases"].items() if v}
    report["cases_passed"] = len(report["cases"]) - len(failed)
    out = config.PROJECT_ROOT / "reports" / "phase2_verification.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"exact file set cases/HHG-001..020.json: {report['exact_file_set']} "
          f"(present {len(present)}, missing {report['missing']}, extra {report['extra']})")
    print(f"cases passing every check: {report['cases_passed']}/20")
    for k, v in failed.items():
        print(f"  {k}: {v[:4]}")
    return 0 if report["exact_file_set"] and not failed else 1


if __name__ == "__main__":
    sys.exit(main())
