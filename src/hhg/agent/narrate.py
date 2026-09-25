"""Deterministic narrative templates (--llm off). Every ID, amount and date comes from
the case fact sheet; nothing is invented."""

PATTERN_TEXT = {
    "card_testing": "card testing", "card_not_present_fraud": "card-not-present fraud",
    "card_not_present_new_device": "card-not-present fraud from a new device",
    "out_of_region_use": "out-of-region use", "account_takeover": "account takeover",
    "undocumented": "an undocumented pattern", "none": "no fraud pattern",
}


def _m(x):
    return f"${x:,.2f}"


def _clean(text: str) -> str:
    """Free text shows unknown device-profile parts as 'unknown' (IDs in evidence keep '?')."""
    import re
    return re.sub(r"(?<![\w])\?(?![\w])", "unknown", text)


def summary(f: dict) -> str:
    s = [f"Alert on transaction {f['flagged']} ({_m(f['flagged_amt'])}, {f['channel']}) for card {f['card']} "
         f"was triggered by {f['trigger_desc']}."]
    if f["verdict"] == "legitimate":
        s.append(f"Assessed fraud probability is {f['p']:.2f}; the activity is judged legitimate.")
    elif f["verdict"] == "fraud":
        s.append(f"Assessed fraud probability is {f['p']:.2f}; the activity is judged fraud "
                 f"({PATTERN_TEXT[f['pattern']]}) covering {f['n_affected']} transaction(s) and {_m(f['exposure'])}.")
    else:
        s.append(f"Assessed fraud probability is {f['p']:.2f}; the evidence does not settle the question "
                 f"(leading hypothesis: {PATTERN_TEXT[f['pattern']]}).")
    if f["key_evidence"]:
        s.append("Key evidence: " + "; ".join(f["key_evidence"][:3]) + ".")
    if f["response"] != "none":
        s.append(f"A {f['request_type'].replace('_', ' ')} request was made and its response was simulated "
                 f"as '{f['response']}'.")
    s.append("Final actions: " + ", ".join(f["final_actions"]) + ".")
    return _clean(" ".join(s))


def what_changed(f: dict) -> str:
    if f["response"] == "none":
        return "nothing"
    added = [a for a in f["final_actions"] if a not in f["initial_actions"]]
    dropped = [a for a in f["initial_actions"] if a not in f["final_actions"]]
    s = (f"The simulated {f['response'].replace('_', ' ')} response moved the fraud probability from "
         f"{f['p_initial']:.2f} to {f['p']:.2f} and the verdict to {f['verdict']}.")
    if added or dropped:
        s += (" Final actions" + (f" add {', '.join(added)}" if added else "")
              + (" and" if added and dropped else "") + (f" drop {', '.join(dropped)}" if dropped else "") + ".")
    return s


def stop_reason(f: dict) -> str:
    if f["response"] in ("deny", "confirm"):
        return (f"The simulated verification response settled the question (README §6); probability "
                f"{f['p']:.2f}. Further steps would not change the actions.")
    if f["stop_rule"]:
        return (f"Stopping rule met: probability {f['p_initial']:.2f} with {f['n_indep']} independent pieces of "
                f"evidence (README §6); further steps would not change the decision.")
    if f["response"] == "no_reply":
        return ("No reply within 24 hours was assumed; policy R4 actions apply and the remaining uncertainty is "
                "handed on as recorded. Further automated steps are unlikely to change the decision.")
    return ("The customer's own statement in the alert and the graph evidence already determine the policy "
            "actions; further steps are unlikely to change the decision (README §6).")


def sar_narrative(f: dict) -> str:
    s = [
        f"This report concerns customer {f['customer']} and card {f['card']}.",
        f"Between {f['first_date']} and {f['last_date']}, {f['n_affected']} transaction(s) totalling "
        f"{_m(f['exposure'])} were identified as part of one suspicious episode ({', '.join(f['affected'][:8])}).",
        f"The activity was {f['channel_desc']} and the alert was raised by {f['trigger_desc']} on transaction "
        f"{f['flagged']}.",
        f"The activity is assessed as {PATTERN_TEXT[f['pattern']]} with a fraud probability of {f['p']:.2f}.",
    ]
    for ev in f["key_evidence"][:3]:
        s.append(ev.rstrip(".") + ".")
    if f["connected_cards"]:
        s.append(f"The same origin links this card to {len(f['connected_cards'])} other card(s): "
                 f"{', '.join(f['connected_cards'][:6])}.")
    if f["device_profiles"]:
        s.append(f"Linked device profile(s): {'; '.join(f['device_profiles'][:2])}.")
    if f["response"] != "none":
        s.append(f"A simulated {f['request_type'].replace('_', ' ')} response was recorded as '{f['response']}'.")
    s.append(f"It is suspicious because {f['why']}.")
    s.append("Recommended actions: " + ", ".join(f["final_actions"]) + ".")
    s.append("All amounts are in USD; product codes and region codes are dataset codes, and no merchant "
             "identifiers exist in the data.")
    while len(s) < 6:
        s.append("No further facts were established.")
    return _clean(" ".join(s[:12]))
