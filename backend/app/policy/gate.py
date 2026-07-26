"""
Hard pre-condition: NO action reaches Playwright without
non-empty reasoning + cited_source_text. This runs before
the risk classifier / policy engine even see the action.
"""

from app.schemas.action_schema import AgentAction


class GateRejected(Exception):
    pass


def enforce_action_contract(action: AgentAction) -> None:
    if not action.reasoning or not action.reasoning.strip():
        raise GateRejected(f"Action {action.action_id} missing reasoning")

    if not action.cited_source_text or not action.cited_source_text.strip():
        raise GateRejected(f"Action {action.action_id} missing cited_source_text")

    if not action.cited_source_location or not action.cited_source_location.strip():
        raise GateRejected(f"Action {action.action_id} missing cited_source_location")

    if action.action_type != "done" and (not action.target or not action.target.strip()):
        raise GateRejected(f"Action {action.action_id} missing target")