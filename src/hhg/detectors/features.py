"""Evidence-family detectors (ARCHITECTURE.md §10.3), computed in Python over rows that
TigerGraph returned for this case's as_of. Pure functions: no I/O, no randomness.

Each family yields strength s in [0, 1] (direction given by its weight), the entity IDs it
rests on, and a templated claim. Unnamed Vesta columns are described as unnamed.
"""

import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from hhg import config

T = config.T
PROXY_STRONG = ("IP_PROXY:ANONYMOUS", "IP_PROXY:HIDDEN")


@dataclass
class Txn:
    txn_id: str
    ts: datetime
    amt: float
    product_cd: str
    channel: str
    risk_score: float
    addr1: str
    p_email: str
    r_email: str
    new_found: str
    proxy: str
    match_status: str
    profile_key: str
    m: dict

    @staticmethod
    def from_vertex(v: dict) -> "Txn":
        a = {k.split(".")[-1]: val for k, val in v["attributes"].items()}
        return Txn(txn_id=str(a.get("txn_id", v["v_id"])), ts=datetime.strptime(a["ts"], config.TS_FORMAT),
                   amt=float(a["amt"]), product_cd=a.get("product_cd", ""), channel=a.get("channel", ""),
                   risk_score=float(a.get("risk_score", 0)), addr1=a.get("addr1", ""), p_email=a.get("p_email", ""),
                   r_email=a.get("r_email", ""), new_found=a.get("new_found", ""), proxy=a.get("proxy_type", ""),
                   match_status=a.get("match_status", ""), profile_key=a.get("profile_key", ""),
                   m={f"m{i}": a.get(f"m{i}", "") for i in range(1, 10)})


@dataclass
class Family:
    name: str
    s: float = 0.0
    available: bool = True
    entities: list = field(default_factory=list)
    claim: str = ""
    refs: list = field(default_factory=list)
    detail: dict = field(default_factory=dict)


def _fmt(x: float) -> str:
    return f"${x:,.2f}"


def split(txns: list, flagged: Txn):
    cut = flagged.ts - timedelta(hours=T["baseline_gap_hours"])
    base = [t for t in txns if t.ts <= cut]
    recent = [t for t in txns if t.ts > cut]
    return base, recent


def amount_anomaly(base, f) -> Family:
    fam = Family("F1_amount", entities=[f.txn_id])
    amts = [math.log(t.amt) for t in base if t.amt > 0]
    if len(amts) < 5:
        fam.available, fam.claim = False, f"Fewer than 5 earlier visible transactions on the card; no amount baseline"
        return fam
    med = statistics.median(amts)
    mad = statistics.median([abs(a - med) for a in amts])
    z = (math.log(f.amt) - med) / (1.4826 * mad + 0.1)
    fam.detail = {"z": round(z, 2), "median_amt": round(math.exp(med), 2), "n_base": len(amts)}
    fam.s = max(0.0, min(1.0, (z - 2) / 3))
    fam.claim = (f"Flagged amount {_fmt(f.amt)} vs card median {_fmt(math.exp(med))} over {len(amts)} earlier "
                 f"visible transactions (robust z = {z:.1f})")
    return fam


def product_novelty(base, f) -> Family:
    fam = Family("F2_product", entities=[f.txn_id])
    seen = Counter(t.product_cd for t in base)
    if sum(seen.values()) < 3:
        fam.available, fam.claim = False, "Too little card history to judge product code novelty"
        return fam
    fam.s = 0.0 if f.product_cd in seen else 1.0
    fam.detail = {"product_cd": f.product_cd, "seen": dict(seen)}
    fam.claim = (f"Product code {f.product_cd} " + ("never used on this card before"
                 if fam.s else f"used {seen[f.product_cd]} times before on this card"))
    return fam


def burst(txns, base, f, as_of) -> Family:
    fam = Family("F3_burst")
    lo = f.ts - timedelta(hours=T["burst_hours"])
    window = [t for t in txns if t.channel == "online" and lo <= t.ts <= as_of]
    n = len(window)
    base_online = [t for t in base if t.channel == "online"]
    span_days = max(1.0, (f.ts - min(t.ts for t in base)).total_seconds() / 86400) if base else 1.0
    expected = len(base_online) / span_days * (T["burst_hours"] / 24)
    fam.entities = [t.txn_id for t in window]
    fam.detail = {"n_online_48h": n, "expected_48h": round(expected, 2)}
    if n >= 2 and n >= 3 * expected + 2:
        fam.s = min(1.0, (n - 1) / 3)
    fam.claim = (f"{n} online transactions on the card in the 48 hours up to the alert "
                 f"(about {expected:.1f} expected from the card's visible history)")
    return fam


