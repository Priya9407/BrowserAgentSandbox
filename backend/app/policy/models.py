"""
models.py

Shared Pydantic models used by the Policy Engine.
"""

from pydantic import BaseModel

from app.policy.risk_taxonomy import RiskCategory
from app.policy.decision import PolicyDecision


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

    # Whether hidden content was detected
    hidden_content_detected: bool

    # Why this decision was made
    reason: str

    # Optional details for debugging/UI
    metadata: dict = {}
