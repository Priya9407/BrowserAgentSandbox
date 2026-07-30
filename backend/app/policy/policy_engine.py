"""
policy_engine.py

The core security engine of Frontier.

Tripwire mode (Milestone 1 B)
------------------------------
The full provenance / origin check is expensive and adds latency.
For a real demo with ordinary tasks (search, navigate, read prices)
the vast majority of actions are NAVIGATION or FORM_FILL — running
the full source classifier on every one clutters the UI and adds
latency without adding safety value.

Tripwire rule:
  - NAVIGATION / FORM_FILL / UNKNOWN  → lightweight pass
    (risk-level only, skip source classifier + topic drift,
    ALLOW immediately unless hidden content is on the page)
  - CREDENTIAL / PAYMENT / SEND / DELETE / DOWNLOAD / FILE_UPLOAD
    → full provenance check (source classifier + topic drift + origin-aware decision)

Normal tasks sail through cleanly. The full machinery only fires
when it actually matters.

Decision matrix (sensitive actions only)
-----------------------------------------
topic_drift                               → DENY if critical, else ESCALATE
origin=hidden_page_content                → DENY if critical, else ESCALATE
hidden_content_detected (page heuristic)  → DENY if DELETE, else ESCALATE
origin=visible_page_content + high risk   → ESCALATE
origin=user_task                          → normal risk rules
"""

from app.schemas.action_schema import AgentAction

from app.policy.classifier import RiskClassifier
from app.policy.source_classifier import SourceClassifier
from app.policy.topic_drift import TopicDriftDetector
from app.policy.risk_taxonomy import RiskCategory, get_risk_level
from app.policy.decision import PolicyDecision
from app.policy.models import Origin, PolicyResult


# Only these categories get the full provenance treatment.
_SENSITIVE = {
    RiskCategory.CREDENTIAL,
    RiskCategory.PAYMENT,
    RiskCategory.SEND,
    RiskCategory.DELETE,
    RiskCategory.DOWNLOAD,
    RiskCategory.FILE_UPLOAD,
}


