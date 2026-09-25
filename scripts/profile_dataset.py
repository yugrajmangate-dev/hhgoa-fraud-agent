"""Profile every column of the official dataset and write the data dictionary.

Reads data/raw/ only. Writes reports/data_dictionary.md (human-readable, V1..V339 grouped
into blocks with identical null counts) and reports/column_profile.json (one entry per
column). Column meanings are quoted from data/raw/README.md; nothing is interpreted beyond it.
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_dataset import (DEFAULT_BASELINE, DEFAULT_DATA_DIR, PROJECT_ROOT,  # noqa: E402
                              REQUIRED_COLUMNS, TS_FORMAT, read_header, read_strings)

DEFAULT_REPORTS = PROJECT_ROOT / "reports"
BATCH = 40
FILES = ["transactions.csv", "identity.csv", "closed_cases_history.csv", "case_pack.csv"]

# Meanings quoted or condensed from data/raw/README.md.
MEANING = {
    "TransactionID": "Transaction ID (disguised: new IDs)",
    "TransactionDT": "Seconds from the dataset start (disguised: small time offsets)",
    "TransactionAmt": "Amount in USD (disguised: small amount offsets)",
    "ProductCD": "Product code W/C/H/R/S; W has no identity record and is treated as in person",
    "card1": "Issuer code (disguised); customer_id is derived from it",
    "card2": "Card detail: issuer code", "card3": "Card detail: issuer code",
    "card4": "Card network (visa, mastercard, american express, discover)",
    "card5": "Card detail: issuer code", "card6": "Card type (credit, debit)",
    "addr1": "Billing region, anonymized code", "addr2": "Billing country code; 87 is the home country",
    "dist1": "Distance between two unnamed points, when known",
    "dist2": "Distance between two unnamed points, when known",
    "P_emaildomain": "Purchaser email domain", "R_emaildomain": "Recipient email domain",
    "customer_id": "Added. e.g. C01234; derived from the card issuer field; one customer can have several cards",
    "ts": "Added. Real timestamp YYYY-MM-DD HH:MM:SS, July 2 to December 31, 2016",
    "channel": "Added. in_person (ProductCD W, no device record) or online",
    "risk_score": "Added. 0-1 from the bank's detection model. An input, not an answer",
    "id_15": "Device New / Found", "id_23": "Proxy: transparent, anonymous, hidden", "id_30": "OS",
    "id_31": "Browser", "id_33": "Screen", "id_34": "Match status",
    "DeviceType": "mobile or desktop", "DeviceInfo": "Device or platform description",
    "case_id": "Case ID", "card_id": "Card ID, e.g. C01234-K1 (derivation not documented; see DATASET_NOTES.md)",
    "opened_at": "When the case / alert was opened", "closed_at": "When the case was closed",
    "outcome": "confirmed_fraud / cleared", "pattern": "Five documented patterns, undocumented, or none",
    "first_fraud_txn_id": "First fraudulent transaction (blank when cleared)",
    "txn_ids": "Pipe-separated transaction IDs in the case", "n_txns": "Number of transactions in txn_ids",
    "exposure_usd": "Total USD of the fraud episode (0 when cleared)",
    "connected_card_ids": "Pipe-separated other cards in the same compromise",
    "actions_taken": "Pipe-separated policy actions", "report_filed": "Yes / No (SAR filed)",
    "analyst_notes": "Free-text narrative", "trigger_type": "risk_score / customer_report / analyst_request",
    "trigger_text": "Alert text", "flagged_txn_id": "Where the alert fired; not necessarily where fraud started",
}
GROUP_MEANING = [
    ("C", range(1, 15), "Counts (e.g. addresses/phones associated with the card); unnamed individually"),
    ("D", range(1, 16), "Time deltas in days (e.g. days since previous transaction); unnamed individually"),
    ("M", range(1, 10), "Match flags (e.g. name on card matches address)"),
    ("V", range(1, 340), "Vesta engineered features: ranking, counting, entity relationships; unnamed"),
]


def meaning(col: str) -> str:
    if col in MEANING:
        return MEANING[col]
    for prefix, numbers, text in GROUP_MEANING:
        if col in {f"{prefix}{n}" for n in numbers}:
            return text
    if col.startswith("id_"):
        n = int(col[3:])
        return ("Encoded rating (device, IP-domain, proxy, login counts, time on page)" if n <= 11
                else "Categorical identity field (unnamed)")
    return ""


def profile_series(s: pd.Series) -> dict:
    blank = s == ""
    v = s[~blank]
    out = {"rows": int(len(s)), "blank": int(blank.sum()),
           "blank_pct": round(100 * float(blank.mean()), 2) if len(s) else 0.0,
           "distinct": int(v.nunique())}
    if v.empty:
        out["type"] = "empty"
        return out
    num = pd.to_numeric(v, errors="coerce")
    if num.notna().all():
        integral = bool((num % 1 == 0).all())
        written_int = bool(v.str.fullmatch(r"-?\d+").all())
        out["type"] = "integer" if written_int else ("integer-valued, written as N.0" if integral else "decimal")
        out["min"], out["max"] = float(num.min()), float(num.max())
        return out
    ts = pd.to_datetime(v, format=TS_FORMAT, errors="coerce")
    if ts.notna().all():
        out["type"] = "timestamp"
        out["min"], out["max"] = str(ts.min()), str(ts.max())
        return out
    out["type"] = "string"
    top = v.value_counts().head(5)
    out["top"] = {str(k): int(c) for k, c in top.items()}
    out["max_len"] = int(v.str.len().max())
    return out


def profile_file(path: Path) -> list:
    header = read_header(path)
    rows = []
    for start in range(0, len(header), BATCH):
        cols = header[start:start + BATCH]
        df = read_strings(path, cols)
        for c in cols:
            rows.append({"column": c, **profile_series(df[c]), "meaning": meaning(c)})
        del df
    return rows


def fmt_range(p: dict) -> str:
    if p["type"] in ("empty",):
        return ""
    if "top" in p:
        if p["distinct"] == p["rows"] - p["blank"] and p["distinct"] > 20:
            return f"all non-blank values unique (max length {p['max_len']})"
        items = list(p["top"].items())
        shown = ", ".join(f"`{k[:40]}` ({v:,})".replace("|", "\\|") for k, v in items[:5])
        return shown + (" …" if p["distinct"] > len(items) else "")
    lo, hi = p["min"], p["max"]
    if isinstance(lo, float):
        lo, hi = f"{lo:.10g}", f"{hi:.10g}"
    return f"{lo} … {hi}"


def v_blocks(rows: list) -> list:
    """Group consecutive V columns with identical blank counts and types."""
    blocks = []
    for r in rows:
        if not (r["column"].startswith("V") and r["column"][1:].isdigit()):
            continue
        key = (r["blank"], r["type"])
        if blocks and blocks[-1]["key"] == key:
            blocks[-1]["cols"].append(r)
        else:
            blocks.append({"key": key, "cols": [r]})
    return blocks


def render(profiles: dict, baseline: dict) -> str:
    out = ["# Data dictionary: HHGoa IEEE-CIS dataset", "",
           "> Generated by `python scripts/profile_dataset.py` from `data/raw/`. Do not edit by hand.",
           "> Meanings are quoted or condensed from `data/raw/README.md`. Empty fields are counted as "
           "**blank**; the files contain no other null marker.", "",
           "| File | Rows | Columns | SHA-256 (first 16) |", "|---|---:|---:|---|"]
    for name in FILES:
        rows = profiles[name]
        sha = baseline.get(name, {}).get("sha256", "")[:16]
        out.append(f"| `{name}` | {rows[0]['rows']:,} | {len(rows)} | `{sha}` |")
    out.append("")
    head = ["| Column | Type | Blank | Blank % | Distinct | Range / top values | Meaning (README) |",
            "|---|---|---:|---:|---:|---|---|"]
    for name in FILES:
        rows = profiles[name]
        out += [f"## `{name}`", ""] + head
        for r in rows:
            if name == "transactions.csv" and r["column"].startswith("V") and r["column"][1:].isdigit():
                continue
            out.append(f"| `{r['column']}` | {r['type']} | {r['blank']:,} | {r['blank_pct']} | "
                       f"{r['distinct']:,} | {fmt_range(r)} | {r['meaning']} |")
        if name == "transactions.csv":
            out += ["", "### `V1` … `V339`, grouped by identical blank count",
                    "", "Vesta engineered features: ranking, counting, entity relationships; unnamed. "
                    "Use as anonymous signals only and say so in evidence (README, Things to know).", "",
                    "| Columns | Count | Type | Blank per column | Blank % | Min … max over block |",
                    "|---|---:|---|---:|---:|---|"]
            for b in v_blocks(rows):
                cols = b["cols"]
                span = cols[0]["column"] if len(cols) == 1 else f"{cols[0]['column']}–{cols[-1]['column']}"
                mins = [c["min"] for c in cols if "min" in c]
                maxs = [c["max"] for c in cols if "max" in c]
                rng = f"{min(mins):.10g} … {max(maxs):.10g}" if mins else ""
                out.append(f"| `{span}` | {len(cols)} | {b['key'][1]} | {b['key'][0]:,} | "
                           f"{cols[0]['blank_pct']} | {rng} |")
        out.append("")
    return "\n".join(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS)
    args = parser.parse_args(argv)
    if args.reports_dir.resolve().is_relative_to(args.data_dir.resolve()):
        print("REFUSED: reports directory is inside the dataset directory", file=sys.stderr)
        return 3
    missing = [f for f in FILES if not (args.data_dir / f).is_file()]
    if missing:
        print(f"BLOCKED: missing {missing} in {args.data_dir}", file=sys.stderr)
        return 2
    profiles = {name: profile_file(args.data_dir / name) for name in FILES}
    for name in FILES:
        assert [r["column"] for r in profiles[name]] == read_header(args.data_dir / name)
        assert set(REQUIRED_COLUMNS[name]) == {r["column"] for r in profiles[name]}
    baseline = (json.loads(DEFAULT_BASELINE.read_text(encoding="utf-8"))["files"]
                if DEFAULT_BASELINE.is_file() else {})
    args.reports_dir.mkdir(parents=True, exist_ok=True)
    (args.reports_dir / "column_profile.json").write_text(
        json.dumps(profiles, indent=1) + "\n", encoding="utf-8")
    (args.reports_dir / "data_dictionary.md").write_text(render(profiles, baseline) + "\n",
                                                         encoding="utf-8")
    print(f"profiled {sum(len(v) for v in profiles.values())} columns in {len(FILES)} files; "
          f"wrote {args.reports_dir / 'data_dictionary.md'} and column_profile.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
