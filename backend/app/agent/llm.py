import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

client = genai.Client(
    api_key=os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
)


def get_next_action(user_task: str, dom: str):

    prompt = f"""
You are a secure browser automation agent.

Your task is to determine the SINGLE next browser action.

USER TASK:
{user_task}

HTML:
{dom}

IMPORTANT RULES:

- Read the HTML carefully.
- Find the element that best satisfies the user's request.
- Return exactly ONE action.
- Never invent selectors.
- The selector MUST exist in the HTML.
- Use CSS selectors only.
- cited_source_location MUST also be a CSS selector.
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
