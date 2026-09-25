"""Command line: run benchmark investigations.

    python -m hhg.cli run HHG-017 [--out runs/phase1] [--no-graph-write] [--llm off]
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from hhg import config
from hhg.agent.orchestrator import Investigation
from hhg.tools.gateway import MCPTransport


def asof_order(case_ids):
    """Benchmark cases in as_of (case_pack.opened_at) order, ties by case_id."""
    import csv
    with (config.RAW_DIR / "case_pack.csv").open(encoding="utf-8", newline="") as f:
        opened = {r["case_id"]: r["opened_at"] for r in csv.DictReader(f)}
    ids = list(opened) if case_ids == ["all"] else case_ids
    return sorted(ids, key=lambda c: (opened[c], c))


async def run_cases(case_ids, out_dir: Path, write_graph: bool, runs_root: Path):
    transport = await MCPTransport().start()
    results = {}
    try:
        for cid in case_ids:
            inv = Investigation(cid, transport, out_dir, write_graph=write_graph, runs_root=runs_root)
            try:
                ans = await inv.run()
                c = ans["case"]
                results[cid] = {"ok": True, "verdict": c["verdict"], "p": c["fraud_probability"],
                                "pattern": c["pattern"], "status": c["status"],
                                "written_to_graph": c["written_to_graph"], "graph_case_id": c["graph_case_id"],
                                "tool_calls": ans["tool_calls"], "latency_s": ans["latency_s"], "run_id": inv.run_id}
            except Exception as exc:  # report, never hide
                results[cid] = {"ok": False, "error": str(exc)[:500], "run_id": inv.run_id}
    finally:
        await transport.close()
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("cases", nargs="+")
    run.add_argument("--out", type=Path, default=config.CASES_DIR)
    run.add_argument("--runs-root", type=Path, default=config.RUNS_DIR / "cases")
    run.add_argument("--no-graph-write", action="store_true")
    run.add_argument("--llm", choices=["off"], default="off", help="Phase 1 supports deterministic templates only")
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    results = asyncio.run(run_cases(asof_order(args.cases), args.out, not args.no_graph_write, args.runs_root))
    print(json.dumps(results, indent=2))
    return 0 if all(r["ok"] for r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
