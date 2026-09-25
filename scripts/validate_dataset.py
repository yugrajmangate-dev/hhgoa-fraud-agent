"""Validate the official HHGoa dataset in data/raw/ against its README.

Every expectation below comes from data/raw/README.md or from DATASET_NOTES.md (where
a rule was inferred from the data, the check says so). The raw files are only read.

Checks: required files, integrity against the pinned SHA-256 baseline, row counts,
required columns, unique identifiers, join-key consistency, timestamp parseability and
temporal ordering, benchmark case IDs HHG-001..HHG-020, and enumerations.

Writes reports/dataset_validation.json.

Exit codes:
    0  no failed checks (warnings allowed)
    1  at least one failed check
    2  data/raw/ missing
    4  --write-baseline refused because a baseline already exists (use --force)
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.csv as pacsv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "raw"
DEFAULT_OUT = PROJECT_ROOT / "reports" / "dataset_validation.json"
DEFAULT_BASELINE = PROJECT_ROOT / "config" / "raw_dataset_manifest.json"

TS_FORMAT = "%Y-%m-%d %H:%M:%S"
# README: TransactionDT is "seconds from the dataset start"; ts runs from July 2, 2016.
# DATASET_NOTES.md §5: ts == 2016-07-02 00:00:00 + TransactionDT seconds on every row.
DT_ORIGIN = pd.Timestamp("2016-07-02 00:00:00")

EXPECTED_FILES = ["README.md", "transactions.csv", "identity.csv",
                  "closed_cases_history.csv", "case_pack.csv"]
EXPECTED_ROWS = {"transactions.csv": 590_742, "identity.csv": 144_432,
                 "closed_cases_history.csv": 5_565, "case_pack.csv": 20}

TXN_ORIGINAL = (["TransactionID", "TransactionDT", "TransactionAmt", "ProductCD"]
                + [f"card{i}" for i in range(1, 7)]
                + ["addr1", "addr2", "dist1", "dist2", "P_emaildomain", "R_emaildomain"]
                + [f"C{i}" for i in range(1, 15)] + [f"D{i}" for i in range(1, 16)]
                + [f"M{i}" for i in range(1, 10)] + [f"V{i}" for i in range(1, 340)])
REQUIRED_COLUMNS = {
    "transactions.csv": TXN_ORIGINAL + ["customer_id", "ts", "channel", "risk_score"],
    "identity.csv": (["TransactionID"] + [f"id_{i:02d}" for i in range(1, 39)]
                     + ["DeviceType", "DeviceInfo"]),
    "closed_cases_history.csv": ["case_id", "customer_id", "card_id", "opened_at", "closed_at",
                                 "outcome", "pattern", "first_fraud_txn_id", "txn_ids", "n_txns",
                                 "exposure_usd", "connected_card_ids", "actions_taken",
                                 "report_filed", "analyst_notes"],
    "case_pack.csv": ["case_id", "opened_at", "trigger_type", "trigger_text", "flagged_txn_id",
                      "card_id", "customer_id", "risk_score"],
}
EXPECTED_COLUMN_COUNTS = {"transactions.csv": 397, "identity.csv": 41,
                          "closed_cases_history.csv": 15, "case_pack.csv": 8}

TXN_USED = ["TransactionID", "TransactionDT", "TransactionAmt", "ProductCD", "card1", "card6",
            "addr1", "customer_id", "ts", "channel", "risk_score"]

POLICY_ACTIONS = {"ALLOW_TRANSACTION", "DECLINE_TRANSACTION", "MONITOR_CARD",
                  "MONITOR_CONNECTED_CARDS", "WARN_CUSTOMER", "VERIFY_WITH_CUSTOMER",
                  "STEP_UP_AUTH", "BLOCK_CARD", "BLOCK_ALL_CARDS", "GENERATE_REPORT",
                  "CREATE_CASE", "FILE_REPORT", "ESCALATE_TO_ANALYST", "CLOSE_NO_FRAUD"}
PATTERNS = {"card_testing", "card_not_present_fraud", "card_not_present_new_device",
            "out_of_region_use", "account_takeover", "undocumented", "none"}
BENCHMARK_IDS = [f"HHG-{n:03d}" for n in range(1, 21)]


# ---------------------------------------------------------------- helpers

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest(data_dir: Path) -> dict:
    return {name: {"bytes": (data_dir / name).stat().st_size, "sha256": sha256(data_dir / name)}
            for name in EXPECTED_FILES if (data_dir / name).is_file()}


def read_header(path: Path) -> list:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return next(csv.reader(f))


def read_strings(path: Path, columns=None) -> pd.DataFrame:
    """Read columns as raw strings; empty fields stay "" (never coerced to NaN)."""
    header = columns or read_header(path)
    opts = pacsv.ConvertOptions(include_columns=header,
                                column_types={c: pa.string() for c in header},
                                strings_can_be_null=False, quoted_strings_can_be_null=False)
    return pacsv.read_csv(path, convert_options=opts).to_pandas()


def parse_ts(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, format=TS_FORMAT, errors="coerce")


def derive_card_ids(txn: pd.DataFrame) -> pd.Series:
    """Card id per transaction, inferred rule (DATASET_NOTES.md §4, not stated in README):
    <customer_id>-K<n>, n = 1-based rank of the transaction's card6 value among the distinct
    card6 values of that customer, in ascending lexical order with "" (blank) first."""
    ranks = txn.groupby("customer_id")["card6"].transform(
        lambda s: s.map({v: i + 1 for i, v in enumerate(sorted(s.unique()))}))
    return txn["customer_id"] + "-K" + ranks.astype(str)


def expected_case_ids_ok(ids) -> bool:
    return list(ids) == BENCHMARK_IDS


def split_pipe(value: str) -> list:
    return [v for v in value.split("|") if v] if value else []


# ---------------------------------------------------------------- report

class Report:
    def __init__(self):
        self.checks = []

    def add(self, check_id, category, ok, expected, observed, severity="error", detail=""):
        status = "pass" if ok else ("fail" if severity == "error" else "warn")
        self.checks.append({"id": check_id, "category": category, "status": status,
                            "expected": expected, "observed": observed, "detail": detail})
        return ok

    def counts(self):
        return {s: sum(c["status"] == s for c in self.checks) for s in ("pass", "warn", "fail")}


# ---------------------------------------------------------------- checks

def check_integrity(r: Report, data_dir: Path, baseline_path: Path):
    for name in EXPECTED_FILES:
        r.add(f"file_exists:{name}", "files", (data_dir / name).is_file(), True,
              (data_dir / name).is_file())
    current = manifest(data_dir)
    if not baseline_path.is_file():
        r.add("integrity:baseline_present", "integrity", False, str(baseline_path), "missing",
              detail="Create once from a fresh, unchanged extract: "
                     "python scripts/validate_dataset.py --write-baseline")
        return current
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))["files"]
    for name in EXPECTED_FILES:
        want, got = baseline.get(name), current.get(name)
        r.add(f"integrity:unchanged:{name}", "integrity", want is not None and want == got,
              want, got, detail="SHA-256 and size must equal the pinned baseline")
    extra = sorted(p.relative_to(data_dir).as_posix() for p in data_dir.rglob("*")
                   if p.is_file() and p.name not in EXPECTED_FILES and p.name != ".gitkeep")
    r.add("integrity:no_extra_files", "integrity", not extra, [], extra, severity="warn")
    return current


def check_columns(r: Report, data_dir: Path):
    for name, required in REQUIRED_COLUMNS.items():
        header = read_header(data_dir / name)
        missing = [c for c in required if c not in header]
        extra = [c for c in header if c not in required]
        dupes = sorted({c for c in header if header.count(c) > 1})
        r.add(f"columns:required:{name}", "columns", not missing, "all present", missing or "all present")
        r.add(f"columns:no_unexpected:{name}", "columns", not extra, [], extra)
        r.add(f"columns:no_duplicates:{name}", "columns", not dupes, [], dupes)
        r.add(f"columns:count:{name}", "columns", len(header) == EXPECTED_COLUMN_COUNTS[name],
              EXPECTED_COLUMN_COUNTS[name], len(header))


def check_all(data_dir: Path, baseline_path: Path) -> dict:
    r = Report()
    current = check_integrity(r, data_dir, baseline_path)
    if not all((data_dir / n).is_file() for n in EXPECTED_FILES):
        return {"report": r, "manifest": current}
    check_columns(r, data_dir)

    txn = read_strings(data_dir / "transactions.csv", TXN_USED)
    ident = read_strings(data_dir / "identity.csv", ["TransactionID", "DeviceInfo"])
    cc = read_strings(data_dir / "closed_cases_history.csv")
    cp = read_strings(data_dir / "case_pack.csv")

    # -- row counts
    for name, df in [("transactions.csv", txn), ("identity.csv", ident),
                     ("closed_cases_history.csv", cc), ("case_pack.csv", cp)]:
        r.add(f"rows:{name}", "rows", len(df) == EXPECTED_ROWS[name], EXPECTED_ROWS[name], len(df))
    outcomes = cc["outcome"].value_counts().to_dict()
    r.add("rows:closed_cases_outcome_split", "rows",
          outcomes == {"confirmed_fraud": 4665, "cleared": 900},
          {"confirmed_fraud": 4665, "cleared": 900}, outcomes)

    # -- unique identifiers and ID formats
    for label, series, pattern in [("transactions.TransactionID", txn["TransactionID"], r"\d+"),
                                   ("identity.TransactionID", ident["TransactionID"], r"\d+"),
                                   ("closed_cases.case_id", cc["case_id"], r"CC-\d{4}"),
                                   ("case_pack.case_id", cp["case_id"], r"HHG-\d{3}")]:
        dupes = int(series.duplicated().sum())
        r.add(f"unique:{label}", "keys", dupes == 0, 0, dupes)
        bad = int((~series.str.fullmatch(pattern)).sum())
        r.add(f"format:{label}", "keys", bad == 0, f"all match {pattern}", bad)
    bad_cust = int((~txn["customer_id"].str.fullmatch(r"C\d{5}")).sum())
    r.add("format:transactions.customer_id", "keys", bad_cust == 0, "all match C\\d{5}", bad_cust)
    card_pat = r"C\d{5}-K\d+"
    conn_all = pd.Series([c for v in cc["connected_card_ids"] for c in split_pipe(v)], dtype=str)
    bad_card = int((~pd.concat([cc["card_id"], cp["card_id"], conn_all]).str.fullmatch(card_pat)).sum())
    r.add("format:card_ids", "keys", bad_card == 0, f"all match {card_pat}", bad_card)

    # -- enumerations
    def enum(check_id, series, allowed):
        seen = set(series.unique())
        r.add(check_id, "enums", seen <= set(allowed), sorted(allowed), sorted(seen))
    enum("enum:transactions.channel", txn["channel"], {"in_person", "online"})
    enum("enum:transactions.ProductCD", txn["ProductCD"], {"W", "C", "H", "R", "S"})
    enum("enum:closed_cases.outcome", cc["outcome"], {"confirmed_fraud", "cleared"})
    enum("enum:closed_cases.pattern", cc["pattern"], PATTERNS)
    enum("enum:closed_cases.report_filed", cc["report_filed"], {"Yes", "No"})
    enum("enum:closed_cases.actions_taken", pd.Series(
        [a for v in cc["actions_taken"] for a in split_pipe(v)]), POLICY_ACTIONS)
    enum("enum:case_pack.trigger_type", cp["trigger_type"],
         {"risk_score", "customer_report", "analyst_request"})
    rs = pd.to_numeric(txn["risk_score"], errors="coerce")
    r.add("range:transactions.risk_score", "values", bool(rs.notna().all() and rs.between(0, 1).all()),
          "numeric in [0, 1]", {"non_numeric": int(rs.isna().sum()), "min": rs.min(), "max": rs.max()})
    amt = pd.to_numeric(txn["TransactionAmt"], errors="coerce")
    r.add("range:transactions.TransactionAmt", "values", bool(amt.notna().all() and (amt > 0).all()),
          "numeric > 0", {"non_numeric": int(amt.isna().sum()), "min": amt.min(), "max": amt.max()})

    # -- timestamps
    ts = parse_ts(txn["ts"])
    r.add("time:transactions.ts_parseable", "time", int(ts.isna().sum()) == 0, 0, int(ts.isna().sum()),
          detail=f"format {TS_FORMAT}")
    r.add("time:transactions.ts_range", "time",
          ts.min() >= pd.Timestamp("2016-07-02") and ts.max() < pd.Timestamp("2017-01-01"),
          "2016-07-02 .. 2016-12-31", [str(ts.min()), str(ts.max())])
    dt = pd.to_numeric(txn["TransactionDT"], errors="coerce")
    mismatch = int((ts != DT_ORIGIN + pd.to_timedelta(dt, unit="s")).sum())
    r.add("time:ts_equals_origin_plus_TransactionDT", "time", mismatch == 0, 0, mismatch,
          detail="origin 2016-07-02 00:00:00 (DATASET_NOTES.md §5)")
    r.add("time:transactions_sorted_by_ts", "time", bool(ts.is_monotonic_increasing), True,
          bool(ts.is_monotonic_increasing), severity="warn")
    for col in ("opened_at", "closed_at"):
        parsed = parse_ts(cc[col])
        r.add(f"time:closed_cases.{col}_parseable", "time", int(parsed.isna().sum()) == 0, 0,
              int(parsed.isna().sum()))
        cc[col + "_ts"] = parsed
    cp["opened_ts"] = parse_ts(cp["opened_at"])
    r.add("time:case_pack.opened_at_parseable", "time", int(cp["opened_ts"].isna().sum()) == 0, 0,
          int(cp["opened_ts"].isna().sum()))
    inverted = int((cc["closed_at_ts"] < cc["opened_at_ts"]).sum())
    r.add("time:closed_cases.closed_after_opened", "time", inverted == 0, 0, inverted)
    outside = cc[(cc["opened_at_ts"] >= pd.Timestamp("2016-11-01")) |
                 (cc["closed_at_ts"] >= pd.Timestamp("2016-11-01"))]
    r.add("time:closed_cases.within_july_october", "time", outside.empty,
          "README: closed cases July to October", {
              "opened_in_november": int((cc["opened_at_ts"] >= pd.Timestamp("2016-11-01")).sum()),
              "closed_in_november": int((cc["closed_at_ts"] >= pd.Timestamp("2016-11-01")).sum()),
              "latest_closed_at": str(cc["closed_at_ts"].max())},
          severity="warn", detail="Documented discrepancy; see DATASET_NOTES.md §7")
    cp_months = sorted(cp["opened_ts"].dt.strftime("%Y-%m").unique())
    r.add("time:case_pack.in_november_december", "time", set(cp_months) <= {"2016-11", "2016-12"},
          ["2016-11", "2016-12"], cp_months)
    earliest_asof = cp["opened_ts"].min()
    leaking = int((cc["closed_at_ts"] >= earliest_asof).sum())
    r.add("time:closed_cases.all_closed_before_first_benchmark", "time", leaking == 0, 0, leaking,
          detail=f"earliest benchmark opened_at {earliest_asof}; latest closed_at "
                 f"{cc['closed_at_ts'].max()}")

    # -- join keys: transactions / identity
    tx = txn.assign(ts_parsed=ts, amt=amt).set_index("TransactionID")
    orphan_ident = int((~ident["TransactionID"].isin(tx.index)).sum())
    r.add("join:identity_to_transactions", "joins", orphan_ident == 0, 0, orphan_ident)
    ident_chan = tx.loc[ident["TransactionID"], "channel"].value_counts().to_dict()
    r.add("join:identity_only_online", "joins", set(ident_chan) == {"online"}, {"online": len(ident)},
          ident_chan)
    w_mismatch = int(((txn["ProductCD"] == "W") != (txn["channel"] == "in_person")).sum())
    r.add("join:productcd_W_iff_in_person", "joins", w_mismatch == 0, 0, w_mismatch)
    online_no_ident = int(((txn["channel"] == "online") & ~txn["TransactionID"].isin(ident["TransactionID"])).sum())
    r.add("join:online_transactions_with_identity", "joins", online_no_ident == 0, 0, online_no_ident,
          severity="warn", detail="README: device record present for online; some online rows have none")
    per_cust = txn.groupby("customer_id")["card1"].nunique()
    per_card1 = txn.groupby("card1")["customer_id"].nunique()
    r.add("join:customer_id_one_to_one_card1", "joins",
          bool((per_cust == 1).all() and (per_card1 == 1).all()), True,
          {"customers_with_multiple_card1": int((per_cust > 1).sum()),
           "card1_with_multiple_customers": int((per_card1 > 1).sum())})

    # -- join keys: closed cases
    tx["card_id"] = derive_card_ids(txn).values
    cards = set(tx["card_id"])
    cc["txl"] = cc["txn_ids"].map(split_pipe)
    x = cc[["case_id", "customer_id", "card_id", "opened_at_ts", "closed_at_ts", "txl"]].explode("txl")
    missing_tx = int((~x["txl"].isin(tx.index)).sum())
    r.add("join:closed_case_txns_exist", "joins", missing_tx == 0, 0, missing_tx)
    x = x[x["txl"].isin(tx.index)]
    xt = tx.loc[x["txl"]]
    wrong_cust = int((xt["customer_id"].values != x["customer_id"].values).sum())
    r.add("join:closed_case_txn_customer_matches", "joins", wrong_cust == 0, 0, wrong_cust)
    wrong_card = int((xt["card_id"].values != x["card_id"].values).sum())
    r.add("join:closed_case_card_id_matches_derived_rule", "joins", wrong_card == 0, 0, wrong_card,
          detail="Validates the inferred card_id rule (DATASET_NOTES.md §4)")
    multi = int(x["txl"].duplicated().sum())
    r.add("join:txn_in_at_most_one_closed_case", "joins", multi == 0, 0, multi, severity="warn")
    r.add("join:closed_case_card_ids_exist", "joins", bool(cc["card_id"].isin(cards).all()), 0,
          int((~cc["card_id"].isin(cards)).sum()))
    missing_conn = sorted(set(conn_all) - cards)
    r.add("join:connected_card_ids_exist", "joins", not missing_conn, [], missing_conn)
    after_open = int((xt["ts_parsed"].values > x["opened_at_ts"].values).sum())
    r.add("time:closed_case_txns_before_opened_at", "time", after_open == 0, 0, after_open)
    n_bad = int((pd.to_numeric(cc["n_txns"]) != cc["txl"].str.len()).sum())
    r.add("consistency:closed_cases.n_txns", "consistency", n_bad == 0, 0, n_bad)
    fraud = cc["outcome"] == "confirmed_fraud"
    ff_bad = int((~cc[fraud].apply(lambda row: row["first_fraud_txn_id"] in row["txl"], axis=1)).sum())
    r.add("consistency:first_fraud_txn_in_txn_ids", "consistency", ff_bad == 0, 0, ff_bad)
    cleared_bad = int((cc.loc[~fraud, "first_fraud_txn_id"] != "").sum())
    r.add("consistency:cleared_have_no_first_fraud_txn", "consistency", cleared_bad == 0, 0, cleared_bad)
    first_ts = tx.loc[cc.loc[fraud, "first_fraud_txn_id"], "ts_parsed"].values
    min_ts = cc.loc[fraud, "txl"].map(lambda l: tx.loc[l, "ts_parsed"].min()).values
    not_earliest = sorted(cc.loc[fraud, "case_id"][first_ts != min_ts])
    r.add("consistency:first_fraud_txn_is_earliest", "consistency", not not_earliest, [], not_earliest,
          severity="warn", detail="first_fraud_txn_id is not the earliest listed transaction")
    exp_calc = x.assign(amt=xt["amt"].abs().values).groupby("case_id")["amt"].sum().round(2)
    exp_file = pd.to_numeric(cc.set_index("case_id")["exposure_usd"])
    exp_want = exp_calc.where(cc.set_index("case_id").loc[exp_calc.index, "outcome"] == "confirmed_fraud", 0.0)
    exp_bad = sorted(exp_want.index[(exp_want - exp_file.loc[exp_want.index]).abs() > 0.005])
    r.add("consistency:exposure_equals_sum_of_amounts", "consistency", not exp_bad, [], exp_bad[:20],
          detail="confirmed fraud: sum |TransactionAmt| of txn_ids; cleared: 0")

    # -- benchmark case pack
    ids = cp["case_id"].tolist()
    r.add("benchmark:case_ids_HHG-001_to_HHG-020", "benchmark", expected_case_ids_ok(ids),
          BENCHMARK_IDS, ids)
    flagged = cp["flagged_txn_id"]
    r.add("benchmark:flagged_txns_exist", "benchmark", bool(flagged.isin(tx.index).all()), 0,
          int((~flagged.isin(tx.index)).sum()))
    ft = tx.loc[flagged[flagged.isin(tx.index)]]
    r.add("benchmark:flagged_txn_customer_matches", "benchmark",
          bool((ft["customer_id"].values == cp["customer_id"].values).all()), 0,
          int((ft["customer_id"].values != cp["customer_id"].values).sum()))
    r.add("benchmark:flagged_txn_card_matches_derived_rule", "benchmark",
          bool((ft["card_id"].values == cp["card_id"].values).all()), 0,
          int((ft["card_id"].values != cp["card_id"].values).sum()))
    lag_h = (cp["opened_ts"].values - ft["ts_parsed"].values) / pd.Timedelta(hours=1)
    r.add("time:flagged_txn_before_case_opened", "time", bool((lag_h >= 0).all()), "lag >= 0 h",
          {"min_h": float(lag_h.min()), "max_h": float(lag_h.max())})
    has_score = cp["trigger_type"] == "risk_score"
    r.add("benchmark:risk_score_present_iff_risk_trigger", "benchmark",
          bool(((cp["risk_score"] != "") == has_score).all()), True,
          bool(((cp["risk_score"] != "") == has_score).all()))
    score_diff = (pd.to_numeric(cp.loc[has_score, "risk_score"]).values
                  - pd.to_numeric(ft.loc[has_score.values, "risk_score"]).values)
    r.add("benchmark:risk_score_matches_transaction", "benchmark", bool((abs(score_diff) < 0.005).all()),
          0, int((abs(score_diff) >= 0.005).sum()))
    text_amt = cp["trigger_text"].str.extract(r"\$([\d,]+\.\d\d)")[0].str.replace(",", "").astype(float)
    amt_bad = int((abs(text_amt.values - ft["amt"].values) >= 0.005).sum())
    r.add("benchmark:trigger_text_amount_matches", "benchmark", amt_bad == 0, 0, amt_bad)
    text_ids = cp["trigger_text"].str.findall(r"\b(3\d{6})\b")
    id_bad = int(sum(fid not in found for fid, found in zip(flagged, text_ids)))
    r.add("benchmark:trigger_text_txn_id_matches", "benchmark", id_bad == 0, 0, id_bad)

    return {"report": r, "manifest": current,
            "asof_availability": asof_availability(tx, ident, cc, cp)}


def asof_availability(tx: pd.DataFrame, ident: pd.DataFrame, cc: pd.DataFrame,
                      cp: pd.DataFrame) -> list:
    """Per benchmark case: what exists at or before opened_at (visible) versus after (future).
    Informational; the cutoff rule itself is proposed in DATASET_NOTES.md §7 and §12."""
    has_ident = tx.index.isin(ident["TransactionID"])
    rows = []
    for case in cp.itertuples():
        asof = case.opened_ts
        visible = tx["ts_parsed"] <= asof
        cust = tx["customer_id"] == case.customer_id
        card = tx["card_id"] == case.card_id
        cards_all = sorted(tx.loc[cust, "card_id"].unique())
        cards_visible = sorted(tx.loc[cust & visible, "card_id"].unique())
        rows.append({
            "case_id": case.case_id, "as_of": str(asof),
            "flagged_txn_id": case.flagged_txn_id,
            "flagged_ts": str(tx.loc[case.flagged_txn_id, "ts_parsed"]),
            "txns_visible": int(visible.sum()), "txns_future": int((~visible).sum()),
            "identity_visible": int((visible & has_ident).sum()),
            "customer_txns_visible": int((cust & visible).sum()),
            "customer_txns_future": int((cust & ~visible).sum()),
            "card_txns_visible": int((card & visible).sum()),
            "card_txns_future": int((card & ~visible).sum()),
            "customer_cards_visible": cards_visible, "customer_cards_all_time": cards_all,
            "closed_cases_visible": int((cc["closed_at_ts"] <= asof).sum()),
            "closed_cases_opened_not_closed": int(((cc["opened_at_ts"] <= asof)
                                                   & (cc["closed_at_ts"] > asof)).sum()),
            "customer_closed_cases_visible": int(((cc["customer_id"] == case.customer_id)
                                                  & (cc["closed_at_ts"] <= asof)).sum()),
        })
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--write-baseline", action="store_true",
                        help="pin current SHA-256s as the unchanged-dataset baseline, then exit")
    parser.add_argument("--force", action="store_true", help="allow --write-baseline to overwrite")
    args = parser.parse_args(argv)

    if args.out.resolve().is_relative_to(args.data_dir.resolve()):
        print(f"REFUSED: output {args.out} is inside the dataset directory", file=sys.stderr)
        return 3
    if not args.data_dir.is_dir():
        print(f"BLOCKED: dataset directory not found: {args.data_dir}", file=sys.stderr)
        return 2

    if args.write_baseline:
        if args.baseline.exists() and not args.force:
            print(f"REFUSED: baseline exists: {args.baseline} (use --force)", file=sys.stderr)
            return 4
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(json.dumps({
            "created_at": datetime.now(timezone.utc).isoformat(),
            "note": "SHA-256 of the official dataset as extracted, unchanged, into data/raw/",
            "files": manifest(args.data_dir)}, indent=2) + "\n", encoding="utf-8")
        print(f"baseline written to {args.baseline}")
        return 0

    result = check_all(args.data_dir, args.baseline)
    report = result["report"]
    counts = report.counts()
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_dir": str(args.data_dir.resolve()),
        "baseline": str(args.baseline.resolve()),
        "summary": counts,
        "manifest": result["manifest"],
        "checks": report.checks,
        "asof_availability": result.get("asof_availability", []),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")

    for c in report.checks:
        if c["status"] != "pass":
            print(f"{c['status'].upper():4s}  {c['id']}: expected {c['expected']!s:.80}, "
                  f"observed {c['observed']!s:.120}")
    print(f"{counts['pass']} passed, {counts['warn']} warnings, {counts['fail']} failed; "
          f"report written to {args.out}")
    return 1 if counts["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
