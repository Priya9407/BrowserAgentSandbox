"""
plan_schema.py — Task List Contract
=====================================
This is the locked schema between the planner (planner.py / generate_plan())
and the executor (agent.py / playwright_agent.py).

DO NOT change field names without updating both sides.

──────────────────────────────────────────────────────────────────
CONTRACT: TaskPlan
──────────────────────────────────────────────────────────────────
A TaskPlan is the planner's ENTIRE output for one user goal.
It is produced ONCE, before the execution loop starts.
The executor consumes it step-by-step; it is never regenerated mid-run.

{
  "original_task": str,       # The raw free-text goal the user typed.
                              # Carried through for provenance — the policy
                              # layer uses this as the trust anchor.

  "steps": [PlannedStep]      # Ordered list, executed top-to-bottom.
                              # Min 1 step. Typically 2–6.
}

──────────────────────────────────────────────────────────────────
CONTRACT: PlannedStep
──────────────────────────────────────────────────────────────────
One logical milestone in the plan. NOT a grounded browser action.
Grounding into CSS selectors / concrete actions happens later,
per-iteration, inside get_next_action() in llm.py.

{
  "step_number": int,         # 1-based index. Must be sequential
                              # (1, 2, 3 …). Used for display only —
                              # execution order is list order, not this field.

  "goal": str,                # Plain-language description of what this
                              # step should accomplish.
                              # Good:  "Search for Sony WH-1000XM5 on Google"
                              # Bad:   "Click #search-btn"  ← too low-level
                              # Bad:   "Do stuff"           ← too vague

  "action_type_hint": str|null  # Optional coarse hint to guide the executor.
                                # One of: click | type | navigate | scroll |
                                #         submit | done | null
                                # The executor MAY ignore this — it is a hint,
                                # not a directive. Never put a CSS selector here.
}

──────────────────────────────────────────────────────────────────
EXAMPLE — "Search for Sony headphones price"
──────────────────────────────────────────────────────────────────
{
  "original_task": "Search for the Sony WH-1000XM5 price and report it",
  "steps": [
    {
      "step_number": 1,
      "goal": "Type 'Sony WH-1000XM5 price' into the Google search box and submit",
      "action_type_hint": "type"
    },
    {
      "step_number": 2,
      "goal": "Read the price shown in the search results and report it",
      "action_type_hint": "done"
    }
  ]
}

──────────────────────────────────────────────────────────────────
EXECUTION CONTRACT (agent.py side)
──────────────────────────────────────────────────────────────────
• agent.set_plan(plan)        — called once after generate_plan()
• agent.think(dom)            — called per browser iteration; internally
                                injects the CURRENT STEP goal into the
                                LLM prompt via _build_task_context()
• agent.advance_step()        — called after a step's action is ALLOW'd
                                or approved; moves current_step_index forward
• agent.is_last_step()        — True when current_step_index == len(steps)-1
• action_type == "done"       — signals the current step is satisfied;
                                executor calls advance_step() and continues
                                (or halts if is_last_step())

──────────────────────────────────────────────────────────────────
POLICY CONTRACT
──────────────────────────────────────────────────────────────────
• original_task is the TRUST ANCHOR for the source classifier.
  It must reach policy.evaluate(user_task=...) unchanged.
• PlannedStep.goal must NOT be passed as user_task — it is a sub-goal,
  not the original human intent. Passing a step goal as user_task would
  cause the source classifier to mis-classify page-sourced instructions
  as user-task-sourced.
"""

from pydantic import BaseModel


class PlannedStep(BaseModel):
    step_number: int
    goal: str
    action_type_hint: str | None = None


class TaskPlan(BaseModel):
    original_task: str
    steps: list[PlannedStep]
