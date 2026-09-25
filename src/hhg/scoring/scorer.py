"""Evidence scorer -> fraud_probability in [0.01, 0.99] (ARCHITECTURE.md §10.3-§10.4).

Phase 1 uses fixed, documented weights (config.W, OP); no fitting. The bank risk score is
recorded as F10 but carries weight 0 (README: often wrong in both directions).
"""

import math
from dataclasses import dataclass, field

from hhg import config

T = config.T


def logit(p: float) -> float:
    return math.log(p / (1 - p))


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


@dataclass
class Assessment:
    p: float
    logit: float
    contributions: dict
    n_support: int
    n_exculpatory: int
    conflict: bool
    coverage: float
    statement: str = "none"
    history: list = field(default_factory=list)


def score(families: dict, familiar_aspects: int, statement: str = "none") -> Assessment:
    """families: name -> Family (s, available). statement: none|dispute|deny|confirm|no_reply."""
    contrib = {}
    for name, fam in families.items():
        if fam.available and name in config.W:
            contrib[name] = round(config.W[name] * fam.s, 4)
    contrib["F14_familiar"] = round(config.W["F14_familiar"] * min(familiar_aspects, 3), 4)
    x = config.INTERCEPT + sum(contrib.values())
    if statement != "none":
        contrib["F12_statement"] = round(math.log(config.LR[statement]), 4)
        x += contrib["F12_statement"]
    p = min(0.99, max(0.01, sigmoid(x)))
    sup = [k for k, c in contrib.items() if c >= T["theta"]]
    exc = [k for k, c in contrib.items() if c <= -T["theta"]]
    conflict = any(c >= T["theta_strong"] for c in contrib.values()) and any(
        c <= -T["theta_strong"] for c in contrib.values())
    applicable = [f for n, f in families.items() if n in config.W]
    coverage = sum(1 for f in applicable if f.available) / max(1, len(applicable))
    return Assessment(p=round(p, 2), logit=round(x, 4), contributions=contrib, n_support=len(sup),
                      n_exculpatory=len(exc), conflict=conflict, coverage=round(coverage, 2), statement=statement)


def update_with_response(a: Assessment, response: str) -> Assessment:
    """Apply a (simulated) customer response as a likelihood ratio (config.LR, OP)."""
    x = a.logit + math.log(config.LR[response])
    contrib = dict(a.contributions, F12_response=round(math.log(config.LR[response]), 4))
    p = min(0.99, max(0.01, sigmoid(x)))
    sup = sum(1 for c in contrib.values() if c >= T["theta"])
    exc = sum(1 for c in contrib.values() if c <= -T["theta"])
    return Assessment(p=round(p, 2), logit=round(x, 4), contributions=contrib, n_support=sup, n_exculpatory=exc,
                      conflict=a.conflict, coverage=a.coverage, statement=response, history=a.history + [a.p])


def verdict(a: Assessment, response: str = "none") -> str:
    if response == "deny":
        return "fraud"
    if response == "confirm":
        return "legitimate"
    if a.p >= T["weak_p"] and a.n_support >= 2:
        return "fraud"
    # Legitimate without a response needs two independent exculpatory pieces (README §6 standard);
    # a low probability resting on a single piece stays 'uncertain' so R1 verification applies.
    if a.p < T["case_p"] and a.n_exculpatory >= 2:
        return "legitimate"
    return "uncertain"


def stop_rule_met(a: Assessment) -> bool:
    """README §6: p >= 0.85 or <= 0.15 with at least two independent pieces of evidence."""
    return (a.p >= T["stop_hi"] and a.n_support >= 2) or (a.p <= T["stop_lo"] and a.n_exculpatory >= 2)
