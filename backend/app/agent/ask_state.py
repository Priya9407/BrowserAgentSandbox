"""
ask_state.py — Global state for tracking pending 'ask' actions
"""

# trace_id -> {"status": "pending" | "resolved", "question": str, "answer": str | None}
pending_asks: dict[str, dict] = {}
