import pytest
from app.schemas.action_schema import AgentAction
from app.policy.gate import enforce_action_contract, GateRejected

def make_action(**overrides):
    base = dict(
        action_id="1", action_type="click", target="#buy",
        reasoning="user wants to buy", cited_source_text="Buy Laptop",
        cited_source_location="#buy", timestamp="now",
    )
    base.update(overrides)
    return AgentAction(**base)

def test_valid_action_passes():
    enforce_action_contract(make_action())  # should not raise

def test_missing_reasoning_rejected():
    with pytest.raises(GateRejected):
        enforce_action_contract(make_action(reasoning=""))

def test_missing_citation_rejected():
    with pytest.raises(GateRejected):
        enforce_action_contract(make_action(cited_source_text="   "))

def test_done_action_skips_target_check():
    a = make_action(action_type="done", target="")
    enforce_action_contract(a)  # should not raise