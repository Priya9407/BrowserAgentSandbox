"""
policy_engine.py

The core security engine of Frontier.

Responsibilities
----------------
1. Run the instruction-source classifier  (WHERE did this come from?)
2. Classify browser action into a risk category
3. Determine risk level (LOW / MEDIUM / HIGH / CRITICAL)
4. Detect hidden content
5. Combine origin + risk → ALLOW / DENY / ESCALATE
6. Return PolicyResult

Decision matrix
---------------
origin=hidden_page_content                → always ESCALATE minimum, DENY if high/critical risk
origin=visible_page_content + high risk   → ESCALATE
origin=user_task                          → normal risk-based rules apply
"""

from app.schemas.action_schema import AgentAction

from app.policy.classifier import RiskClassifier
from app.policy.source_classifier import SourceClassifier
from app.policy.risk_taxonomy import RiskCategory, get_risk_level
from app.policy.decision import PolicyDecision
from app.policy.models import Origin, PolicyResult


class PolicyEngine:
    def __init__(self):
        self.classifier = RiskClassifier()
        self.source_classifier = SourceClassifier()

    def evaluate(
        self,
        action: AgentAction,
        hidden_content_detected: bool = False,
        user_task: str = "",
        visible_page_text: str = "",
        hidden_page_text: str = "",
    ) -> PolicyResult:

        # ------------------------------------
        # STEP 1
        # Classify instruction source (origin)
        # ------------------------------------

        origin = self.source_classifier.classify(
            cited_source_text=action.cited_source_text,
            user_task=user_task,
            visible_page_text=visible_page_text,
            hidden_page_text=hidden_page_text,
        )

        # ------------------------------------
        # STEP 2
        # Classify the action into a risk category
        # ------------------------------------

        category = self.classifier.classify(action)

        # ------------------------------------
        # STEP 3
        # Convert to LOW / MEDIUM / HIGH / CRITICAL
        # ------------------------------------

        risk_level = get_risk_level(category)

        # ------------------------------------
        # STEP 4
        # Decide — origin tightens the outcome
        # ------------------------------------

        decision = self._decide(category, hidden_content_detected, origin)

        # ------------------------------------
        # STEP 5
        # Build human-readable explanation
        # ------------------------------------

        reason = self._reason(category, decision, hidden_content_detected, origin)

        # ------------------------------------
        # STEP 6
        # Return result
        # ------------------------------------

        return PolicyResult(
            action_id=action.action_id,
            risk_category=category,
            risk_level=risk_level,
            decision=decision,
            hidden_content_detected=hidden_content_detected,
            origin=origin,
            reason=reason,
            metadata={
                "target": action.target,
                "action_type": action.action_type,
            },
        )

    # ------------------------------------------------------------------
    # Decision logic
    # ------------------------------------------------------------------

    def _decide(
        self,
        category: RiskCategory,
        hidden: bool,
        origin: Origin,
    ) -> PolicyDecision:

        # --------------------------------------------------
        # Instruction came from HIDDEN page text
        # Even if the page element isn't flagged by the
        # heuristic detector, the cited text itself traces
        # back to hidden content — never auto-trust.
        # --------------------------------------------------

        if origin == Origin.HIDDEN_PAGE_CONTENT:
            if category in (
                RiskCategory.CREDENTIAL,
                RiskCategory.PAYMENT,
                RiskCategory.SEND,
                RiskCategory.DELETE,
            ):
                return PolicyDecision.DENY
            return PolicyDecision.ESCALATE

        # --------------------------------------------------
        # Hidden DOM content detected on page, but NOT cited
        # The page is actively trying to hide instructions,
        # but the agent successfully ignored them. Escalate
        # for human review rather than blindly denying.
        # --------------------------------------------------

        if hidden:
            if category == RiskCategory.DELETE:
                return PolicyDecision.DENY
            return PolicyDecision.ESCALATE

        # --------------------------------------------------
        # Instruction came from VISIBLE page text
        # The page may be legitimately guiding the agent, but
        # page content is never a trusted authority for
        # high-risk actions — require human sign-off.
        # --------------------------------------------------

        if origin == Origin.VISIBLE_PAGE_CONTENT:
            if category in (
                RiskCategory.CREDENTIAL,
                RiskCategory.PAYMENT,
                RiskCategory.DOWNLOAD,
                RiskCategory.FILE_UPLOAD,
                RiskCategory.SEND,
                RiskCategory.DELETE,
            ):
                return PolicyDecision.ESCALATE
            # Low/medium risk from visible content is fine
            return PolicyDecision.ALLOW

        # --------------------------------------------------
        # Instruction came from the USER'S OWN TASK
        # Normal risk-based rules apply.
        # --------------------------------------------------

        if category == RiskCategory.NAVIGATION:
            return PolicyDecision.ALLOW

        if category == RiskCategory.FORM_FILL:
            return PolicyDecision.ALLOW

        if category in (
            RiskCategory.CREDENTIAL,
            RiskCategory.PAYMENT,
            RiskCategory.DOWNLOAD,
            RiskCategory.FILE_UPLOAD,
            RiskCategory.SEND,
        ):
            return PolicyDecision.ESCALATE

        if category == RiskCategory.DELETE:
            return PolicyDecision.DENY

        # Unknown action — escalate to be safe
        return PolicyDecision.ESCALATE

    # ------------------------------------------------------------------
    # Reason builder
    # ------------------------------------------------------------------

    def _reason(
        self,
        category: RiskCategory,
        decision: PolicyDecision,
        hidden: bool,
        origin: Origin,
    ) -> str:

        if origin == Origin.HIDDEN_PAGE_CONTENT:
            return (
                "The agent's cited reasoning traces back to hidden page content "
                "(display:none, off-screen, zero-opacity, or similar). "
                "Instructions from hidden elements are never auto-trusted."
            )

        if hidden:
            return (
                "Hidden HTML/CSS content detected on the page. "
                "The agent successfully ignored the injection, but the action is "
                "escalated for human review due to suspicious page structure."
            )

        if origin == Origin.VISIBLE_PAGE_CONTENT:
            base = (
                "The agent's reasoning originates from visible page text, "
                "not the user's original task. "
            )
            if decision == PolicyDecision.ESCALATE:
                return base + "Human approval required before a high-risk page-sourced action is executed."
            return base + "Action is low-risk and within scope."

        # origin == USER_TASK — normal explanations
        explanations = {
            RiskCategory.NAVIGATION: "Navigation action rooted in the user's task. Safe to execute.",
            RiskCategory.FORM_FILL: "Form-fill action rooted in the user's task. Safe to execute.",
            RiskCategory.CREDENTIAL: "Credential entry requires explicit user approval.",
            RiskCategory.PAYMENT: "Payment action requires explicit user approval.",
            RiskCategory.DOWNLOAD: "Download requires user approval.",
            RiskCategory.FILE_UPLOAD: "File upload requires user approval.",
            RiskCategory.SEND: "Sending data requires user approval.",
            RiskCategory.DELETE: "Delete operations are blocked by policy.",
            RiskCategory.UNKNOWN: "Unknown action type — escalating to be safe.",
        }

        return explanations.get(category, "No reason available.")
