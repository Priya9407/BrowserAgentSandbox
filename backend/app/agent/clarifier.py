"""
clarifier.py -- Pre-task Clarification Engine

Before the agent starts executing, this module asks the LLM:
"Is this task ambiguous? What critical details are missing?"

If the task needs clarification, the agent will emit one or more
ask-style questions that the user must answer before the browser
even opens. Once all answers are collected, the task is enriched
with the user''s context and handed to the planner.
"""

import json
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.getenv("NVIDIA_API_KEY"),
)


def get_clarification_questions(user_task: str) -> list[dict]:
    """
    Analyzes the user task and returns a list of clarifying questions that
    must be answered. Each entry is a dict:

        {"question": str, "options": [str, ...]}

    `options` is a list of concrete choices the user can pick from (e.g.
    payment method: ["Card", "UPI", "COD"]). If no sensible options exist
    for a question, it is an empty list — the UI then shows a free-text box
    with an "Other" chip instead.

    The task is started FIRST, then questions are asked ONE AT A TIME by
    /chat (via the ask mechanism) so the user never sees a wall of questions.
    Returns an empty list if the task is already specific enough.
    """
    prompt = f"""You are a smart AI assistant helping a browser automation agent understand the user''s intent.

USER TASK: {user_task}

Identify ONLY the critical missing details that:
1. The agent CANNOT reasonably guess or search for itself
2. Without which the agent cannot complete the task at all
3. Are specific to this user (personal preferences, product choices, etc.)

Keep it to the PRIMARY questions only (max 3) — do not over-ask.

DO NOT ask for:
  - Passwords, login credentials, or account details — the agent will ask for those on the login page if needed
  - Which website to visit — the agent can search or you can specify it in your task

DO ask for:
  - Specific product preferences (color, size, model)
  - Delivery/pickup preferences
  - Travel dates, locations
  - Payment method preference (if checkout will be needed)

When a question has a small, concrete set of reasonable answers (e.g.
payment method, seat type, ticket class), provide 2-5 concrete options in
`options`. For open-ended questions (movie name, date, address), leave
`options` as an empty list.

DO NOT invent brand names, product names, or prices as options — options
must be generic categories ("Card", "UPI", "COD", "Economy", "Standard").

DO NOT ask about things the agent can figure out itself (generic steps,
search queries, etc.)
If the task is already self-contained, return an empty list.

Return ONLY this JSON:
{{"questions": [{{"question": "...", "options": ["..."]}}]}}

Examples:
- "Book a movie ticket" -> {{"questions": [{{"question": "Which movie and which city/theater?", "options": []}}, {{"question": "Which date and showtime?", "options": []}}, {{"question": "How many seats and seat type?", "options": ["1 - Standard", "2 - Standard", "1 - Premium", "2 - Premium"]}}]}}
- "Search for Sony headphones price" -> {{"questions": []}}
- "Order pizza from Swiggy" -> {{"questions": [{{"question": "Which restaurant and pizza?", "options": []}}, {{"question": "What is your delivery address?", "options": []}}]}}
- "Order a large pepperoni pizza from Domino's in Bangalore" -> {{"questions": [{{"question": "What is your delivery address?", "options": []}}, {{"question": "Payment method preference?", "options": ["COD", "Card", "UPI"]}}]}}
- "Book a flight to Delhi" -> {{"questions": [{{"question": "Where are you flying from?", "options": []}}, {{"question": "What is your travel date and class?", "options": ["Economy", "Premium Economy", "Business"]}}]}}
- "Login to my Amazon account" -> {{"questions": []}}  (agent will ask for credentials on the page)
"""

    try:
        response = client.chat.completions.create(
            model="meta/llama-3.1-8b-instruct",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        raw = data.get("questions", [])
        questions = []
        for q in raw:
            if isinstance(q, str):
                questions.append({"question": q, "options": []})
            elif isinstance(q, dict) and q.get("question"):
                opts = q.get("options") or []
                questions.append({
                    "question": q["question"],
                    "options": [o for o in opts if isinstance(o, str) and o.strip()][:5],
                })
        print(f"[Clarifier] Task: {user_task!r}")
        print(f"[Clarifier] Questions: {questions}")
        return questions[:3]   # primary questions only
    except Exception as e:
        print(f"[Clarifier] Error: {e}")
        return []


def enrich_task_with_answers(original_task: str, qa_pairs: list[dict]) -> str:
    """
    Merges the original task with user-provided Q&A context.
    """
    if not qa_pairs:
        return original_task

    context_lines = "\n".join(
        f"- {pair.get('question', '')}: {pair.get('answer', '')}"
        for pair in qa_pairs
        if pair.get("answer")
    )

    return f"{original_task}\n\nAdditional context provided by the user:\n{context_lines}"