def device_novelty(base, f) -> Family:
    fam = Family("F4_device", entities=[f.txn_id])
    if f.channel != "online" or not (f.profile_key or f.new_found):
        fam.available, fam.claim = False, "No device record for the flagged transaction"
        return fam
    seen = {t.profile_key for t in base if t.profile_key}
    new_to_card = bool(f.profile_key) and bool(seen) and f.profile_key not in seen
    marked_new = f.new_found == "New"
    proxy = f.proxy in PROXY_STRONG
    fam.detail = {"profile": f.profile_key, "id_15": f.new_found, "proxy": f.proxy, "new_to_card": new_to_card,
                  "familiar": bool(f.profile_key) and f.profile_key in seen and f.new_found == "Found"}
    if marked_new or new_to_card:
        fam.s = 0.6 + (0.4 if proxy else 0.0)
    fam.claim = (f"Device profile '{f.profile_key or 'unknown'}': identity marks it {f.new_found or 'unmarked'}"
                 + ("; not seen on this card before" if new_to_card else "")
                 + (f"; behind {f.proxy}" if f.proxy else ""))
    return fam


def region_context(txns, base, f, as_of) -> tuple:
    fam, trip = Family("F5_region", entities=[f.txn_id]), Family("F5_trip", entities=[f.txn_id])
    regions = Counter(t.addr1 for t in base if t.addr1)
    if not f.addr1 or sum(regions.values()) < 3:
        fam.available = trip.available = False
        fam.claim = trip.claim = "No usable billing-region history for the card"
        return fam, trip, False
    home = regions.most_common(1)[0][0]
    novel = f.addr1 not in regions
    lo = f.ts - timedelta(hours=72)
    concurrent_home = any(t.addr1 == home and t.txn_id != f.txn_id and lo <= t.ts <= as_of for t in txns)
    new_days = {t.ts.date() for t in txns if t.addr1 == f.addr1 and f.ts - timedelta(days=7) <= t.ts <= as_of}
    fam.detail = {"addr1": f.addr1, "home": home, "novel": novel, "concurrent_home": concurrent_home,
                  "days_in_new_region": len(new_days)}
    trip.detail = fam.detail
    if novel and f.channel == "in_person":
        if concurrent_home:
            fam.s = 1.0
        elif len(new_days) >= 2:
            trip.s = 1.0
        else:
            fam.s = 0.5
    fam.claim = (f"Billing region {f.addr1} " + ("has no history on this card" if novel else "is familiar")
                 + f"; home region {home}" + ("; home-region activity continued within 72 hours"
                                               if concurrent_home else ""))
    trip.claim = (f"{len(new_days)} distinct days of purchases in region {f.addr1} without concurrent "
                  f"home-region activity, consistent with a trip")
    return fam, trip, (not novel and f.addr1 == home)


def card_testing(txns, f, as_of) -> Family:
    fam = Family("F6_testing")
    lo = f.ts - timedelta(hours=24)
    online = sorted([t for t in txns if t.channel == "online" and lo <= t.ts <= as_of], key=lambda t: (t.ts, t.txn_id))
    small = [t for t in online if t.amt <= T["small_auth_max"]]
    win = timedelta(minutes=T["testing_window_min"])
    for i in range(len(small)):
        seq = [s for s in small[i:] if s.ts - small[i].ts <= win]
        if len(seq) >= T["testing_min_count"]:
            later = [t for t in online if t.ts >= seq[-1].ts and t.amt > T["small_auth_max"]
                     and t.ts - seq[-1].ts <= timedelta(hours=24)]
            if later:
                fam.s = 1.0
                fam.entities = [t.txn_id for t in seq + later]
                cleared = any(t.amt > T["testing_block_amt"] for t in later)
                fam.detail = {"small": [t.txn_id for t in seq], "larger": [t.txn_id for t in later],
                              "cleared_over_100": cleared}
                fam.claim = (f"{len(seq)} online authorizations of at most {_fmt(T['small_auth_max'])} within "
                             f"{T['testing_window_min']} minutes, followed by {len(later)} larger online purchase(s)"
                             f" totalling {_fmt(sum(t.amt for t in later))}")
                return fam
    fam.claim = "No card-testing sequence (3+ small online authorizations within an hour, then a larger purchase)"
    return fam


