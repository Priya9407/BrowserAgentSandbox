"""
decision.py

Defines the possible decisions that the Policy Engine
can make after evaluating an AgentAction.

Every browser action MUST end in exactly one decision.
"""

from enum import Enum


class PolicyDecision(str, Enum):
    """
    Final decision returned by the Policy Engine.
    """

    # Safe to execute immediately
    ALLOW = "ALLOW"

    # Dangerous action.
    # Never execute automatically.
    DENY = "DENY"

    # Requires user approval.
    ESCALATE = "ESCALATE"


def describe(decision: PolicyDecision) -> str:
    """
    Human-readable explanation.
    """

    descriptions = {
        PolicyDecision.ALLOW: "Action is considered safe and may be executed.",
        PolicyDecision.DENY: "Action violates security policy and must not be executed.",
        PolicyDecision.ESCALATE: "Action requires explicit user approval before execution.",
    }

    return descriptions[decision]
