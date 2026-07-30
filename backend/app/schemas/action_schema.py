from pydantic import BaseModel


class SemanticTarget(BaseModel):
    """Role + visible label for semantic element resolution"""
    role: str = "generic"        # ARIA role: button, link, textbox, combobox, …
    label: str = ""              # Visible text, placeholder, or aria-label


class AgentAction(BaseModel):
    action_id: str
    action_type: str
    target: str | None = ""                         # CSS selector (best-effort)
    semantic_target: SemanticTarget = SemanticTarget()  # Role+text fallback
    value: str | None = None
    reasoning: str
    cited_source_text: str | None = ""
    cited_source_location: str | None = ""
    timestamp: str
    options: list[str] | None = None   # Present choices for the user to pick from (action_type="ask" only)
