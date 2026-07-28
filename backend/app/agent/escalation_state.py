# escalation_state.py
# A shared, thread-safe dictionary to track the state of escalated actions.
# action_id -> "pending" | "approved" | "denied"
pending_escalations = {}
