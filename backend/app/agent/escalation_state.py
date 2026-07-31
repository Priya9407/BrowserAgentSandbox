# escalation_state.py
# A shared, thread-safe dictionary to track the state of escalated actions.
# action_id -> "pending" | "approved" | "denied"
pending_escalations = {}

# Global toggle for skipping low/unknown risk escalations
# SAFETY: auto-approve NEVER applies to PAYMENT, SEND, or CREDENTIAL actions.
# These are always escalated regardless of this toggle.
auto_approve_low_unknown = False

# Risk categories that are NEVER auto-approved
_AUTO_APPROVE_BLOCKLIST = {"PAYMENT", "SEND", "CREDENTIAL"}


def should_auto_approve(category: str) -> bool:
    """
    Returns True only if:
    1. auto_approve_low_unknown is enabled, AND
    2. The risk category is NOT in the blocklist (payment, send, credential)
    """
    if not auto_approve_low_unknown:
        return False
    if category.upper() in _AUTO_APPROVE_BLOCKLIST:
        return False
    return True


def get_escalation_with_timeout(action_id: str, timeout_ms: int = 60000) -> str | None:
    """
    Wait for an escalation decision with a timeout.
    Returns "approved", "denied", or None (timed out).
    """
    import time as _time
    start = _time.time()
    while _time.time() - start < timeout_ms / 1000:
        state = pending_escalations.get(action_id)
        if state and state != "pending":
            return state
        import time as _t
        _t.sleep(0.5)
    # Timed out — mark it and return None
    if action_id in pending_escalations:
        pending_escalations[action_id] = "timed_out"
    return None
