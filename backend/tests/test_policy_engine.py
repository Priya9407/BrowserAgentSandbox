from app.schemas.action_schema import AgentAction

from app.policy.policy_engine import PolicyEngine


engine = PolicyEngine()


action = AgentAction(
    action_id="1",
    action_type="click",
    target="#buy",
    reasoning="User wants to buy laptop",
    cited_source_text="Buy Laptop",
    cited_source_location="#buy",
    timestamp="now",
)

result = engine.evaluate(action)

print(result.model_dump())
