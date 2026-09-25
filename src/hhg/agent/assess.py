"""Pattern classification, episode building and the memory signature (pure functions)."""

import math
import statistics
from datetime import timedelta

from hhg import config

T = config.T
KNOWN = ["card_testing", "card_not_present_fraud", "card_not_present_new_device", "out_of_region_use",
         "account_takeover"]


def signature(fams: dict, flagged) -> str:
    """Deterministic case signature in the vocabulary of the closed-case notes (trigger type
    deliberately excluded: in history it is a proxy for the outcome)."""
    parts = ["Online purchases" if flagged.channel == "online" else "Card-present use"]
    if fams["F1_amount"].s > 0 or fams["F2_product"].s > 0:
        parts.append("inconsistent with the cardholder's usual merchants and amounts")
    if fams["F3_burst"].s > 0:
        parts.append("several online purchases within hours")
    if fams["F4_device"].s > 0:
        parts.append("from a device not previously seen on this account")
        if "ANONYMOUS" in flagged.proxy or "HIDDEN" in flagged.proxy:
            parts.append("behind an anonymous proxy")
    if fams["F5_region"].s > 0:
        parts.append("in a billing region the cardholder had no history in, while the cardholder retained the card")
    if fams["F5_trip"].s > 0:
        parts.append("travel to the billing region in question")
    if fams["F6_testing"].s > 0:
        parts.append("a run of very small online authorizations followed by a larger purchase, consistent with "
                     "testing a stolen card number")
    if fams["F7_takeover"].s > 0:
        parts.append("mixed-channel activity inconsistent with the cardholder; credentials and card data both used")
    if fams["F8_network"].s > 0:
        parts.append("other cardholders reported the same device profile this month")
    if fams["F15_structuring"].s > 0:
        parts.append(f"purchases each just under ${fams['F15_structuring'].detail['threshold']:.0f} "
                     f"authorization threshold")
    if fams["F13_recurring"].s > 0:
        parts.append("charge consistent with their stated intent")
    return "; ".join(parts) + "."


def classify(fams: dict, flagged, related_patterns: list, memory_votes: dict) -> tuple:
    """Returns (pattern, description, coordinated_cross_customer)."""
    net = fams["F8_network"]
    if fams["F6_testing"].s > 0:
        return "card_testing", "", False
    if fams["F15_structuring"].s > 0:
        repeated = memory_votes.get("undocumented", 0) > 0
        return "undocumented", (
            f"Repeated online purchases on one card within an hour, each just under a round "
            f"${fams['F15_structuring'].detail['threshold']:.0f} amount, apparently chosen to stay under an "
            f"authorization threshold. It matches none of the five documented patterns; similar closed cases "
            f"{'on other customers ' if repeated else ''}show the same structure. Found by scanning the card's "
            f"visible transactions for clustered near-threshold amounts."), repeated
    ring_cards = len(net.detail.get("ring_cards", [])) + sum(len(l["fraud_cards"]) for l in
                                                             net.detail.get("links", []) if l["kind"] == "DeviceProfile")
    if flagged.channel == "online" and fams["F4_device"].s > 0 and ring_cards >= T["several_cards"] - 1:
        if "undocumented" in related_patterns or memory_votes.get("undocumented", 0) > 0:
            return "undocumented", (
                f"One device profile ({flagged.profile_key}), new to each account and seen behind a proxy, is "
                f"used for online purchases on at least {ring_cards + 1} different customers' cards within "
                f"{T['window_days']} days. The activity looks like a shared-device ring rather than a single "
                f"compromised card, and earlier closed cases on the same device were not matched to a documented "
                f"typology. Found by expanding the card-device graph from the flagged transaction."), True
        return "card_not_present_new_device", "", True
    # Evidence rules from the closed-case backtest (runs/backtest/, 150 confirmed-fraud pseudo-alerts;
    # pattern accuracy 0.213 -> 0.807): online -> card-not-present, with the identity record's device flag
    # 'New' separating pattern 3 (55% vs 0% of pattern 2); in person -> out-of-region when the billing
    # region differs from the card's home region (88% of out_of_region_use vs 12% of account_takeover).
    if flagged.channel == "online":
        return ("card_not_present_new_device" if flagged.new_found == "New" else "card_not_present_fraud"), "", False
    region = fams["F5_region"].detail
    if region.get("addr1") and region.get("home") and region["addr1"] != region["home"]:
        return "out_of_region_use", "", False
    return "account_takeover", "", False


def _z(amt, fams):
    d = fams["F1_amount"].detail
    if "median_amt" not in d:
        return 0.0
    return math.log(amt / d["median_amt"])


def episode(pattern: str, fams: dict, txns: list, flagged, as_of: str) -> list:
    """Transactions believed to be part of the same episode (always includes the flagged one)."""
    by_id = {t.txn_id: t for t in txns}
    by_id[flagged.txn_id] = flagged
    ids = {flagged.txn_id}
    if pattern == "card_testing":
        ids |= set(fams["F6_testing"].entities)
    elif pattern == "undocumented" and fams["F15_structuring"].s > 0:
        ids |= set(fams["F15_structuring"].entities)
    elif pattern in ("card_not_present_fraud", "card_not_present_new_device", "undocumented"):
        lo = flagged.ts - timedelta(hours=T["burst_hours"])
        seen_products = set(fams["F2_product"].detail.get("seen", {}))
        for t in txns:
            if t.channel != "online" or not (lo <= t.ts):
                continue
            same_device = flagged.profile_key and t.profile_key == flagged.profile_key and fams["F4_device"].s > 0
            unusual = _z(t.amt, fams) > 1.0 or (seen_products and t.product_cd not in seen_products)
            if same_device or unusual:
                ids.add(t.txn_id)
    elif pattern == "out_of_region_use":
        lo = flagged.ts - timedelta(days=7)
        ids |= {t.txn_id for t in txns if t.channel == "in_person" and t.addr1 == flagged.addr1 and lo <= t.ts}
    elif pattern == "account_takeover":
        lo = flagged.ts - timedelta(days=7)
        ids |= {t.txn_id for t in txns if lo <= t.ts and (
            (flagged.profile_key and t.profile_key == flagged.profile_key) or
            (flagged.p_email and t.p_email == flagged.p_email and t.channel == "online"))}
    return sorted(ids, key=lambda i: (by_id[i].ts, i))


def familiar_aspects(fams: dict, region_familiar: bool) -> list:
    out = []
    if fams["F1_amount"].available and abs(fams["F1_amount"].detail.get("z", 99)) < 1:
        out.append("amount typical for the card")
    if fams["F2_product"].available and fams["F2_product"].s == 0:
        out.append("product code used before")
    if fams["F4_device"].detail.get("familiar"):
        out.append("device profile seen before on the card and marked Found")
    if region_familiar:
        out.append("home billing region")
    return out
