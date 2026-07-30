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


def get_clarification_questions(user_task: str) -> list[str]:
    """
    Analyzes the user task and returns a list of clarifying questions
    that must be answered before execution can begin.
    Returns an empty list if the task is already specific enough.
    """
    prompt = f"""You are a smart AI assistant helping a browser automation agent understand the user''s intent.

USER TASK: {user_task}

Identify ONLY the critical missing details that:
1. The agent CANNOT reasonably guess or search for itself
2. Without which the agent cannot complete the task at all
3. Are specific to this user (personal preferences, account details, etc.)

DO NOT ask about things the agent can figure out itself (which website, generic steps, etc.)
If the task is already self-contained, return an empty list.

Return ONLY this JSON:
{{"questions": ["question 1", "question 2"]}}

Examples:
- "Book a movie ticket" -> {{"questions": ["Which movie and which city/theater?", "Which date and showtime?", "How many seats and seat type?"]}}
- "Search for Sony headphones price" -> {{"questions": []}}
- "Order pizza from Swiggy" -> {{"questions": ["Which restaurant and pizza?", "What is your delivery address?"]}}
- "Book a flight to Delhi" -> {{"questions": ["Where are you flying from?", "What is your travel date and class?"]}}
"""

    try:
        response = client.chat.completions.create(
            model="meta/llama-3.1-70b-instruct",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        questions = data.get("questions", [])
        print(f"[Clarifier] Task: {user_task!r}")
        print(f"[Clarifier] Questions: {questions}")
        return [q for q in questions if q and isinstance(q, str)]
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
