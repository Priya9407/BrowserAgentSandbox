from app.policy.models import PolicyResult
from app.policy.risk_taxonomy import RiskCategory
from app.policy.decision import PolicyDecision


result = PolicyResult(
    action_id="1",
    risk_category=RiskCategory.PAYMENT,
    risk_level="CRITICAL",
    decision=PolicyDecision.ESCALATE,
    hidden_content_detected=False,
    reason="Payment requires confirmation.",
    metadata={"button": "#buy"},
)

print(result.model_dump())
