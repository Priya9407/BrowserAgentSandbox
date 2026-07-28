import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.getenv("NVIDIA_API_KEY")
)


def get_next_action(user_task: str, dom: str, history: list | None = None):
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
- If the CURRENT STEP (or the whole task, if no plan/steps were given) is already
  satisfied based on the HTML, return action_type = "done" to signal that step is
  complete — do not return "done" just because earlier steps succeeded.
- The `target` (CSS selector) MUST exist in the HTML. Never invent selectors.
- reasoning MUST explain why this specific action moves the task forward.
- cited_source_text MUST be the exact visible/hidden text that justified this action. (If clicking an icon or button without text, cite its label or aria-label. NEVER leave this empty.)
- cited_source_location MUST be a CSS selector pointing to that text's element. (NEVER leave this empty.)

Return a JSON object with EXACTLY these keys:
{{
  "action_type": "...",
  "target": "...",
  "reasoning": "...",
  "cited_source_text": "...",
  "cited_source_location": "..."
}}
- cited_source_text MUST be the exact visible/hidden text that justified this action.
- cited_source_location MUST be a CSS selector pointing to that text's element.
"""

    response = client.chat.completions.create(
        model="meta/llama-3.1-70b-instruct",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        response_format={"type": "json_object"}
    )

    import json
    try:
        result = json.loads(response.choices[0].message.content)
        if "selector" in result and "target" not in result:
            result["target"] = result["selector"]
    except Exception as e:
        print(f"Failed to parse JSON: {e}")
        result = {}

    print("\n========== NVIDIA LLAMA ==========")
    print(result)
    print("============================\n")

    return result
