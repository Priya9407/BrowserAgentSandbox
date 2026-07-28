from pydantic import BaseModel


class PlannedStep(BaseModel):
    step_number: int
    goal: str          # what this step should accomplish, in plain language
    action_type_hint: str | None = None  # optional guess: "click", "type", "navigate", etc.


class TaskPlan(BaseModel):
    original_task: str
    steps: list[PlannedStep]