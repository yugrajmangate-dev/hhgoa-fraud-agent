"""Build TigerGraph staging files from data/raw/ (read-only) with build gates.

Output: data/staging/*.tsv (tab-separated, no quoting; tabs/newlines are removed from
text fields and counted), staging_manifest.json, and config/embedding_idf.json.
Gates (abort on failure): raw SHA-256 equals the pinned manifest; the derived card_id
rule reproduces 100% of labelled pairs; entity counts equal ARCHITECTURE.md §2.
"""

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.csv as pacsv

from hhg import config
from hhg.etl.card_id import derive_card_ids, validate_against_labels
from hhg.memory import embed, knowledge

SENTINEL = "-999999.0"
PART_BYTES = 4 * 1024 * 1024
IDF_PATH = config.PROJECT_ROOT / "config" / "embedding_idf.json"
EXPECTED = {"Customer": 13553, "Card": 14317, "Transaction": 590742, "DeviceProfile": 9705,
            "EmailDomain": 60, "BillingRegion": 332, "ClosedCase": 5565, "MADE": 590742,
            "FROM_DEVICE": 140784, "PURCHASER_EMAIL": 496262, "RECIPIENT_EMAIL": 137453,
            "BILLED_IN": 525003, "NEXT": 576425, "INVOLVES": 14955, "ON_CARD": 5565,
            "CONNECTED_TO": 92, "FIRST_FRAUD": 4665, "HAS_PATTERN": 5565}
TXN_COLS = ["TransactionID", "TransactionAmt", "ProductCD", "card4", "card6", "addr1", "addr2", "dist1",
            "P_emaildomain", "R_emaildomain"] + [f"M{i}" for i in range(1, 10)] + \
           ["customer_id", "ts", "channel", "risk_score"]
ID_COLS = ["TransactionID", "id_15", "id_23", "id_30", "id_31", "id_33", "id_34", "DeviceType", "DeviceInfo"]


class GateError(RuntimeError):
    pass


def read_strings(path: Path, cols=None) -> pd.DataFrame:
    header = cols or pacsv.read_csv(path, read_options=pacsv.ReadOptions(block_size=1 << 16)).column_names
    opts = pacsv.ConvertOptions(include_columns=cols, column_types={c: pa.string() for c in header},
                                strings_can_be_null=False, quoted_strings_can_be_null=False)
    return pacsv.read_csv(path, convert_options=opts).to_pandas()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def profile_key(info, os_, browser, screen) -> pd.Series:
    parts = [s.where(s != "", "?") for s in (info, os_, browser, screen)]
    return parts[0] + " | " + parts[1] + " | " + parts[2] + " | " + parts[3]