class PolicyEngine:
    def __init__(self):
        self.classifier = RiskClassifier()
        self.source_classifier = SourceClassifier()
        self.topic_drift_detector = TopicDriftDetector()

    def evaluate(
        self,
        action: AgentAction,
        hidden_content_detected: bool = False,
        user_task: str = "",
        visible_page_text: str = "",
        hidden_page_text: str = "",
    ) -> PolicyResult:

        # ------------------------------------
        # STEP 1 — Risk category + level (always runs, cheap)
        # ------------------------------------
        category = self.classifier.classify(action)
        risk_level = get_risk_level(category)

        # ------------------------------------
        # STEP 2 — Tripwire gate
        # Non-sensitive + no hidden content on page → ALLOW immediately.
        # Skip source classifier and topic drift entirely.
        # ------------------------------------
        if category not in _SENSITIVE and not hidden_content_detected:
            return PolicyResult(
                action_id=action.action_id,
                risk_category=category,
                risk_level=risk_level,
                decision=PolicyDecision.ALLOW,
                hidden_content_detected=False,
                topic_drift_detected=False,
                origin=Origin.USER_TASK,
                reason="Low/medium-risk action — lightweight pass.",
                metadata={"target": action.target, "action_type": action.action_type},
            )

        # ------------------------------------
        # STEP 3 — Full provenance check
        # Reaches here only for sensitive action types
        # OR when hidden content was detected on the page.
        # ------------------------------------
        origin = self.source_classifier.classify(
            cited_source_text=action.cited_source_text,
            user_task=user_task,
            visible_page_text=visible_page_text,
            hidden_page_text=hidden_page_text,
        )

        topic_drift_detected = self.topic_drift_detector.detect(
            user_task=user_task,
            reasoning=action.reasoning,
            cited_source_text=action.cited_source_text,
        )

        # ------------------------------------
        # STEP 4 — Decision
        # ------------------------------------
        decision = self._decide(category, hidden_content_detected, origin, topic_drift_detected)

        # ------------------------------------
        # STEP 5 — Human-readable reason
        # ------------------------------------
        reason = self._reason(category, decision, hidden_content_detected, origin, topic_drift_detected)

        return PolicyResult(
            action_id=action.action_id,
            risk_category=category,
            risk_level=risk_level,
            decision=decision,
            hidden_content_detected=hidden_content_detected,
            topic_drift_detected=topic_drift_detected,
            origin=origin,
            reason=reason,
            metadata={"target": action.target, "action_type": action.action_type},
        )

    # ------------------------------------------------------------------
    # Decision logic (sensitive actions only)
    # ------------------------------------------------------------------

    def _decide(
        self,
        category: RiskCategory,
        hidden: bool,
        origin: Origin,
        topic_drift: bool = False,
    ) -> PolicyDecision:

        _critical = {RiskCategory.CREDENTIAL, RiskCategory.PAYMENT,
                     RiskCategory.SEND, RiskCategory.DELETE}

        # Semantic topic drift — reasoning unrelated to user's task.
        if topic_drift:
            return PolicyDecision.DENY if category in _critical else PolicyDecision.ESCALATE

        # UNVERIFIED provenance: the LLM fabricated or hallucinated the citation.
        # Treat this as at least as dangerous as hidden content — the model
        # cannot be trusted to justify its own actions.
        if origin == Origin.UNVERIFIED:
            _hard_deny = {RiskCategory.CREDENTIAL, RiskCategory.PAYMENT,
                          RiskCategory.DELETE, RiskCategory.SEND}
            return PolicyDecision.DENY if category in _hard_deny else PolicyDecision.ESCALATE

        # Cited text traces back to hidden DOM content.
        if origin == Origin.HIDDEN_PAGE_CONTENT:
            _hard_deny = {RiskCategory.CREDENTIAL, RiskCategory.PAYMENT, RiskCategory.DELETE}
            return PolicyDecision.DENY if category in _hard_deny else PolicyDecision.ESCALATE

        # Page has hidden elements (heuristic detector), agent didn't cite them.
        if hidden:
            return PolicyDecision.DENY if category == RiskCategory.DELETE else PolicyDecision.ESCALATE

        # Reasoning comes from visible page text (not user's own words).
        if origin == Origin.VISIBLE_PAGE_CONTENT:
            if category in (RiskCategory.CREDENTIAL, RiskCategory.PAYMENT,
                            RiskCategory.DOWNLOAD, RiskCategory.FILE_UPLOAD,
                            RiskCategory.SEND, RiskCategory.DELETE):
                return PolicyDecision.ESCALATE
            return PolicyDecision.ALLOW

        # Origin is USER_TASK — normal risk rules apply.
        if category in (RiskCategory.CREDENTIAL, RiskCategory.PAYMENT,
                        RiskCategory.DOWNLOAD, RiskCategory.FILE_UPLOAD,
                        RiskCategory.SEND):
            return PolicyDecision.ESCALATE

        if category == RiskCategory.DELETE:
            return PolicyDecision.DENY

        return PolicyDecision.ESCALATE  # unknown sensitive type, be safe

    # ------------------------------------------------------------------
    # Reason builder
    # ------------------------------------------------------------------

    def _reason(
        self,
        category: RiskCategory,
        decision: PolicyDecision,
        hidden: bool,
        origin: Origin,
        topic_drift: bool = False,
    ) -> str:

        if topic_drift:
            return (
                "Semantic topic drift detected: the agent's reasoning is unrelated "
                "to the user's original task. Possible prompt injection via visible "
                "page content."
            )

        if origin == Origin.UNVERIFIED:
            base = (
                "The agent's cited reasoning cannot be verified against any known "
                "source (user task, visible page text, or hidden page text). "
                "The LLM may have fabricated this citation. "
            )
            if decision == PolicyDecision.DENY:
                return base + "Action denied — unverifiable citation with high-risk category."
            return base + "Human review required before this unverifiable action executes."

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
            base = "The agent's reasoning originates from visible page text, not the user's original task. "
            if decision == PolicyDecision.ESCALATE:
                return base + "Human approval required before this high-risk page-sourced action executes."
            return base + "Action is within acceptable risk for page-sourced instructions."

        # USER_TASK origin
        return {
            RiskCategory.CREDENTIAL:  "Credential entry requires explicit user approval.",
            RiskCategory.PAYMENT:     "Payment action requires explicit user approval.",
            RiskCategory.DOWNLOAD:    "Download requires user approval.",
            RiskCategory.FILE_UPLOAD: "File upload requires user approval.",
            RiskCategory.SEND:        "Sending data requires user approval.",
            RiskCategory.DELETE:      "Delete operations are blocked by policy.",
        }.get(category, "Sensitive action requires user approval.")
