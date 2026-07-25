from app.policy.decision import (
    PolicyDecision,
    describe,
)

for decision in PolicyDecision:
    print(decision)
    print(describe(decision))
    print("-" * 40)
