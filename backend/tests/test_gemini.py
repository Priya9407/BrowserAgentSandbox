from app.agent.llm import get_next_action

dom = """
<button id="buy">
Buy Laptop
</button>
"""

response = get_next_action("Buy the laptop", dom)

print(response)
