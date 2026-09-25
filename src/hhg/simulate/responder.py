"""Deterministic evidence-response simulator (ARCHITECTURE.md §13). Customer and analyst
replies are not provided by the dataset; every response here is an explicit, recomputable
assumption derived only from the pre-response assessment (T8)."""

from hhg import config

T = config.T


def request_type(channel: str, device_or_takeover_signal: bool, trigger_type: str) -> str:
    if channel == "online" and device_or_takeover_signal and trigger_type != "customer_report":
        return "step_up_auth"
    return "customer_validation"


def respond(p_pre: float, req_type: str, *, flagged_id: str, pattern_hint: str, region: str,
            recurring: bool, clearance_reason: str) -> tuple:
    """Returns (response class, assumed_response text)."""
    if recurring:
        return "confirm", ("Simulated: customer recognises the charge as their own monthly recurring payment "
                           "(recurring-charge match found before the request)")
    if p_pre >= T["sim_deny"]:
        cls = "deny"
        if req_type == "step_up_auth":
            text = f"Simulated: step-up authentication for further activity was not completed (treated as denial)"
        elif pattern_hint == "out_of_region_use":
            text = f"Simulated: customer states they did not make transaction {flagged_id} and were not in region {region}"
        else:
            text = f"Simulated: customer states they did not make transaction {flagged_id} and still has the card"
        return cls, f"{text} (pre-response probability {p_pre:.2f} ≥ {T['sim_deny']:.2f} deny threshold)"
    if p_pre <= T["sim_confirm"]:
        reason = {"travel": "confirms they were travelling in the billing region in question",
                  "new_phone": "confirms the purchase was made from their new phone",
                  "intent": "confirms the purchase; the amount was unusual but intended"}.get(
            clearance_reason, f"confirms they made transaction {flagged_id}")
        if req_type == "step_up_auth":
            return "confirm", (f"Simulated: step-up authentication passed by the cardholder "
                               f"(pre-response probability {p_pre:.2f} ≤ {T['sim_confirm']:.2f} confirm threshold)")
        return "confirm", (f"Simulated: customer {reason} (pre-response probability {p_pre:.2f} ≤ "
                           f"{T['sim_confirm']:.2f} confirm threshold)")
    return "no_reply", (f"Simulated: no reply within 24 hours (pre-response probability {p_pre:.2f} is between "
                        f"the {T['sim_confirm']:.2f} confirm and {T['sim_deny']:.2f} deny thresholds)")
