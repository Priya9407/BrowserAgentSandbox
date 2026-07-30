"""
Hard pre-condition: NO action reaches Playwright without non-empty reasoning.
For fill/type actions specifically, cited_source_text is also required since
those are the actions most susceptible to prompt injection via hidden DOM.

Clicks, scrolls, and other navigation-like actions are allowed without a
citation — the policy engine still classifies and controls them.
"""

from app.schemas.action_schema import AgentAction


class GateRejected(Exception):
    pass


# Any direct browser action that interacts with content must include a citation.
# Only terminal/non-interactive actions like `done`, `ask`, `navigate`, and
# `scroll` may omit citation fields.

def enforce_action_contract(action: AgentAction) -> None:
    if not action.reasoning or not action.reasoning.strip():
        raise GateRejected(f"Action {action.action_id} missing reasoning")

    if action.action_type not in ("done", "ask", "navigate", "scroll"):
        if not action.cited_source_text or not action.cited_source_text.strip():
            raise GateRejected(f"Action {action.action_id} missing cited_source_text")
        if not action.cited_source_location or not action.cited_source_location.strip():
            raise GateRejected(f"Action {action.action_id} missing cited_source_location")

    if action.action_type not in ("done", "ask", "navigate", "scroll") and (not action.target or not action.target.strip()):
        raise GateRejected(f"Action {action.action_id} missing target")