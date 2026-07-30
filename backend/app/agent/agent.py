"""
agent.py — BrowserAgent

Manages per-session state: plan, step pointer, action history, and budget.

Recovery loop
  • record_step_failure() / record_step_success() — track per-step outcome
    so the recovery loop in playwright_agent.py can decide when to retry
    vs. re-plan vs. give up.
  • step_failures  dict[int, int] — counts consecutive failures per step index
  • MAX_STEP_RETRIES = 1 — after 1 failed retry the recovery loop requests
    a re-plan; after re-plan also fails it emits an honest "couldn't complete"
    message and moves on.
"""

from datetime import datetime

from app.schemas.action_schema import AgentAction, SemanticTarget
from app.schemas.plan_schema import TaskPlan
from app.agent.llm import get_next_action

MAX_STEP_RETRIES = 1   # one retry before escalating to a re-plan request


class BrowserAgent:
    def __init__(self):
        self.user_task = None
        self.history: list[dict] = []
        self.step_count = 0
        self.max_steps = 30
        self.plan: TaskPlan | None = None
        self.current_step_index = 0
        self.step_failures: dict[int, int] = {}   # step_index → consecutive failure count

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def set_task(self, task: str):
        self.user_task = task
        self.history = []
        self.step_count = 0
        self.plan = None
        self.current_step_index = 0
        self.step_failures = {}

    def set_plan(self, plan: TaskPlan):
        """Attach a pre-generated plan. Called once, right after set_task()."""
        self.plan = plan
        self.current_step_index = 0
        self.step_failures = {}
        if plan and plan.steps:
            self.max_steps = max(self.max_steps, len(plan.steps) * 3)

    # ------------------------------------------------------------------
    # Replanning 
    # ------------------------------------------------------------------

    def replace_remaining_plan(self, new_plan: TaskPlan):
        """
        Swap in a revised plan for the remaining steps.
        Resets the step pointer to 0 on the new plan but preserves history.
        """
        self.plan = new_plan
        self.current_step_index = 0
        self.step_failures = {}
        if new_plan and new_plan.steps:
            # Give budget headroom for the revised steps
            self.max_steps = max(self.max_steps, self.step_count + len(new_plan.steps) * 3)

    # ------------------------------------------------------------------
    # Failure tracking 
    # ------------------------------------------------------------------

    def record_step_failure(self) -> int:
        """Increment the failure counter for the current step. Returns new count."""
        idx = self.current_step_index
        self.step_failures[idx] = self.step_failures.get(idx, 0) + 1
        return self.step_failures[idx]

    def record_step_success(self):
        """Reset failure counter for the current step on success."""
        self.step_failures[self.current_step_index] = 0

    def current_step_failure_count(self) -> int:
        return self.step_failures.get(self.current_step_index, 0)

    # ------------------------------------------------------------------
    # Step context
    # ------------------------------------------------------------------

    def _build_task_context(self) -> str:
        if not self.plan or not self.plan.steps:
            return self.user_task

        plan_lines = "\n".join(
            f"  {s.step_number}. {s.goal}"
            + (" ← CURRENT STEP" if i == self.current_step_index else "")
            for i, s in enumerate(self.plan.steps)
        )

        return (
            f"{self.user_task}\n\n"
            f"You are following this pre-made plan:\n{plan_lines}\n\n"
            f"Focus on completing the CURRENT STEP above. "
            f"If it is already satisfied based on the steps taken so far, "
            f"return action_type = 'done'."
        )

    # ------------------------------------------------------------------
    # Core loop interface
    # ------------------------------------------------------------------

    def is_done(self) -> bool:
        return self.step_count >= self.max_steps

    def think(self, dom: str) -> AgentAction:
        self.step_count += 1

        result = get_next_action(
            user_task=self._build_task_context(),
            dom=dom,
            history=self.history,
        )

        import uuid

        # Build SemanticTarget from the LLM result
        raw_sem = result.get("semantic_target", {})
        if isinstance(raw_sem, dict):
            sem = SemanticTarget(
                role=raw_sem.get("role", "generic"),
                label=raw_sem.get("label", ""),
            )
        else:
            sem = SemanticTarget()

        action = AgentAction(
            action_id=str(uuid.uuid4()),
            action_type=result.get("action_type", "done"),
            target=result.get("target", ""),
            semantic_target=sem,
            value=result.get("value"),
            reasoning=result.get("reasoning", ""),
            cited_source_text=result.get("cited_source_text", ""),
            cited_source_location=result.get("cited_source_location", ""),
            timestamp=datetime.now().isoformat(),
            options=result.get("options"),  # optional list of user-selectable choices
        )

        self.history.append(action.model_dump())
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

    @property
    def current_step_goal(self) -> str:
        if self.plan and self.plan.steps:
            return self.plan.steps[self.current_step_index].goal
        return self.user_task