def threshold_avoidance(txns, f, as_of) -> Family:
    """Repeated online purchases just under a round authorization threshold within an hour
    (the pattern described in undocumented closed cases, e.g. 'each just under $500')."""
    fam = Family("F15_structuring")
    lo = f.ts - timedelta(hours=24)
    online = sorted([t for t in txns if t.channel == "online" and lo <= t.ts <= as_of], key=lambda t: (t.ts, t.txn_id))
    for limit in (100.0, 250.0, 500.0, 1000.0, 2500.0):
        near = [t for t in online if 0.9 * limit <= t.amt < limit]
        for i in range(len(near)):
            seq = [t for t in near[i:] if t.ts - near[i].ts <= timedelta(minutes=60)]
            if len(seq) >= 3 and f.txn_id in {t.txn_id for t in seq}:
                fam.s = 1.0
                fam.entities = [t.txn_id for t in seq]
                fam.detail = {"threshold": limit, "txns": fam.entities}
                fam.claim = (f"{len(seq)} online purchases within 60 minutes each just under {_fmt(limit)} "
                             f"({', '.join(_fmt(t.amt) for t in seq)}), consistent with staying under an "
                             f"authorization threshold")
                return fam
    fam.claim = "No repeated purchases just under a round threshold"
    return fam


def takeover(txns, base, recent, f) -> Family:
    fam = Family("F7_takeover", entities=[f.txn_id])
    if len(base) < 5:
        fam.available, fam.claim = False, "Too little card history to judge credential anomalies"
        return fam
    anomalies = []
    if len({t.channel for t in base}) == 1 and len({t.channel for t in recent}) == 2:
        anomalies.append("mixed-channel activity where the card was single-channel")
    flips = [k for k, v in f.m.items() if v == "F" and sum(1 for t in base if t.m.get(k) == "T") >= 3
             and sum(1 for t in base if t.m.get(k) == "T") > sum(1 for t in base if t.m.get(k) == "F")]
    if flips:
        anomalies.append(f"match flags {', '.join(k.upper() for k in flips)} false where history is mostly true")
    ms = Counter(t.match_status for t in base if t.match_status)
    if f.match_status and ms and f.match_status not in ms:
        anomalies.append(f"identity match status {f.match_status} not seen before")
    emails = {t.p_email for t in base if t.p_email}
    if f.p_email and len(emails) >= 1 and f.p_email not in emails:
        anomalies.append(f"purchaser email domain {f.p_email} new to the card")
    fam.detail = {"anomalies": anomalies}
    fam.s = 0.0 if len(anomalies) < 2 else min(1.0, (len(anomalies) - 1) / 2)
    fam.claim = ("Credential anomalies: " + "; ".join(anomalies)) if anomalies else "No credential anomalies found"
    return fam


def recurring(base, f) -> Family:
    fam = Family("F13_recurring", entities=[f.txn_id])
    tol = T["recurring_tol"] * f.amt
    matches = sorted([t for t in base if t.product_cd == f.product_cd and abs(t.amt - f.amt) <= tol],
                     key=lambda t: t.ts)
    chain = matches + [f]
    gaps = [(b.ts - a.ts).days for a, b in zip(chain, chain[1:])]
    ok = (len(matches) >= T["recurring_min_occ"] and gaps
          and all(T["recurring_min_days"] <= g <= T["recurring_max_days"] for g in gaps[-T["recurring_min_occ"]:]))
    fam.s = 1.0 if ok else 0.0
    fam.entities = [t.txn_id for t in chain] if ok else [f.txn_id]
    fam.detail = {"matches": [t.txn_id for t in matches], "gaps_days": gaps}
    fam.claim = (f"Recurring charge: {len(matches)} earlier product {f.product_cd} charges within 2% of "
                 f"{_fmt(f.amt)} at {gaps} day intervals (no merchant field exists; approximated by product "
                 f"code and amount)") if ok else "No monthly recurring charge matching the flagged amount"
    return fam


