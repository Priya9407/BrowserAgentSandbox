"""
verification_state.py

Shared, thread-safe dictionary to track the state of in-flight extension actions
that need verification feedback before the next action is emitted.

action_id -> {
    "status": "pending" | "completed" | "failed",
    "result": dict | None,   # action_result payload from side panel
}
"""

pending_verifications: dict[str, dict] = {}
