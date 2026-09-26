"""Export the committed benchmark artifacts into safe, static JSON for the React cockpit.

Reads only files tracked by git: cases/HHG-*.json and the committed run bundle under
runs/cases/<run_id>/ (answer copy, trace.json, audit.jsonl) whose answer bytes equal the
case file. Writes frontend/public/data/index.json and frontend/public/data/cases/<id>.json.

Never reads .env or data/raw/. Knowledge-chunk text (quoted from the dataset README) is
dropped; only chunk ids, sections and scores are kept. The export refuses to write any
string that looks like a URL or a workspace hostname.

Deterministic: the same commit always produces byte-identical output.

    .venv/Scripts/python frontend/scripts/export_data.py        (from the project root)
"""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from hhg.audit.log import verify  # noqa: E402  (read-only reuse of the project's own chain verifier)

OUT = ROOT / "frontend" / "public" / "data"
DEMO = {"HHG-017": "verification flow", "HHG-014": "device-ring"}
ROUTE_RANK = {"auto": 0, "L1": 1, "L2": 2}
FORBIDDEN = re.compile(r"https?://|tgcloud|\.env\b|TG_SECRET|TG_HOST", re.IGNORECASE)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tracked(pattern: str) -> list:
    out = subprocess.run(["git", "ls-files", "--", pattern], cwd=ROOT, capture_output=True, text=True, check=True)
    return sorted(Path(ROOT, p) for p in out.stdout.splitlines())


def highest_route(actions) -> str:
    routes = [a["route"] for a in actions]
    return max(routes, key=lambda r: ROUTE_RANK.get(r, -1)) if routes else "none"


def assessment(a: dict) -> dict:
    return {"p": a["p"], "n_support": a["n_support"], "n_exculpatory": a["n_exculpatory"],
            "conflict": a["conflict"], "coverage": a["coverage"], "statement": a.get("statement", "none"),
            "contributions": {k: v for k, v in a["contributions"].items() if v}}


def audit_event(e: dict) -> dict:
    p = e["payload"]
    keep = {"seq": e["seq"], "wall": e["wall"], "event": e["event"], "hash": e["hash"], "prev": e["prev"]}
    if e["event"] == "state":
        keep["state"] = p["state"]
        keep["detail"] = {k: v for k, v in p.items() if k != "state"}
    elif e["event"] == "tool_call":
        keep["detail"] = {k: p[k] for k in ("call_id", "tool", "query", "params", "executed_at", "row_count",
                                            "result_sha256", "ref") if k in p}
    elif e["event"] == "policy":
        keep["detail"] = {"phase": p["phase"], "fired": p["fired"], "guards": p.get("guards", [])}
    elif e["event"] == "persist":
        keep["detail"] = {k: p[k] for k in ("graph_case_id", "answer_sha256", "edges", "read_back") if k in p}
    else:  # validation, write_call
        keep["detail"] = p
    return keep


def bundle(case_file: Path, runs: dict) -> dict:
    body = case_file.read_bytes()
    answer = json.loads(body)
    cid = answer["case_id"]
    run_dir = next((d for d in runs.get(cid, []) if (d / f"{cid}.json").read_bytes() == body), None)
    if run_dir is None:
        raise SystemExit(f"{cid}: no committed run directory produced this exact answer file")
    trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
    audit_path = run_dir / "audit.jsonl"
    events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    chain_ok, n_events = verify(audit_path)
    persist = next((e["payload"] for e in events if e["event"] == "persist"), None)
    pf = trace["policy_final"]
    return {
        "case_id": cid,
        "run_id": trace["run_id"],
        "as_of": trace["as_of"],
        "source": {"answer_file": f"cases/{cid}.json", "run_dir": f"runs/cases/{run_dir.name}",
                   "answer_sha256": hashlib.sha256(body).hexdigest(), "trace_sha256": sha256(run_dir / "trace.json"),
                   "audit_sha256": sha256(audit_path)},
        "answer": answer,
        "trigger": trace["case"],
        "assessment": {"initial": assessment(trace["assessment_initial"]),
                       "final": assessment(trace["assessment_final"])},
        "policy": {"fired": trace["policy_fired"],
                   "final": {k: pf.get(k) for k in ("verdict", "pattern", "exposure", "response", "shared_link",
                                                    "shared_element", "shared_cards", "evidence_request_type")}},
        "families": [{"name": f["name"], "s": f["s"], "available": f["available"], "entities": f["entities"],
                      "claim": f["claim"], "refs": f["refs"], "detail": f.get("detail", {})}
                     for f in trace["families"].values()],
        "linked_cards": trace["linked_cards"],
        "envelopes": trace["envelopes"],
        "knowledge": [{"chunk_id": k["chunk_id"], "source": k["source"], "section": k["section"],
                       "score": round(k.get("@score", 0.0), 4)} for k in trace["knowledge"]],
        "audit": {"chain_verified": chain_ok, "n_events": n_events, "events": [audit_event(e) for e in events]},
        "persist": None if persist is None else {
            "graph_case_id": persist["graph_case_id"], "edges": persist["edges"], "read_back": persist["read_back"],
            "answer_sha256_matches_file": persist["answer_sha256"] == hashlib.sha256(body).hexdigest()},
    }


def dump(obj, path: Path):
    text = json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=False) + "\n"
    hit = FORBIDDEN.search(text)
    if hit:
        raise SystemExit(f"refusing to write {path.name}: found {hit.group(0)!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    cases = [p for p in tracked("cases") if re.fullmatch(r"HHG-\d{3}\.json", p.name)]
    if not cases:
        raise SystemExit("no committed answer files in cases/")
    runs = {}
    for p in tracked("runs/cases"):
        if p.name == "audit.jsonl":
            runs.setdefault(p.parent.name.rsplit("-", 1)[0], []).append(p.parent)
    index = []
    for f in cases:
        b = bundle(f, runs)
        dump(b, OUT / "cases" / f"{b['case_id']}.json")
        c, nba = b["answer"]["case"], b["answer"]["next_best_actions"]
        index.append({"case_id": b["case_id"], "verdict": c["verdict"], "fraud_probability": c["fraud_probability"],
                      "pattern": c["pattern"], "exposure_usd": c["exposure_usd"], "status": c["status"],
                      "sar_file": b["answer"]["sar"]["file"], "route": highest_route(nba["final"]),
                      "trigger_type": b["trigger"]["trigger_type"], "as_of": b["as_of"],
                      "evidence_count": len(c["evidence"]), "audit_verified": b["audit"]["chain_verified"],
                      "demo": DEMO.get(b["case_id"])})
    dump({"cases": index}, OUT / "index.json")
    print(f"exported {len(index)} cases to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
