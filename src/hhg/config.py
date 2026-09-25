"""Versioned configuration. README-given values are marked README; operational
definitions the README leaves open are marked OP (ARCHITECTURE.md Appendix B)."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
STAGING_DIR = PROJECT_ROOT / "data" / "staging"
RUNS_DIR = PROJECT_ROOT / "runs"
CASES_DIR = PROJECT_ROOT / "cases"
GSQL_DIR = Path(__file__).resolve().parent / "graph" / "gsql"
RAW_MANIFEST = PROJECT_ROOT / "config" / "raw_dataset_manifest.json"
ENV_FILE = PROJECT_ROOT / ".env"

GRAPH_NAME = os.environ.get("TG_GRAPHNAME", "FraudGraph")

POLICY_VERSION = "readme-1.0+op-1"
SCORER_VERSION = "constrained-fit-v2"
CARD_RULE_VERSION = "card6-rank-v1"
EMBED_VERSION = "hash-tfidf-512-v1"
SCHEMA_VERSION = "fraudgraph-p1-v1"

TS_FORMAT = "%Y-%m-%d %H:%M:%S"

T = {
    # README
    "case_p": 0.30,               # §3a open a case
    "weak_p": 0.70,               # R1
    "stop_hi": 0.85,              # §6
    "stop_lo": 0.15,              # §6
    "block_l1_max": 2500.0,       # §2
    "report_exposure": 1000.0,    # R2, §3a
    "escalate_exposure": 500.0,   # R4, R8
    "testing_min_count": 3,       # R5
    "testing_window_min": 60,     # R5
    "testing_block_amt": 100.0,   # R5
    "burst_hours": 48,            # pattern 2
    # OP
    "small_auth_max": 5.0,
    "window_days": 30,
    "several_cards": 3,
    "max_degree": 50,
    "lookback_days": 180,
    "baseline_gap_hours": 72,
    "theta": 0.4,
    "theta_strong": 1.0,
    "sim_deny": 0.60,
    "sim_confirm": 0.40,
    "recurring_tol": 0.02,
    "recurring_min_days": 25,
    "recurring_max_days": 35,
    "recurring_min_occ": 2,
    "memory_top_k": 20,
    "memory_cite_max": 5,
    "memory_min_sim": 0.35,
    "max_tool_calls": 40,
}

# Customer-statement likelihood ratios (OP; assumptions recorded in every case)
LR = {"dispute": 3.0, "deny": 9.0, "confirm": 1 / 19, "no_reply": 1.5}

# Evidence-family weights in logit units. Scorer v2 (Phase 2), evidence: runs/backtest_v1/, 300 closed-case
# pseudo-alerts (150 fraud / 150 cleared). Families with >= 10 non-zero observations were refit by logistic
# regression under README sign constraints (supporting >= 0, exculpatory <= 0): the unconstrained fit reversed
# F1/F4/F14, contradicting the README, so those are neutralised to 0 rather than reversed. Fixed v1 weights
# scored test AUC 0.458; the constrained model 0.596 (unconstrained 0.747, rejected for its signs).
# Families with no or negligible backtest support keep their README-grounded v1 weights (marked v1).
# F11 memory is 0: its lexical signature reuses detector vocabulary (circular; anti-correlated in backtest).
W = {
    "F1_amount": 0.0, "F2_product": 0.452, "F3_burst": 0.656, "F4_device": 0.0, "F5_region": 1.2,   # F5 v1
    "F5_trip": -1.0, "F6_testing": 3.0, "F7_takeover": 1.0, "F8_network": 0.289, "F9_prior": 0.825,   # v1: trip, testing, takeover
    "F10_risk": 0.0, "F11_memory": 0.0, "F13_recurring": -2.5, "F14_familiar": 0.0, "F15_structuring": 2.0,  # v1: recurring, structuring
}
INTERCEPT = -0.666   # fitted on the 50/50 backtest sample, i.e. the README's "half legitimate" prior
PRIOR_P = 0.5            # README: "Half the cases are legitimate"
HISTORY_FRAUD_RATE = 4665 / 5565   # closed-case base rate, for the memory prior shift
