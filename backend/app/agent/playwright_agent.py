from pathlib import Path
from playwright.sync_api import sync_playwright

from app.agent.agent import BrowserAgent
from app.policy.hidden_detector import HiddenContentDetector
from app.policy.policy_engine import PolicyEngine
from app.policy.decision import PolicyDecision


def run_browser_agent():

    browser_agent = BrowserAgent()

    browser_agent.set_task("Buy the laptop")

    detector = HiddenContentDetector()

    policy = PolicyEngine()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            slow_mo=500,
        )

        page = browser.new_page()

        project_root = Path(__file__).resolve().parents[3]

        page.goto((project_root / "test-pages" / "shopping.html").as_uri())

        # ---------------------------------
        # STEP 1
        # Detect hidden content
        # ---------------------------------

        hidden = detector.detect(page)

        print("\nHidden Detector")
        print(hidden)

        # ---------------------------------
        # STEP 2
        # Extract DOM
        # ---------------------------------

        dom = page.content()

        # ---------------------------------
        # STEP 3
        # Ask Gemini
        # ---------------------------------

        action = browser_agent.think(dom)

        print("\nAgent Action")
        print(action.model_dump())

        # ---------------------------------
        # STEP 4
        # Policy Engine
        # ---------------------------------

        result = policy.evaluate(action, hidden["hidden_found"])

        print("\nPolicy Result")
        print(result.model_dump())

        # ---------------------------------
        # STEP 5
        # Decision
        # ---------------------------------

        if result.decision == PolicyDecision.ALLOW:
            print("\nALLOW")

            if action.action_type == "click":
                page.click(action.target)

        elif result.decision == PolicyDecision.ESCALATE:
            print("\nESCALATE")

            answer = input("Approve action? (y/n): ")

            if answer.lower() == "y":
                page.click(action.target)

            else:
                print("Cancelled.")

        else:
            print("\nDENY")

        page.wait_for_timeout(5000)

        browser.close()


if __name__ == "__main__":
    run_browser_agent()
