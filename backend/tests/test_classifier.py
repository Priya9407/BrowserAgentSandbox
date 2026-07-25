from app.schemas.action_schema import AgentAction
from app.policy.classifier import RiskClassifier


classifier = RiskClassifier()


actions = [
    AgentAction(
        action_id="1",
        action_type="click",
        target="#buy",
        reasoning="User wants to buy laptop",
        cited_source_text="Buy Laptop",
        cited_source_location="#buy",
        timestamp="now",
    ),
    AgentAction(
        action_id="2",
        action_type="click",
        target="#login",
        reasoning="Login to account",
        cited_source_text="Login",
        cited_source_location="#login",
        timestamp="now",
    ),
    AgentAction(
        action_id="3",
        action_type="click",
        target="#download",
        reasoning="Download PDF",
        cited_source_text="Download",
        cited_source_location="#download",
        timestamp="now",
    ),
]

for action in actions:
    print(action.target)

    print(classifier.classify(action))

    print("-" * 40)