def network(shared: dict, ring: dict, card_id: str) -> tuple:
    """F8 from shared_origin_scan (and optional ring expansion). Returns family, linked
    cards (fraud-indicated), linking device profiles, capped elements."""
    fam = Family("F8_network")
    types = {str(e["v_id"]): e["v_type"] for e in shared.get("elements", [])}
    card_info = {str(c["v_id"]): c["attributes"] for c in shared.get("cards", [])}

    def fraud_ids(attrs):
        a = {k.split(".")[-1]: v for k, v in attrs.items()}
        return sorted(set(a.get("@fraud_closed_cases", []) + a.get("@fraud_agent_cases", [])))

    links, linked_cards, devices, partial = [], set(), set(), []
    element_fraud = shared.get("element_fraud_cards") or {}   # fraud FROM the element in the window (R6)
    for el, cards in (shared.get("element_cards") or {}).items():
        fraud_cards = [c for c in element_fraud.get(el, []) if c != card_id and c in cards]
        kind = types.get(el, "?")
        if kind == "DeviceProfile" and "?" in el.split(" | "):
            if fraud_cards:
                partial.append({"element": el, "fraud_cards": len(fraud_cards)})
            continue  # a partial tuple is a common configuration, not the same device profile
        if fraud_cards:
            links.append({"element": el, "kind": kind, "fraud_cards": sorted(fraud_cards),
                          "cases": sorted({x for c in fraud_cards for x in fraud_ids(card_info[c])})})
            linked_cards.update(fraud_cards)
            if kind == "DeviceProfile":
                devices.add(el)
    ring_cards = []
    if ring and not ring.get("capped"):
        for c in ring.get("cards", []):
            cid, attrs = str(c["v_id"]), c["attributes"]
            a = {k.split(".")[-1]: v for k, v in attrs.items()}
            if cid != card_id and a.get("@new_device_txns", 0) > 0:   # unlabeled ring signal: device New on the card
                ring_cards.append(cid)
    best = max([len(l["fraud_cards"]) * (1.0 if l["kind"] == "DeviceProfile" else 0.5) for l in links] or [0])
    fam.s = 1.0 if best >= 2 or len(ring_cards) >= T["several_cards"] - 1 else (0.5 if best >= 1 else 0.0)
    fam.entities = sorted(linked_cards | set(ring_cards))
    fam.detail = {"links": links, "ring_cards": sorted(ring_cards), "capped": shared.get("capped", []),
                  "partial_profiles_excluded": partial}
    if links:
        top = sorted(links, key=lambda l: (-len(l["fraud_cards"]), l["element"]))[0]
        fam.claim = (f"{top['kind']} '{top['element']}' is shared in the last {T['window_days']} days with "
                     f"{len(top['fraud_cards'])} other card(s) whose confirmed-fraud transactions used it in that window "
                     f"({', '.join(top['cases'][:5])})")
    elif ring_cards:
        fam.claim = (f"Device ring: {len(ring_cards)} other customers' cards used the same fully specified device "
                     f"profile in the last {T['window_days']} days, each with window transactions whose identity record "
                     f"marks the device New")
    else:
        fam.claim = f"No shared device, region or recipient email links to other cards' visible fraud in {T['window_days']} days"
    return fam, sorted(linked_cards | set(ring_cards)), sorted(devices), shared.get("capped", [])


def prior_fraud(history: dict, card_id: str) -> Family:
    fam = Family("F9_prior")
    rows = [{k.split(".")[-1]: v for k, v in c["attributes"].items()} for c in history.get("closed_on_card", [])]
    hits = [r for r in rows if r.get("card_id") == card_id and r.get("outcome") == "confirmed_fraud"]
    fam.s = 1.0 if hits else 0.0
    fam.entities = sorted(r["case_id"] for r in hits)
    fam.claim = (f"{len(hits)} earlier confirmed-fraud closed case(s) on this card, closed before the alert"
                 if hits else "No earlier confirmed fraud on this card before the alert")
    return fam


def memory(similar: dict) -> tuple:
    """F11: similarity-weighted fraud share of retrieved closed cases, prior-shifted."""
    fam = Family("F11_memory")
    rows = []
    for c in similar.get("closed", []):
        a = {k.split(".")[-1]: v for k, v in c["attributes"].items()}
        if float(a.get("@score", 0)) >= T["memory_min_sim"]:
            rows.append(a)
    if not rows:
        fam.available, fam.claim = False, "No sufficiently similar closed cases retrieved"
        return fam, []
    w = sum(float(r["@score"]) for r in rows)
    share = sum(float(r["@score"]) for r in rows if r["outcome"] == "confirmed_fraud") / w
    share = min(max(share, 0.02), 0.98)
    shift = math.log(share / (1 - share)) - math.log(config.HISTORY_FRAUD_RATE / (1 - config.HISTORY_FRAUD_RATE))
    fam.s = max(-1.0, min(1.0, shift / 2))
    cited = [r["case_id"] for r in rows][: T["memory_cite_max"]]
    votes = Counter(r["pattern"] for r in rows)
    fam.entities = cited
    fam.detail = {"fraud_share": round(share, 3), "n": len(rows), "pattern_votes": dict(votes)}
    fam.claim = (f"{len(rows)} similar closed cases (lexical similarity ≥ {T['memory_min_sim']}): weighted fraud "
                 f"share {share:.2f} vs history base rate {config.HISTORY_FRAUD_RATE:.2f}; patterns {dict(votes)}")
    return fam, cited
