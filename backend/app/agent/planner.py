import os
import json

from dotenv import load_dotenv
from openai import OpenAI

from app.schemas.plan_schema import TaskPlan, PlannedStep

load_dotenv()

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.getenv("NVIDIA_API_KEY")
)


def generate_plan(user_task: str, dom: str | None = None) -> TaskPlan:
    """
    Calls the LLM to break a free-text goal into a structured, ordered list
    of steps. Each step is a plain-language goal — NOT a grounded AgentAction
    yet. Grounding into actual selectors happens later, step-by-step, via
    the existing get_next_action() call in llm.py.
    """

    dom_block = f"\nCURRENT PAGE HTML (for context only, may change by execution time):\n{dom}" if dom else ""

    prompt = f"""
You are a planning assistant for a secure browser automation agent.

USER TASK:
{user_task}
{dom_block}

Break this task down into a short ordered list of high-level steps needed
to complete it. Each step should describe WHAT needs to happen in plain
language — NOT a CSS selector, NOT low-level browser instructions.
Keep the list as short as possible while still being complete (typically 2-6 steps).

Return a JSON object with EXACTLY this shape:
{{
  "steps": [
    {{"step_number": 1, "goal": "...", "action_type_hint": "click|type|navigate|scroll|submit|done"}},
    {{"step_number": 2, "goal": "...", "action_type_hint": "..."}}
  ]
}}
"""

    try:
        response = client.chat.completions.create(
            model="meta/llama-3.1-70b-instruct",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content)
        steps = [PlannedStep(**s) for s in result.get("steps", [])]
    except Exception as e:
        print(f"Planner LLM Error: {e}")
        steps = []

    return TaskPlan(original_task=user_task, steps=steps)