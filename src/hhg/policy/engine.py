"""Deterministic policy engine: README Fraud Policy R1-R10 are the decision authority
(ARCHITECTURE.md §10.2, §10.5, §10.6). Pure functions; the LLM never supplies inputs."""

from dataclasses import dataclass, field

from hhg import config

T = config.T

ORDER = ["ALLOW_TRANSACTION", "DECLINE_TRANSACTION", "STEP_UP_AUTH", "VERIFY_WITH_CUSTOMER", "BLOCK_CARD",
         "BLOCK_ALL_CARDS", "CREATE_CASE", "GENERATE_REPORT", "FILE_REPORT", "MONITOR_CARD",
         "MONITOR_CONNECTED_CARDS", "WARN_CUSTOMER", "ESCALATE_TO_ANALYST", "CLOSE_NO_FRAUD"]
AUTO = {"ALLOW_TRANSACTION", "MONITOR_CARD", "MONITOR_CONNECTED_CARDS", "WARN_CUSTOMER", "VERIFY_WITH_CUSTOMER",
        "STEP_UP_AUTH", "GENERATE_REPORT", "CREATE_CASE", "ESCALATE_TO_ANALYST", "CLOSE_NO_FRAUD"}
BLOCKS = {"BLOCK_CARD", "BLOCK_ALL_CARDS"}


class PolicyViolation(AssertionError):
    pass


def route(action: str, exposure: float) -> str:
    """README §2 approval routing."""
    if action in AUTO:
        return "auto"
    if action == "DECLINE_TRANSACTION":
        return "L1"
    if action == "BLOCK_CARD":
        return "L1" if exposure <= T["block_l1_max"] else "L2"
    if action in ("BLOCK_ALL_CARDS", "FILE_REPORT"):
        return "L2"
    raise ValueError(f"unknown action {action}")


@dataclass
class PolicyInput:
    trigger_type: str
    p: float
    n_support: int
    n_exculpatory: int
    conflict: bool
    verdict: str
    pattern: str
    exposure: float
    response: str = "none"               # none | deny | confirm | no_reply
    card_testing: bool = False
    cleared_over_100: bool = False
    recurring_match: bool = False
    shared_link: bool = False
    shared_element: str = ""
    shared_cards: int = 0
    coordinated_cross_customer: bool = False
    confirmed_fraud_cards: int = 0
    credentials_compromised: bool = False
    customer_visible_cards: int = 1
    evidence_requested: bool = False
    evidence_request_type: str = ""      # customer_validation | step_up_auth (when requested)
    online_device_signal: bool = False

    @property
    def dispute(self) -> bool:
        return self.trigger_type == "customer_report"


@dataclass
class Decision:
    actions: list
    fired: list = field(default_factory=list)
    guards: list = field(default_factory=list)


def _cite(reasons: dict, action: str, text: str):
    reasons.setdefault(action, [])
    if text not in reasons[action]:
        reasons[action].append(text)


