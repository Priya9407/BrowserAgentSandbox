from pathlib import Path

from playwright.sync_api import sync_playwright

from app.agent.agent import BrowserAgent


def run_browser_agent():

    # ----------------------------
    # Create Browser Agent
    # ----------------------------
    agent = BrowserAgent()

    # Give the agent a task
    agent.set_task("Buy the laptop")

    # ----------------------------
    # Launch Playwright
    # ----------------------------
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=500)

        page = browser.new_page()

        # ----------------------------
        # Open Test Page
        # ----------------------------
        project_root = Path(__file__).resolve().parents[3]

        html_path = project_root / "test-pages" / "shopping.html"

        page.goto(html_path.as_uri())

        # ----------------------------
        # Read DOM
        # ----------------------------
        dom = page.content()

        print("\n========== DOM ==========\n")
        print(dom)

        # ----------------------------
        # Ask Gemini
        # ----------------------------
        action = agent.think(dom)

        print("\n========== AGENT RESPONSE ==========\n")
        print(action.model_dump())

        # ----------------------------
        # Execute Action
        # ----------------------------
        if action.action_type == "click":
            print(f"\nClicking {action.target}")

            page.click(action.target)

        else:
            print("Unsupported Action")

        # Wait so you can see the click
        page.wait_for_timeout(3000)

        browser.close()


if __name__ == "__main__":
    run_browser_agent()
