"""
models.py

Shared Pydantic models used by the Policy Engine.
"""

from enum import Enum

from pydantic import BaseModel

from app.policy.risk_taxonomy import RiskCategory
from app.policy.decision import PolicyDecision


class Origin(str, Enum):
    """
    Where the agent's cited reasoning came from.

    This is the core of the provenance layer:
    we classify WHERE an instruction came from,
    not WHAT it says.

    user_task          — the reasoning maps back to what the
                         human originally typed. Safe.
    visible_page_content — the reasoning cites text visible
                         on the page. Needs scrutiny.
    hidden_page_content  — the reasoning cites text that is
                         hidden from the user (display:none,
                         off-screen, zero-opacity, etc.).
                         Never auto-trusted.
    """

    USER_TASK = "user_task"
    VISIBLE_PAGE_CONTENT = "visible_page_content"
    HIDDEN_PAGE_CONTENT = "hidden_page_content"


class PolicyResult(BaseModel):
    """
    Final output of the Policy Engine.
    """

    # Original browser action
    action_id: str

    # Navigation / Payment / Download ...
    risk_category: RiskCategory

    # LOW / MEDIUM / HIGH / CRITICAL
    risk_level: str

    # ALLOW / DENY / ESCALATE
    decision: PolicyDecision

    # Whether hidden content was detected on the page
    hidden_content_detected: bool

    # Where the agent's reasoning originated
    origin: Origin = Origin.USER_TASK

    # Whether the action semantically drifts from the user task
    topic_drift_detected: bool = False

    # Why this decision was made
    reason: str

    # Optional details for debugging/UI
    metadata: dict = {}
