import asyncio
from pathlib import Path
from playwright.sync_api import sync_playwright

from app.agent.agent import BrowserAgent
from app.policy.hidden_detector import HiddenContentDetector
from app.policy.policy_engine import PolicyEngine
from app.policy.decision import PolicyDecision
from app.policy.gate import enforce_action_contract, GateRejected


async def run_browser_agent_async(
    queue: asyncio.Queue,
    page_uri: str | None = None,
    user_task: str = "Buy the laptop",
    headless: bool = False,
    auto_approve_escalated: bool = False,
):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: run_browser_agent(
            queue,
            loop,
            page_uri=page_uri,
            user_task=user_task,
            headless=headless,
            auto_approve_escalated=auto_approve_escalated,
        ),
    )


def run_browser_agent(
    queue: asyncio.Queue = None,
    loop: asyncio.AbstractEventLoop = None,
    page_uri: str | None = None,
    user_task: str = "Buy the laptop",
    headless: bool = False,
    auto_approve_escalated: bool = False,
):
    browser_agent = BrowserAgent()
    browser_agent.set_task(user_task)

    detector = HiddenContentDetector()
    policy = PolicyEngine()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=500)
        page = browser.new_page()

        project_root = Path(__file__).resolve().parents[3]
        if page_uri is None:
            page_uri = (project_root / "test-pages" / "shopping.html").as_uri()
        page.goto(page_uri)

        while not browser_agent.is_done():
            # ------------------------------------------------------------------
            # Detect hidden content
            # ------------------------------------------------------------------
            hidden = detector.detect(page)

            # ------------------------------------------------------------------
            # Extract page text for the source classifier.
            #
            # visible_page_text — innerText of the full body (only rendered text,
            #                     mirrors what a human actually sees).
            # hidden_page_text  — concatenated innerText of every element the
            #                     hidden-detector flagged as concealed.
            # ------------------------------------------------------------------
            visible_page_text: str = page.evaluate(
                "() => document.body.innerText || ''"
            )

            hidden_page_text: str = " ".join(
                el.get("text", "") or ""
                for el in hidden.get("elements", [])
            )

            # ------------------------------------------------------------------
            # Extract DOM for the LLM
            # ------------------------------------------------------------------
            dom = page.content()

            # ------------------------------------------------------------------
            # Ask the LLM for the next action
            # ------------------------------------------------------------------
            action = browser_agent.think(dom)
            print(f"\n--- Step {browser_agent.step_count} ---")
            print(action.model_dump())

            if action.action_type == "done":
                print("Agent reports task complete.")
                break

            # ------------------------------------------------------------------
            # GATE — hard pre-condition check
            # Runs before Playwright or the policy engine see the action.
            # ------------------------------------------------------------------
            try:
                enforce_action_contract(action)
            except GateRejected as e:
                print(f"\nGATE REJECTED: {e}")
                break

            # ------------------------------------------------------------------
            # POLICY ENGINE — origin + risk → ALLOW / ESCALATE / DENY
            # ------------------------------------------------------------------
            result = policy.evaluate(
                action,
                hidden_content_detected=hidden["hidden_found"],
                user_task=browser_agent.user_task,
                visible_page_text=visible_page_text,
                hidden_page_text=hidden_page_text,
            )
            print(result.model_dump())

            # ------------------------------------------------------------------
            # Push to dashboard WebSocket queue
            # ------------------------------------------------------------------
            if queue is not None and loop is not None:
                payload = {
                    "action": action.model_dump(mode="json"),
                    "policy": result.model_dump(mode="json"),
                }
                asyncio.run_coroutine_threadsafe(queue.put(payload), loop)

            # ------------------------------------------------------------------
            # Execute / escalate / deny
            # ------------------------------------------------------------------
            if result.decision == PolicyDecision.ALLOW:
                _execute(page, action)

            elif result.decision == PolicyDecision.ESCALATE:
                print(f"\nESCALATE — origin={result.origin}, reason: {result.reason}")
                if auto_approve_escalated:
                    print("Auto-approving escalated action.")
                    _execute(page, action)
                else:
                    print("Escalated action not auto-approved. Stopping execution.")
                    break

            else:  # DENY
                print(f"DENY — {result.reason}")
                break

        page.wait_for_timeout(3000)
        browser.close()


def _execute(page, action):
    if action.action_type == "click":
        page.click(action.target)
    elif action.action_type == "navigate":
        page.goto(action.target)
    elif action.action_type in ("fill", "type"):
        page.fill(action.target, action.value or "")
    else:
        print(f"Unhandled action_type: {action.action_type}")


if __name__ == "__main__":
    run_browser_agent()
