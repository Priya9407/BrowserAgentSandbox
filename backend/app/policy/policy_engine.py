"""
policy_engine.py

The core security engine of Frontier.

Responsibilities
----------------
1. Classify browser action
2. Determine risk level
3. Detect hidden content
4. Decide:
        ALLOW
        DENY
        ESCALATE
5. Return PolicyResult
"""

from app.schemas.action_schema import AgentAction

from app.policy.classifier import RiskClassifier
from app.policy.risk_taxonomy import (
    RiskCategory,
    get_risk_level,
)
from app.policy.decision import PolicyDecision
from app.policy.models import PolicyResult


class PolicyEngine:
    def __init__(self):

        self.classifier = RiskClassifier()

    def evaluate(
        self,
        action: AgentAction,
        hidden_content_detected: bool = False,
    ) -> PolicyResult:

        # ------------------------------------
        # STEP 1
        # Classify the action
        # ------------------------------------

        category = self.classifier.classify(action)

        # ------------------------------------
        # STEP 2
        # Convert to LOW/MEDIUM/HIGH
        # ------------------------------------

        risk_level = get_risk_level(category)

        # ------------------------------------
        # STEP 3
        # Decide
        # ------------------------------------

        decision = self._decide(
            category,
            hidden_content_detected,
        )

        # ------------------------------------
        # STEP 4
        # Build explanation
        # ------------------------------------

        reason = self._reason(
            category,
            decision,
            hidden_content_detected,
        )

        # ------------------------------------
        # STEP 5
        # Return result
        # ------------------------------------

        return PolicyResult(
            action_id=action.action_id,
            risk_category=category,
            risk_level=risk_level,
            decision=decision,
            hidden_content_detected=hidden_content_detected,
            reason=reason,
            metadata={
                "target": action.target,
                "action_type": action.action_type,
            },
        )

    # -------------------------------------------------

    def _decide(
        self,
        category: RiskCategory,
        hidden: bool,
    ) -> PolicyDecision:

        # ----------------------------------
        # Hidden prompt detected
        # Never trust it.
        # ----------------------------------

        if hidden:
            return PolicyDecision.DENY

        # ----------------------------------
        # Safe
        # ----------------------------------

        if category == RiskCategory.NAVIGATION:
            return PolicyDecision.ALLOW

        if category == RiskCategory.FORM_FILL:
            return PolicyDecision.ALLOW

        # ----------------------------------
        # Needs approval
        # ----------------------------------

        if category in [
            RiskCategory.CREDENTIAL,
            RiskCategory.PAYMENT,
            RiskCategory.DOWNLOAD,
            RiskCategory.FILE_UPLOAD,
            RiskCategory.SEND,
        ]:
            return PolicyDecision.ESCALATE

        # ----------------------------------
        # Dangerous
        # ----------------------------------

        if category == RiskCategory.DELETE:
            return PolicyDecision.DENY

        # ----------------------------------
        # Unknown action
        # ----------------------------------

        return PolicyDecision.ESCALATE

    # -------------------------------------------------

    def _reason(
        self,
        category: RiskCategory,
        decision: PolicyDecision,
        hidden: bool,
    ) -> str:

        if hidden:
            return "Hidden HTML or CSS content detected. Action blocked for security."

        explanations = {
            RiskCategory.NAVIGATION: "Navigation is considered low risk.",
            RiskCategory.FORM_FILL: "Form filling is considered safe.",
            RiskCategory.CREDENTIAL: "Credentials require explicit user approval.",
            RiskCategory.PAYMENT: "Payment requires explicit user approval.",
            RiskCategory.DOWNLOAD: "Downloads require user approval.",
            RiskCategory.FILE_UPLOAD: "Uploading files requires user approval.",
            RiskCategory.SEND: "Sending data requires user approval.",
            RiskCategory.DELETE: "Delete operations are blocked.",
            RiskCategory.UNKNOWN: "Unknown browser action.",
        }

        return explanations.get(
            category,
            "Unknown policy decision.",
        )
