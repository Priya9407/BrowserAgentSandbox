from datetime import datetime

from app.schemas.action_schema import AgentAction
from app.schemas.plan_schema import TaskPlan
from app.agent.llm import get_next_action


class BrowserAgent:
    def __init__(self):
        self.user_task = None
        self.history = []          # list of past AgentAction (as dicts)
        self.step_count = 0
        self.max_steps = 5
        self.plan: TaskPlan | None = None
        self.current_step_index = 0

    def set_task(self, task):
        self.user_task = task
        self.history = []
        self.step_count = 0
        self.plan = None
        self.current_step_index = 0

    def set_plan(self, plan: TaskPlan):
        """Attach a pre-generated plan. Called once, right after set_task()."""
        self.plan = plan
        self.current_step_index = 0
        if plan and plan.steps:
            # give the loop enough budget to actually reach the last step,
            # plus headroom for a step that needs more than one think() call
            self.max_steps = max(self.max_steps, len(plan.steps) * 2)

    def _build_task_context(self) -> str:
        """
        Builds the string handed to get_next_action() as `user_task`.
        If no plan is set, behaves exactly as before (just the raw task) —
        so this is fully backward compatible with the old single-action flow.
        """
        if not self.plan or not self.plan.steps:
            return self.user_task

        plan_lines = "\n".join(
            f"  {s.step_number}. {s.goal}" + (" (CURRENT STEP)" if i == self.current_step_index else "")
            for i, s in enumerate(self.plan.steps)
        )

        return (
            f"{self.user_task}\n\n"
            f"You are following this pre-made plan:\n{plan_lines}\n\n"
            f"Focus on completing the CURRENT STEP above. "
            f"If it's already satisfied based on the steps taken so far, move on to the next one."
        )

    def is_done(self):
        return self.step_count >= self.max_steps

    def think(self, dom):
        self.step_count += 1

        result = get_next_action(
            user_task=self._build_task_context(),
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
        # NOTE: step pointer no longer advances here — only after a
        # step's action has actually been ALLOWED/approved and executed.
        return action

    def is_last_step(self) -> bool:
        if not self.plan or not self.plan.steps:
            return True
        return self.current_step_index >= len(self.plan.steps) - 1

    def advance_step(self) -> bool:
        """Move to the next planned step. Returns False if already on the last step."""
        if self.plan and self.plan.steps and not self.is_last_step():
            self.current_step_index += 1
            return True
        return False