"""Closed-case backtest: the only labelled data (ARCHITECTURE.md §18.3).

Each sampled closed case becomes a pseudo-alert: as_of = opened_at, flagged = its latest
listed transaction, trigger = risk_score (neutral: no customer-statement boost, because in
history the trigger type is a proxy for the outcome). The real gateway/MCP pipeline runs up
to ASSESS; nothing is written to the graph or to cases/. T2 hides the case from its own memory.

    python -m hhg.eval.backtest collect --per-class 150
    python -m hhg.eval.backtest analyse
"""

import asyncio
import csv
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

from hhg import config
from hhg.agent.orchestrator import Investigation
from hhg.tools.gateway import MCPTransport

OUT = config.RUNS_DIR / "backtest"
FEATURES = ["F1_amount", "F2_product", "F3_burst", "F4_device", "F5_region", "F5_trip", "F6_testing",
            "F7_takeover", "F8_network", "F9_prior", "F11_memory", "F13_recurring", "F15_structuring"]
TRAIN_END = "2016-10-01 00:00:00"
EXCULPATORY = {"F5_trip", "F13_recurring", "F14_familiar_count"}
EXCLUDED = {"F11_memory", "F6_testing", "F15_structuring", "F13_recurring"}   # memory circular; others never fired


def sample(per_class: int) -> list:
    """Deterministic stratified sample of closed cases opened on/after 2016-08-15 (history exists)."""
    txn_ts = {}
    with (config.RAW_DIR / "transactions.csv").open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            txn_ts[row["TransactionID"]] = row["ts"]
    with (config.RAW_DIR / "closed_cases_history.csv").open(encoding="utf-8", newline="") as f:
        cases = [r for r in csv.DictReader(f) if r["opened_at"] >= "2016-08-15"]
    key = lambda r: hashlib.sha256(r["case_id"].encode()).hexdigest()
    out = []
    for outcome in ("confirmed_fraud", "cleared"):
        pool = sorted([r for r in cases if r["outcome"] == outcome], key=key)[:per_class]
        for r in pool:
            txns = sorted(r["txn_ids"].split("|"), key=lambda t: (txn_ts[t], t))
            out.append({"case_id": f"BT-{r['case_id']}", "closed_case": r["case_id"], "opened_at": r["opened_at"],
                        "trigger_type": "risk_score", "trigger_text": "backtest pseudo-alert",
                        "flagged_txn_id": txns[-1], "card_id": r["card_id"], "customer_id": r["customer_id"],
                        "risk_score": "", "label": int(outcome == "confirmed_fraud"), "true_pattern": r["pattern"],
                        "true_txns": r["txn_ids"].split("|")})
    return sorted(out, key=lambda r: (r["opened_at"], r["case_id"]))


async def collect(per_class: int):
    OUT.mkdir(parents=True, exist_ok=True)
    rows = sample(per_class)
    done_path = OUT / "features.jsonl"
    done = set()
    if done_path.exists():
        done = {json.loads(l)["case_id"] for l in done_path.read_text(encoding="utf-8").splitlines()}
    transport = await MCPTransport().start()
    try:
        with done_path.open("a", encoding="utf-8") as fh:
            for i, row in enumerate(rows):
                if row["case_id"] in done:
                    continue
                inv = Investigation(row["case_id"], transport, OUT, write_graph=False, runs_root=OUT / "runs",
                                    row=row, stop_after_assess=True)
                try:
                    res = await inv.run()
                    res.update({k: row[k] for k in ("closed_case", "label", "true_pattern", "true_txns", "opened_at")})
                except Exception as exc:
                    res = {"case_id": row["case_id"], "error": str(exc)[:300], "label": row["label"]}
                fh.write(json.dumps(res) + "\n")
                fh.flush()
                if i % 25 == 0:
                    print(f"{i + 1}/{len(rows)} {row['case_id']}", flush=True)
    finally:
        await transport.close()


def _auc(y, s):
    order = np.argsort(s)
    ranks = np.empty(len(s))
    ranks[order] = np.arange(1, len(s) + 1)
    pos = y == 1
    return float((ranks[pos].sum() - pos.sum() * (pos.sum() + 1) / 2) / (pos.sum() * (~pos).sum()))


def _fit(X, y, l2=1.0, iters=50):
    w = np.zeros(X.shape[1] + 1)
    Xb = np.hstack([np.ones((len(X), 1)), X])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-Xb @ w))
        g = Xb.T @ (p - y) + l2 * np.r_[0, w[1:]]
        H = Xb.T @ (Xb * (p * (1 - p))[:, None]) + l2 * np.diag(np.r_[0, np.ones(X.shape[1])])
        w -= np.linalg.solve(H, g)
    return w