class Writer:
    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        self.manifest = {"files": {}, "cleaned_fields": 0}

    def clean(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.astype(str)
        bad = df.apply(lambda s: s.str.contains(r"[\t\r\n]", regex=True)).to_numpy().sum()
        self.manifest["cleaned_fields"] += int(bad)
        return df.replace(r"[\t\r\n]+", " ", regex=True)

    def write(self, name: str, df: pd.DataFrame, split=False):
        df = self.clean(df)
        text = df.to_csv(sep="\t", index=False, lineterminator="\n")
        header, body = text.split("\n", 1)
        parts, buf, size = [], [], 0
        for line in body.splitlines(keepends=True):
            buf.append(line)
            size += len(line.encode())
            if split and size >= PART_BYTES:
                parts.append("".join(buf))
                buf, size = [], 0
        parts.append("".join(buf))
        files = []
        for i, part in enumerate(parts):
            fname = f"{name}.part{i:03d}.tsv" if split else f"{name}.tsv"
            path = self.out_dir / fname
            path.write_text(header + "\n" + part, encoding="utf-8", newline="\n")
            files.append({"file": fname, "rows": part.count("\n"), "sha256": sha256(path)})
        self.manifest["files"][name] = {"rows": int(len(df)), "parts": files}


def build(raw_dir: Path = config.RAW_DIR, out_dir: Path = config.STAGING_DIR) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    pinned = json.loads(config.RAW_MANIFEST.read_text())["files"]
    for name in ("transactions.csv", "identity.csv", "closed_cases_history.csv", "case_pack.csv", "README.md"):
        if sha256(raw_dir / name) != pinned[name]["sha256"]:
            raise GateError(f"raw file changed: {name}")

    t = read_strings(raw_dir / "transactions.csv", TXN_COLS)
    ident = read_strings(raw_dir / "identity.csv", ID_COLS)
    cc = read_strings(raw_dir / "closed_cases_history.csv")
    cp = read_strings(raw_dir / "case_pack.csv")

    t["card_id"] = derive_card_ids(t["customer_id"], t["card6"])
    labelled = pd.concat([
        cc.assign(txn_id=cc["txn_ids"].str.split("|")).explode("txn_id")[["txn_id", "card_id"]],
        cp.rename(columns={"flagged_txn_id": "txn_id"})[["txn_id", "card_id"]]]).drop_duplicates()
    check = validate_against_labels(t.set_index("TransactionID")["card_id"], labelled)
    if check["matched"] != check["labelled_pairs"]:
        raise GateError(f"card_id rule failed: {check}")
    cards = set(t["card_id"])
    conn = [c for v in cc["connected_card_ids"] for c in v.split("|") if c]
    missing = sorted(set(cc["card_id"]) - cards) + sorted(set(conn) - cards) + sorted(set(cp["card_id"]) - cards)
    if missing:
        raise GateError(f"card IDs missing under derived rule: {missing[:10]}")

    t = t.merge(ident, on="TransactionID", how="left", indicator=True)
    t["has_identity"] = (t.pop("_merge") == "both").map({True: "true", False: "false"})
    for c in ID_COLS[1:]:
        t[c] = t[c].fillna("")
    comps = [t["DeviceInfo"], t["id_30"], t["id_31"], t["id_33"]]
    all_blank = (t["DeviceInfo"] == "") & (t["id_30"] == "") & (t["id_31"] == "") & (t["id_33"] == "")
    t["profile_key"] = profile_key(*comps).where(~all_blank, "")
    t["dist1"] = t["dist1"].where(t["dist1"] != "", SENTINEL)
    t = t.sort_values(["card_id", "ts", "TransactionID"], kind="mergesort")

    w = Writer(out_dir)
    w.write("customers", t[["customer_id"]].drop_duplicates().sort_values("customer_id"))
    w.write("cards", t[["card_id", "customer_id", "card6"]].drop_duplicates("card_id")
            .assign(derivation_rule=config.CARD_RULE_VERSION).sort_values("card_id"))
    txn = pd.DataFrame({
        "txn_id": t["TransactionID"], "card_id": t["card_id"], "ts": t["ts"], "amt": t["TransactionAmt"],
        "product_cd": t["ProductCD"], "channel": t["channel"], "risk_score": t["risk_score"],
        "card4": t["card4"], "card6": t["card6"], "addr1": t["addr1"], "addr2": t["addr2"],
        "p_email": t["P_emaildomain"], "r_email": t["R_emaildomain"], "dist1": t["dist1"],
        **{f"m{i}": t[f"M{i}"] for i in range(1, 10)},
        "has_identity": t["has_identity"], "device_type": t["DeviceType"], "device_info": t["DeviceInfo"],
        "os": t["id_30"], "browser": t["id_31"], "screen": t["id_33"], "new_found": t["id_15"],
        "proxy_type": t["id_23"], "match_status": t["id_34"], "profile_key": t["profile_key"]})
    w.write("transactions", txn, split=True)
    dev = t[t["profile_key"] != ""][["profile_key", "DeviceInfo", "id_30", "id_31", "id_33"]] \
        .drop_duplicates("profile_key").sort_values("profile_key")
    dev["completeness"] = (dev[["DeviceInfo", "id_30", "id_31", "id_33"]] != "").sum(axis=1)
    w.write("devices", dev.rename(columns={"DeviceInfo": "device_info", "id_30": "os", "id_31": "browser",
                                           "id_33": "screen"}))
    w.write("regions", pd.DataFrame({"addr1": sorted(set(t["addr1"]) - {""})}))
    w.write("emails", pd.DataFrame({"domain": sorted((set(t["P_emaildomain"]) | set(t["R_emaildomain"])) - {""})}))
    same = t["card_id"].eq(t["card_id"].shift(-1))
    nxt = pd.DataFrame({"from_txn": t["TransactionID"], "to_txn": t["TransactionID"].shift(-1),
                        "gap_seconds": (pd.to_datetime(t["ts"].shift(-1)) - pd.to_datetime(t["ts"]))
                        .dt.total_seconds()})[same.values]
    nxt["gap_seconds"] = nxt["gap_seconds"].astype(int).astype(str)
    w.write("next", nxt, split=True)

    # closed cases and GraphRAG corpus
    readme = (raw_dir / "README.md").read_text(encoding="utf-8")
    chunks = knowledge.chunks(readme)
    idf = embed.fit_idf(list(cc["analyst_notes"]) + [c["text"] for c in chunks])
    embed.save_idf(idf, IDF_PATH)
    ccv = cc.copy()
    ccv["actions_taken"] = ccv["actions_taken"].str.replace("|", ";", regex=False)
    ccv["report_filed"] = ccv["report_filed"].map({"Yes": "true", "No": "false"})
    ccv["embedding"] = [embed.to_field(embed.embed(n, idf)) for n in cc["analyst_notes"]]
    w.write("closed_cases", ccv[["case_id", "customer_id", "card_id", "opened_at", "closed_at", "outcome",
                                 "pattern", "n_txns", "exposure_usd", "actions_taken", "report_filed",
                                 "analyst_notes", "embedding"]], split=True)
    inv = cc.assign(txn_id=cc["txn_ids"].str.split("|")).explode("txn_id")
    w.write("cc_involves", inv[["case_id", "txn_id"]])
    w.write("cc_on_card", cc[["case_id", "card_id"]])
    w.write("cc_connected", cc.assign(card=cc["connected_card_ids"].str.split("|")).explode("card")
            .query("card != ''")[["case_id", "card"]].rename(columns={"card": "card_id"}))
    w.write("cc_first", cc[cc["first_fraud_txn_id"] != ""][["case_id", "first_fraud_txn_id"]]
            .rename(columns={"first_fraud_txn_id": "txn_id"}))
    w.write("cc_pattern", cc[["case_id", "pattern"]])
    patterns = knowledge.PATTERN_NAMES + ["undocumented", "none"]
    w.write("patterns", pd.DataFrame({"name": patterns}))
    w.write("rules", pd.DataFrame({"rule_id": knowledge.policy_rule_ids()}))
    kc = pd.DataFrame(chunks)
    kc["embedding"] = [embed.to_field(embed.embed(x, idf)) for x in kc["text"]]
    w.write("knowledge", kc[["chunk_id", "source", "section", "text", "url", "sha256", "embedding"]])
    links = kc.explode("links").dropna(subset=["links"])
    w.write("kc_rule", links[links["links"].isin(knowledge.policy_rule_ids())][["chunk_id", "links"]]
            .rename(columns={"links": "rule_id"}))
    w.write("kc_pattern", links[links["links"].isin(patterns)][["chunk_id", "links"]]
            .rename(columns={"links": "name"}))

    got = {"Customer": w.manifest["files"]["customers"]["rows"], "Card": w.manifest["files"]["cards"]["rows"],
           "Transaction": len(txn), "DeviceProfile": len(dev), "EmailDomain": w.manifest["files"]["emails"]["rows"],
           "BillingRegion": w.manifest["files"]["regions"]["rows"], "ClosedCase": len(cc), "MADE": len(txn),
           "FROM_DEVICE": int((txn["profile_key"] != "").sum()), "PURCHASER_EMAIL": int((txn["p_email"] != "").sum()),
           "RECIPIENT_EMAIL": int((txn["r_email"] != "").sum()), "BILLED_IN": int((txn["addr1"] != "").sum()),
           "NEXT": len(nxt), "INVOLVES": len(inv), "ON_CARD": len(cc),
           "CONNECTED_TO": w.manifest["files"]["cc_connected"]["rows"],
           "FIRST_FRAUD": w.manifest["files"]["cc_first"]["rows"], "HAS_PATTERN": len(cc)}
    diff = {k: (EXPECTED[k], got[k]) for k in EXPECTED if EXPECTED[k] != got[k]}
    if diff:
        raise GateError(f"staging counts differ from ARCHITECTURE.md §2: {diff}")
    w.manifest.update({"card_rule": config.CARD_RULE_VERSION, "card_rule_check": check, "counts": got,
                       "embedding": config.EMBED_VERSION, "idf_sha256": sha256(IDF_PATH),
                       "raw_manifest_sha256": sha256(config.RAW_MANIFEST)})
    (out_dir / "staging_manifest.json").write_text(json.dumps(w.manifest, indent=2), encoding="utf-8")
    return w.manifest


def main() -> int:
    try:
        m = build()
    except GateError as exc:
        print(f"BUILD GATE FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"card_id rule: {m['card_rule_check']['matched']}/{m['card_rule_check']['labelled_pairs']} labelled pairs")
    print(f"staging counts match ARCHITECTURE.md §2: {m['counts']}")
    print(f"text fields cleaned of tabs/newlines: {m['cleaned_fields']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
