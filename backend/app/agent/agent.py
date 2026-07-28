from datetime import datetime

from app.schemas.action_schema import AgentAction
from app.agent.llm import get_next_action


class BrowserAgent:
    def __init__(self):
        self.user_task = None
        self.history = []          # list of past AgentAction (as dicts)
        self.step_count = 0
        self.max_steps = 5

    def set_task(self, task):
        self.user_task = task
        self.history = []
        self.step_count = 0

    def is_done(self):
        return self.step_count >= self.max_steps

    def think(self, dom):
        self.step_count += 1

        result = get_next_action(
            user_task=self.user_task,
            dom=dom,
            history=self.history,
        )

        import uuid
        action = AgentAction(
            action_id=str(uuid.uuid4()),
            action_type=result["action_type"],
            target=result["target"],
            reasoning=result["reasoning"],
            cited_source_text=result["cited_source_text"],
            cited_source_location=result["cited_source_location"],
            timestamp=datetime.now().isoformat(),
        )

        self.history.append(action.model_dump())
        return action