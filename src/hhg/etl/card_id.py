"""Derived card_id rule (card6-rank-v1). The only module allowed to build K-numbers.

card_id = customer_id + "-K" + n, n = 1-based rank of the transaction's card6 value among
that customer's distinct card6 values over the full dataset, lexical order, blank first.
This is inferred from the data (DATASET_NOTES.md §4), not stated in the README; the
resulting IDs are opaque labels and must never be interpreted (ARCHITECTURE.md §3).
"""

import pandas as pd


def derive_card_ids(customer_id: pd.Series, card6: pd.Series) -> pd.Series:
    frame = pd.DataFrame({"customer_id": customer_id.values, "card6": card6.values})
    ranks = frame.groupby("customer_id")["card6"].transform(
        lambda s: s.map({v: i + 1 for i, v in enumerate(sorted(s.unique()))}))
    return pd.Series((frame["customer_id"] + "-K" + ranks.astype(str)).values, index=customer_id.index)


def validate_against_labels(txn_card: pd.Series, labelled: pd.DataFrame) -> dict:
    """txn_card: derived card_id indexed by txn_id. labelled: columns txn_id, card_id."""
    got = labelled["txn_id"].map(txn_card)
    mismatches = labelled[got.values != labelled["card_id"].values]
    return {"labelled_pairs": int(len(labelled)), "matched": int(len(labelled) - len(mismatches)),
            "mismatches": mismatches.head(20).to_dict("records")}
