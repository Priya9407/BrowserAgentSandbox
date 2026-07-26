import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

client = genai.Client(
    api_key=os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
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
- If the task is already complete, return action_type = "done".
- Never repeat a step already listed above unless the page clearly changed.
- The selector MUST exist in the HTML. Never invent selectors.
- reasoning MUST explain why this specific action moves the task forward.
- cited_source_text MUST be the exact visible/hidden text that justified this action.
- cited_source_location MUST be a CSS selector pointing to that text's element.
"""

    response = client.models.generate_content(
        model="gemini-flash-latest",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema={
                "type": "OBJECT",
                "properties": {
                    "action_type": {"type": "STRING"},
                    "target": {"type": "STRING"},
                    "reasoning": {"type": "STRING"},
                    "cited_source_text": {"type": "STRING"},
                    "cited_source_location": {"type": "STRING"},
                },
                "required": [
                    "action_type",
                    "target",
                    "reasoning",
                    "cited_source_text",
                    "cited_source_location",
                ],
            },
        ),
    )

    result = response.parsed

    print("\n========== GEMINI ==========")
    print(result)
    print("============================\n")

    return result
