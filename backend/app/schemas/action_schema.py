from pydantic import BaseModel


class AgentAction(BaseModel):
    action_id: str
    action_type: str
    target: str
    value: str | None = None
    reasoning: str
    cited_source_text: str
    cited_source_location: str
    timestamp: str
