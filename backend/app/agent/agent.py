from datetime import datetime

from app.schemas.action_schema import AgentAction
from app.agent.llm import get_next_action


class BrowserAgent:
    def __init__(self):
        self.user_task = None

    def set_task(self, task):
        self.user_task = task

    def think(self, dom):

        result = get_next_action(self.user_task, dom)

        return AgentAction(
            action_id="1",
            action_type=result["action_type"],
            target=result["target"],
            reasoning=result["reasoning"],
            cited_source_text=result["cited_source_text"],
            cited_source_location=result["cited_source_location"],
            timestamp=datetime.now().isoformat(),
        )