def decide(x: PolicyInput) -> Decision:
    r, fired, guards = {}, [], []
    denies = x.response == "deny" or (x.dispute and not x.recurring_match and x.response in ("none", "deny"))
    exp = f"${x.exposure:,.2f}"

    # R1: weak single signal -> verify before any block
    # (R1 guards blocking; it has nothing to verify once the verdict is already legitimate)
    r1 = (x.n_support <= 1 and x.p < T["weak_p"] and x.response == "none" and not x.dispute
          and x.verdict != "legitimate")
    if r1:
        fired.append("R1")
        act = "STEP_UP_AUTH" if x.online_device_signal else "VERIFY_WITH_CUSTOMER"
        _cite(r, act, f"R1: case rests on at most one signal and probability {x.p:.2f} < 0.70; verify before any block")
    # R2: customer denies
    if denies:
        fired.append("R2")
        who = "customer denied the transaction (simulated response)" if x.response == "deny" else \
            "customer disputes the transaction in the alert"
        _cite(r, "BLOCK_CARD", f"R2: {who}; exposure {exp} {'≤' if x.exposure <= T['block_l1_max'] else '>'} $2,500")
        _cite(r, "CREATE_CASE", f"R2: {who}")
        if x.exposure > T["report_exposure"] or x.shared_link:
            why = f"exposure {exp} > $1,000" if x.exposure > T["report_exposure"] else \
                f"connects to shared {x.shared_element or 'origin'} with another card's fraud"
            _cite(r, "FILE_REPORT", f"R2: {why}")
    # R3: customer confirms
    if x.response == "confirm":
        fired.append("R3")
        _cite(r, "CLOSE_NO_FRAUD", "R3: customer confirmed the transaction (simulated response); noted in case file")
    # R4: no reply within 24 hours
    if x.response == "no_reply":
        fired.append("R4")
        _cite(r, "MONITOR_CARD", "R4: no reply within 24 hours (simulated)")
        _cite(r, "DECLINE_TRANSACTION", "R4: no reply within 24 hours; decline pending authorizations")
        if x.exposure > T["escalate_exposure"]:
            _cite(r, "ESCALATE_TO_ANALYST", f"R4: no reply and exposure {exp} > $500")
    # R5: card testing
    if x.card_testing:
        fired.append("R5")
        _cite(r, "DECLINE_TRANSACTION", "R5: card-testing sequence observed")
        _cite(r, "STEP_UP_AUTH", "R5: card-testing sequence observed")
        if x.cleared_over_100:
            _cite(r, "BLOCK_CARD", "R5: a purchase over $100 has already cleared after the testing sequence")
    # R6: shared origin
    if x.shared_link and x.shared_cards + 1 >= T["several_cards"]:
        fired.append("R6")
        el = x.shared_element or "shared origin"
        for act in ("CREATE_CASE", "FILE_REPORT", "MONITOR_CONNECTED_CARDS"):
            _cite(r, act, f"R6: {x.shared_cards + 1} cards show fraud sharing {el} within {T['window_days']} days")
    # R7: disputed but matches own recurring pattern
    if x.dispute and x.recurring_match:
        fired.append("R7")
        for act in ("CREATE_CASE", "VERIFY_WITH_CUSTOMER", "WARN_CUSTOMER"):
            if not (act == "VERIFY_WITH_CUSTOMER" and x.response == "confirm"):
                _cite(r, act, "R7: disputed charge matches the customer's own monthly recurring charge; do not block")
    # R8: uncertain and exposed, or conflicting evidence
    if (x.verdict == "uncertain" and x.exposure > T["escalate_exposure"]) or x.conflict:
        fired.append("R8")
        why = "evidence conflicts" if x.conflict else f"verdict uncertain and exposure {exp} > $500"
        _cite(r, "ESCALATE_TO_ANALYST", f"R8: {why}")
    # R9: undocumented coordinated abuse
    if x.pattern == "undocumented" and x.coordinated_cross_customer:
        fired.append("R9")
        for act in ("CREATE_CASE", "FILE_REPORT", "ESCALATE_TO_ANALYST"):
            _cite(r, act, "R9: coordinated or repeated abuse across customers matching no documented pattern")
    # §6 stop, fraud side: multi-signal high probability (R1 does not apply)
    if x.p >= T["stop_hi"] and x.n_support >= 2 and x.response == "none" and not x.recurring_match:
        fired.append("§6")
        _cite(r, "BLOCK_CARD", f"§6: probability {x.p:.2f} ≥ 0.85 with {x.n_support} independent signals; "
                               f"R1 does not apply; exposure {exp}")
        _cite(r, "CREATE_CASE", f"§6/§3a: probability {x.p:.2f} ≥ 0.30")
    # §3b: when evidence is requested, the initial list carries the request itself
    if x.evidence_requested and x.response == "none" and x.evidence_request_type:
        act = "STEP_UP_AUTH" if x.evidence_request_type == "step_up_auth" else "VERIFY_WITH_CUSTOMER"
        _cite(r, act, "§3b: evidence requested before the final recommendation")
    # §3a: open a case
    if x.p >= T["case_p"] or x.evidence_requested or x.dispute:
        why = "evidence requested" if x.evidence_requested else ("customer dispute" if x.dispute
                                                                 else f"probability {x.p:.2f} ≥ 0.30")
        _cite(r, "CREATE_CASE", f"§3a: {why}")
    # §3a: report when confirmed/strongly suspected and a condition holds
    if (x.verdict == "fraud" or x.p >= T["weak_p"]) and (x.exposure > T["report_exposure"] or x.shared_link):
        why = f"exposure {exp} > $1,000" if x.exposure > T["report_exposure"] else \
            f"shared {x.shared_element or 'origin'} links to another card's fraud"
        _cite(r, "FILE_REPORT", f"§3a: fraud strongly suspected and {why}")
    # Legitimate closure
    if x.verdict == "legitimate" and x.response in ("none", "confirm"):
        _cite(r, "CLOSE_NO_FRAUD", "§6: verdict legitimate" if x.response == "none" else "R3")
        if "CREATE_CASE" not in r:
            _cite(r, "ALLOW_TRANSACTION", "§6: legitimate with at least two independent exculpatory signals; no case needed (§3a)")
            _cite(r, "GENERATE_REPORT", "§3a: probability below 0.30 and no dispute; internal write-up without a case")

    # ---- guards
    if (x.n_support <= 1 and x.p < T["weak_p"] and x.response != "deny" and not x.card_testing
            and not (x.dispute and not x.recurring_match)):
        for b in BLOCKS & set(r):
            r.pop(b)
            guards.append(f"GD1 removed {b} (R1)")
    if "R7" in fired:
        for b in BLOCKS & set(r):
            r.pop(b)
            guards.append(f"GD2 removed {b} (R7)")
    if x.verdict == "legitimate":
        for a in list(BLOCKS | {"DECLINE_TRANSACTION", "FILE_REPORT"}):
            if a in r:
                r.pop(a)
                guards.append(f"GD5 removed {a} (legitimate)")
    if "CLOSE_NO_FRAUD" in r and BLOCKS & set(r):
        r.pop("CLOSE_NO_FRAUD")
        guards.append("GD6 removed CLOSE_NO_FRAUD (block present)")
    if "ALLOW_TRANSACTION" in r and "DECLINE_TRANSACTION" in r:
        r.pop("ALLOW_TRANSACTION")
        guards.append("GD6 removed ALLOW_TRANSACTION (decline present)")
    if "FILE_REPORT" in r:
        strong = x.verdict == "fraud" or x.p >= T["weak_p"] or x.response == "deny" or "R9" in fired or "R6" in fired
        if not strong:
            r.pop("FILE_REPORT")
            guards.append("GD4 removed FILE_REPORT (not confirmed or strongly suspected)")
        else:
            _cite(r, "CREATE_CASE", "§3a: a report always has a case behind it")
    # R10: BLOCK_ALL_CARDS only under its condition (replaces BLOCK_CARD)
    if "BLOCK_CARD" in r and (x.confirmed_fraud_cards >= 2 or x.credentials_compromised) \
            and x.customer_visible_cards > 1:
        r["BLOCK_ALL_CARDS"] = r.pop("BLOCK_CARD") + [
            "R10: at least two of the customer's cards show confirmed fraud or credentials are compromised"]
        fired.append("R10")

    actions = [{"action": a, "route": route(a, x.exposure), "reason": "; ".join(r[a])} for a in ORDER if a in r]
    check_invariants(actions, x)
    return Decision(actions=actions, fired=fired, guards=guards)


