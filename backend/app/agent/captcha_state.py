# captcha_state.py
# A shared, thread-safe dictionary to track CAPTCHA pause/resume state,
# mirroring escalation_state.py's pattern.
# session_id (== trace_id) -> "pending" | "resolved"
pending_captchas = {}