def _metrics(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return {"auc": round(_auc(y, p), 3), "brier": round(float(np.mean((p - y) ** 2)), 4),
            "logloss": round(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), 4),
            "acc@0.5": round(float(np.mean((p >= 0.5) == y)), 3)}


def analyse() -> dict:
    rows = [json.loads(l) for l in (OUT / "features.jsonl").read_text(encoding="utf-8").splitlines()]
    ok = [r for r in rows if "error" not in r]
    X = np.array([[r["families"][f]["s"] if r["families"][f]["available"] else 0.0 for f in FEATURES] +
                  [min(r["familiar"], 3)] for r in ok])
    y = np.array([r["label"] for r in ok])
    train = np.array([r["opened_at"] < TRAIN_END for r in ok])
    names = FEATURES + ["F14_familiar_count"]
    fixed_w = np.array([config.W.get(f, 0.0) for f in FEATURES] + [config.W["F14_familiar"]])
    report = {"n": len(ok), "errors": len(rows) - len(ok), "n_train": int(train.sum()), "n_test": int((~train).sum()),
              "base_rate": round(float(y.mean()), 3),
              "univariate": {n: {"mean_fraud": round(float(X[y == 1, j].mean()), 3),
                                 "mean_cleared": round(float(X[y == 0, j].mean()), 3),
                                 "nonzero": int((X[:, j] != 0).sum())} for j, n in enumerate(names)}}
    report["fixed_test"] = _metrics(y[~train], 1 / (1 + np.exp(-(X[~train] @ fixed_w))))
    report["fixed_all"] = _metrics(y, 1 / (1 + np.exp(-(X @ fixed_w))))
    w = _fit(X[train], y[train])
    report["fitted_weights"] = {"intercept": round(float(w[0]), 3), **{n: round(float(v), 3) for n, v in zip(names, w[1:])}}
    report["fitted_test"] = _metrics(y[~train], 1 / (1 + np.exp(-(np.hstack([np.ones(((~train).sum(), 1)), X[~train]]) @ w))))
    # Sign-constrained fit (monotone calibration): supporting families >= 0, exculpatory <= 0.
    # F11 memory is excluded (its lexical signature reuses detector vocabulary: circular).
    signs = {n: (-1 if n in EXCULPATORY else 1) for n in names}
    active = [j for j, n in enumerate(names) if n not in EXCLUDED]
    while True:
        wc = _fit(X[train][:, active], y[train])
        bad = [active[k] for k, v in enumerate(wc[1:]) if v * signs[names[active[k]]] < 0]
        if not bad:
            break
        active = [j for j in active if j not in bad]
    cw = {names[j]: round(float(v), 3) for j, v in zip(active, wc[1:])}
    report["constrained_weights"] = {"intercept": round(float(wc[0]), 3), **cw,
                                     "zeroed": [n for n in names if n not in cw]}
    Xt = np.hstack([np.ones(((~train).sum(), 1)), X[~train][:, active]])
    report["constrained_test"] = _metrics(y[~train], 1 / (1 + np.exp(-(Xt @ wc))))
    wall = _fit(X[:, active], y)   # final weights: same constrained feature set, refit on all 300
    report["constrained_weights_all"] = {"intercept": round(float(wall[0]), 3),
                                         **{names[j]: round(float(v), 3) for j, v in zip(active, wall[1:])}}
    from collections import Counter
    report["pattern_confusion_on_fraud"] = {f"{t} -> {p}": n for (p, t), n in
                                            Counter((r["pattern"], r["true_pattern"]) for r in ok if r["label"] == 1).most_common(12)}
    sims = [(r["sim_scores"][0] if r["sim_scores"] else 0.0, r["label"]) for r in ok]
    report["memory_top_similarity"] = {"fraud_mean": round(float(np.mean([s for s, l in sims if l])), 3),
                                       "cleared_mean": round(float(np.mean([s for s, l in sims if not l])), 3),
                                       "share_ge_0.35": round(float(np.mean([s >= 0.35 for s, _ in sims])), 3)}
    pat = [(r["pattern"], r["true_pattern"]) for r in ok if r["label"] == 1]
    report["pattern_accuracy_on_fraud"] = round(float(np.mean([a == b for a, b in pat])), 3) if pat else None
    ep = [len(set(r["episode"]) & set(r["true_txns"])) / len(set(r["episode"]) | set(r["true_txns"]))
          for r in ok if r["label"] == 1]
    report["episode_jaccard_on_fraud"] = round(float(np.mean(ep)), 3) if ep else None
    (OUT / "analysis.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    if argv[0] == "collect":
        asyncio.run(collect(int(argv[argv.index("--per-class") + 1]) if "--per-class" in argv else 150))
    else:
        print(json.dumps(analyse(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