def check_invariants(actions: list, x: PolicyInput):
    names = [a["action"] for a in actions]
    if len(names) != len(set(names)):
        raise PolicyViolation("GD8 duplicate actions")
    if names != [a for a in ORDER if a in names]:
        raise PolicyViolation("GD8 not in canonical order")
    for a in actions:
        if a["route"] != route(a["action"], x.exposure):
            raise PolicyViolation(f"GD7 wrong route for {a['action']}")
        if not any(tag in a["reason"] for tag in [f"R{i}" for i in range(1, 11)] + ["§3a", "§3b", "§6"]):
            raise PolicyViolation(f"GD9 reason without rule citation: {a}")
    if "BLOCK_ALL_CARDS" in names and not (x.confirmed_fraud_cards >= 2 or x.credentials_compromised):
        raise PolicyViolation("GD3 BLOCK_ALL_CARDS without R10 condition")
    if "FILE_REPORT" in names and "CREATE_CASE" not in names:
        raise PolicyViolation("GD4 report without case")
    if "ALLOW_TRANSACTION" in names and "DECLINE_TRANSACTION" in names:
        raise PolicyViolation("GD6 allow and decline together")
    if "CLOSE_NO_FRAUD" in names and BLOCKS & set(names):
        raise PolicyViolation("GD6 close together with block")
