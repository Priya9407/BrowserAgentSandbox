from app.policy.risk_taxonomy import (
    RiskCategory,
    get_risk_level,
)


print(RiskCategory.NAVIGATION)
print(get_risk_level(RiskCategory.NAVIGATION))

print(RiskCategory.PAYMENT)
print(get_risk_level(RiskCategory.PAYMENT))
