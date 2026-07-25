from pydantic import BaseModel


class AgentAction(BaseModel):
    action_id: str
    action_type: str
    target: str
    reasoning: str
    cited_source_text: str
    cited_source_location: str
    timestamp: str
