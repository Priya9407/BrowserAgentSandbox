"""
llm.py — LLM action grounding

get_next_action() asks the LLM for the next browser action.

Semantic targeting 
-----------------------------------
The LLM now returns TWO ways to address the target element:

  1. `target`         — a CSS selector (best-effort; may be wrong on messy sites)
  2. `semantic_target` — a JSON object:
       { "role": "button|link|textbox|…", "label": "visible text or aria-label" }

The executor (playwright_agent.py) tries the semantic locator first
(get_by_role + get_by_text), then falls back to the CSS selector, then
optionally to a vision pass.  That layered resolution is what makes the
agent survive pages where IDs and class names are ugly or missing.

Vision fallback 
--------------------------------
ask_vision_for_element(page, description) takes a screenshot and calls
the LLM with the image + a plain description ("the search box"), returning
a best-guess CSS selector from the visual layout.  This is the last resort
when both semantic and CSS targeting fail.
"""

import os
import json
import base64

from dotenv import load_dotenv
from openai import OpenAI

from app.schemas.plan_schema import TaskPlan, PlannedStep

load_dotenv()

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.getenv("NVIDIA_API_KEY"),
)

# ---------------------------------------------------------------------------
# Action grounding
# ---------------------------------------------------------------------------

def get_next_action(user_task: str, dom: str, history: list | None = None):
    """
    Given the current DOM and task context, return the next browser action.

    Returns a dict with keys:
        action_type        str
        target             str   — CSS selector (may be empty/wrong)
        semantic_target    dict  — { role, label } for semantic resolution
        value              str | None
        reasoning          str
        cited_source_text  str
        cited_source_location str
    """
    history = history or []

    history_block = "\n".join(
        f"Step {i+1}: {h['action_type']} on {h['target']} — {h['reasoning']}"
        for i, h in enumerate(history)
    ) or "None yet — this is the first step."

    prompt = f"""
You are a secure browser automation agent completing a MULTI-STEP task.

USER TASK:
{user_task}

STEPS TAKEN SO FAR:
{history_block}

HTML:
{dom}

IMPORTANT RULES:

- Return exactly ONE next action.
- If the CURRENT STEP (or the whole task, if no plan was given) is already
  satisfied based on the HTML, return action_type = "done".
- `target` MUST be a valid CSS selector that exists in the HTML.
- `semantic_target` MUST describe the element in plain terms so Playwright
  can find it by role and visible text if the CSS selector fails.
  Provide `role` (one of: button, link, textbox, combobox, checkbox,
  radio, listbox, menuitem, heading, img, searchbox, or "generic") and
  `label` (the element's visible text, placeholder, or aria-label).
- `value` is required when action_type is "fill" or "type"; omit otherwise.
- reasoning MUST explain why this specific action moves the task forward.
- cited_source_text MUST be the exact visible text that justified this action.
- cited_source_location MUST be a CSS selector pointing to that text's element.

Return a JSON object with EXACTLY these keys:
{{
  "action_type": "click|fill|type|navigate|scroll|done",
  "target": "<CSS selector>",
  "semantic_target": {{"role": "<role>", "label": "<visible text or aria-label>"}},
  "value": "<string or null>",
  "reasoning": "...",
  "cited_source_text": "...",
  "cited_source_location": "..."
}}
"""

    response = client.chat.completions.create(
        model="meta/llama-3.1-70b-instruct",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        response_format={"type": "json_object"},
    )

    try:
        result = json.loads(response.choices[0].message.content)
        # Normalise legacy "selector" key
        if "selector" in result and "target" not in result:
            result["target"] = result["selector"]
        # Ensure semantic_target is always present
        if "semantic_target" not in result or not isinstance(result["semantic_target"], dict):
            result["semantic_target"] = {"role": "generic", "label": ""}
    except Exception as e:
        print(f"Failed to parse JSON from LLM: {e}")
        result = {
            "action_type": "done",
            "target": "",
            "semantic_target": {"role": "generic", "label": ""},
            "value": None,
            "reasoning": "LLM parse error",
            "cited_source_text": "",
            "cited_source_location": "",
        }

    print("\n========== NVIDIA LLAMA ==========")
    print(result)
    print("============================\n")

    return result


# ---------------------------------------------------------------------------
# Vision fallback — screenshot → element location
# ---------------------------------------------------------------------------

def ask_vision_for_element(page, description: str) -> str | None:
    """
    Takes a full-page screenshot, sends it to the LLM with a description
    of the element to find (e.g. "the search box"), and returns a CSS
    selector string, or None if the model can't find it.

    Falls back gracefully: if the API doesn't support vision or the model
    can't identify the element, returns None so the caller can give up
    cleanly.
    """
    try:
        screenshot_bytes = page.screenshot(type="png", full_page=False)
        b64 = base64.b64encode(screenshot_bytes).decode()
        data_url = f"data:image/png;base64,{b64}"

        vision_prompt = (
            f"This is a screenshot of a web page. "
            f"Find '{description}' and return ONLY a valid CSS selector "
            f"that would uniquely target it. "
            f"If you cannot confidently identify it, return the JSON: "
            f'{{\"selector\": null}}. '
            f"Return ONLY a JSON object with key 'selector'."
        )

        response = client.chat.completions.create(
            model="meta/llama-3.1-70b-instruct",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": vision_prompt},
                    ],
                }
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )

        result = json.loads(response.choices[0].message.content)
        selector = result.get("selector")
        if selector and isinstance(selector, str):
            print(f"[Vision fallback] found selector: {selector}")
            return selector
        return None

    except Exception as e:
        print(f"[Vision fallback] failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Re-planning with failure context (used by recovery loop)
# ---------------------------------------------------------------------------

def replan_after_failure(
    original_task: str,
    completed_steps: list[dict],
    failed_step: dict,
    failure_reason: str,
    dom: str | None = None,
) -> TaskPlan:
    """
    Ask the LLM for a revised plan when a step has failed, giving it full
    context: what was completed, what failed, and why.  Returns a TaskPlan
    starting from the next un-completed step.
    """
    completed_block = (
        "\n".join(
            f"  {i+1}. (DONE) {s['goal']}" for i, s in enumerate(completed_steps)
        )
        or "  None — this was the first step."
    )

    dom_block = (
        f"\nCURRENT PAGE HTML (abbreviated):\n{dom[:3000]}"
        if dom
        else ""
    )

    prompt = f"""
You are a planning assistant for a secure browser automation agent.

ORIGINAL TASK:
{original_task}

STEPS ALREADY COMPLETED:
{completed_block}

FAILED STEP:
  Goal: {failed_step.get('goal', '?')}
  Reason for failure: {failure_reason}
{dom_block}

The failed step could not be completed. Provide a REVISED plan for the
remaining work. Start from where we left off — do not repeat completed steps.
Keep the list short (typically 1-4 steps).

Return a JSON object with EXACTLY this shape:
{{
  "steps": [
    {{"step_number": 1, "goal": "...", "action_type_hint": "click|type|navigate|scroll|submit|done"}},
    ...
  ]
}}
"""

    try:
        response = client.chat.completions.create(
            model="meta/llama-3.1-70b-instruct",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        steps = [PlannedStep(**s) for s in data.get("steps", [])]
    except Exception as e:
        print(f"[Replan] LLM error: {e}")
        steps = []

    return TaskPlan(original_task=original_task, steps=steps)
