# Task List Contract — Frontier Browser Agent Sandbox

**Status: LOCKED (Day 28, 28 Jul 2025)**
Do not change field names or execution semantics without updating both the planner and executor.

---

## Why this exists

The planner (`planner.py`) and the executor (`agent.py` + `playwright_agent.py`) are built by different people and run at different times. This document is the explicit contract between them — the same role that `action_schema.py` plays for single actions.

---

## The two types in the contract

### `TaskPlan`

The planner's complete output for one user goal. Produced **once**, before execution starts. Never regenerated mid-run.

| Field | Type | Description |
|---|---|---|
| `original_task` | `str` | The raw free-text goal the user typed. **This is the trust anchor** — passed unchanged to `policy.evaluate(user_task=...)`. Do not substitute a step goal here. |
| `steps` | `list[PlannedStep]` | Ordered list of steps, executed top-to-bottom. Min 1, typically 2–6. |

---

### `PlannedStep`

One logical milestone. **Not** a grounded browser action — grounding into CSS selectors happens inside `get_next_action()` per iteration.

| Field | Type | Required | Description |
|---|---|---|---|
| `step_number` | `int` | Yes | 1-based, sequential (1, 2, 3 …). Used for display only — execution order is list order. |
| `goal` | `str` | Yes | Plain-language description of what this step should accomplish. See rules below. |
| `action_type_hint` | `str \| null` | No | Coarse hint for the executor. One of: `click`, `type`, `navigate`, `scroll`, `submit`, `done`, or `null`. A hint only — the executor may ignore it. Never put a CSS selector here. |

**`goal` field rules:**
- ✅ `"Type 'Sony WH-1000XM5' into the Google search box and submit"`
- ✅ `"Read the price shown in the search results and report it"`
- ❌ `"Click #search-btn"` — too low-level, selector doesn't belong here
- ❌ `"Do the search thing"` — too vague to be actionable
- ❌ `"Navigate to https://..."` — put URLs in the executor start URL, not step goals

---

## Wire diagram

```
User types goal
      │
      ▼
generate_plan(user_task)          planner.py
      │
      │  returns TaskPlan
      ▼
agent.set_plan(plan)              agent.py
      │
      │  loop per browser iteration:
      ▼
agent.think(dom)
  └─ _build_task_context()
       injects: original_task + plan steps + CURRENT STEP marker
       into the LLM prompt
      │
      │  LLM returns AgentAction (grounded: selector, action_type, reasoning)
      ▼
enforce_action_contract(action)   gate.py     ← hard pre-condition
      │
      ▼
policy.evaluate(                  policy_engine.py
  action,
  user_task = plan.original_task  ← ALWAYS the original task, never a step goal
)
      │
      ▼
ALLOW → _execute(page, action)
         agent.advance_step()
ESCALATE → human approval → same
DENY → stop
      │
      ▼
action_type == "done" for current step?
  → agent.advance_step() → continue loop
  → agent.is_last_step() == True → break
```

---

## Execution semantics (agent.py)

| Method | When called | Effect |
|---|---|---|
| `set_plan(plan)` | Once, after `generate_plan()` | Stores plan, sets `current_step_index = 0`, adjusts `max_steps` |
| `think(dom)` | Every browser iteration | Calls LLM with current step injected into prompt |
| `advance_step()` | After ALLOW/approved action, or on `done` | Increments `current_step_index`; returns `False` if already on last step |
| `is_last_step()` | Before advancing | `True` when `current_step_index >= len(steps) - 1` |

---

## Policy contract (critical)

`TaskPlan.original_task` **must** reach `policy.evaluate(user_task=...)` unchanged.

The source classifier (`source_classifier.py`) uses `user_task` as the trust anchor: it checks whether the agent's cited reasoning traces back to **what the human originally asked for**. If a step goal is passed instead, the classifier will incorrectly treat page-sourced instructions as user-task-sourced — defeating the entire provenance layer.

```python
# CORRECT
result = policy.evaluate(action, user_task=browser_agent.user_task)
#                                          ^^^^^^^^^^^^^^^^^^^^^^
#                                          = original_task from TaskPlan

# WRONG — never do this
result = policy.evaluate(action, user_task=current_step.goal)
```

---

## Full example

**User input:** `"Search for the Sony WH-1000XM5 price and report it"`

**`generate_plan()` output:**
```json
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
```

**Executor behaviour:**
1. Step 1 active → LLM prompted to type into search box → `AgentAction(action_type="type", target="input[name=q]", ...)` → ALLOW → execute → advance
2. Step 2 active → LLM reads results, returns `action_type="done"` → `is_last_step()` → break
3. Chat panel shows: `✓ Task complete`

---

## The 4 real demo tasks (Day 28 D)

| Label | Goal | Start URL |
|---|---|---|
| Product price | Search for the Sony WH-1000XM5 headphones and tell me the current price | `google.com/search?q=Sony+WH-1000XM5+price` |
| Check a flight | Find the cheapest one-way flight from Delhi to Goa next week and report the price and airline | Google Flights link |
| Restaurant hours | Look up the opening hours of Domino's Pizza in Bangalore and report them | `google.com/search?q=Dominos+Pizza+Bangalore+opening+hours` |
| Buy laptop (demo) | Find the cheapest laptop on this page and add it to the cart | Local `benign_checkout.html` |

These are the live demo scenarios. Run them in this order for the pitch — product price first (simplest, always works), flight second (most impressive), restaurant third (shows breadth), laptop last (shows the provenance layer if a poisoned page is swapped in).
