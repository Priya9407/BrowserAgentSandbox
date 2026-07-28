import asyncio
from pathlib import Path
from playwright.sync_api import sync_playwright

from app.agent.agent import BrowserAgent
from app.policy.hidden_detector import HiddenContentDetector
from app.policy.policy_engine import PolicyEngine
from app.policy.decision import PolicyDecision
from app.policy.gate import enforce_action_contract, GateRejected
from app.agent.planner import generate_plan


async def run_browser_agent_async(
    queue: asyncio.Queue,
    page_uri: str | None = None,
    user_task: str = "Buy the laptop",
    headless: bool = False,
    auto_approve_escalated: bool = False,
    step_callback=None,          # async callable(status: str, text: str) | None
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
            step_callback=step_callback,
        ),
    )


def run_browser_agent(
    queue: asyncio.Queue = None,
    loop: asyncio.AbstractEventLoop = None,
    page_uri: str | None = None,
    user_task: str = "Buy the laptop",
    headless: bool = False,
    auto_approve_escalated: bool = False,
    step_callback=None,          # async callable(status: str, text: str) | None
):
    def _emit(status: str, text: str):
        """Fire the async step_callback from this sync thread, if one was provided."""
        if step_callback is not None and loop is not None:
            asyncio.run_coroutine_threadsafe(step_callback(status, text), loop)

    browser_agent = BrowserAgent()
    browser_agent.set_task(user_task)

    # ------------------------------------------------------------------
    # PLANNING LAYER
    # ------------------------------------------------------------------
    _emit("step", "Generating plan…")
    plan = generate_plan(user_task)
    print("\n========== GENERATED PLAN ==========")
    print(plan.model_dump_json(indent=2))
    print("=====================================\n")
    browser_agent.set_plan(plan)

    if plan.steps:
        plan_summary = " → ".join(s.goal for s in plan.steps)
        _emit("step", f"Plan ready ({len(plan.steps)} steps): {plan_summary}")
    else:
        _emit("step", "No plan steps generated — running freeform.")

    detector = HiddenContentDetector()
    policy = PolicyEngine()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=500)
        page = browser.new_page()

        project_root = Path(__file__).resolve().parents[3]
        if page_uri is None:
            page_uri = (project_root / "test-pages" / "shopping.html").as_uri()
        page.goto(page_uri)

        _emit("step", f"Browser open — starting task…")

        while not browser_agent.is_done():
            # ------------------------------------------------------------------
            # Emit current planned step into chat
            # ------------------------------------------------------------------
            if browser_agent.plan and browser_agent.plan.steps:
                current = browser_agent.plan.steps[browser_agent.current_step_index]
                _emit(
                    "step",
                    f"Step {browser_agent.current_step_index + 1}/{len(browser_agent.plan.steps)}: "
                    f"{current.goal}",
                )

            # ------------------------------------------------------------------
            # Detect hidden content
            # ------------------------------------------------------------------
            hidden = detector.detect(page)

            visible_page_text: str = page.evaluate(
                "() => document.body.innerText || ''"
            )
            hidden_page_text: str = " ".join(
                el.get("text", "") or ""
                for el in hidden.get("elements", [])
            )

            dom = page.content()

            # ------------------------------------------------------------------
            # Ask LLM for next action
            # ------------------------------------------------------------------
            action = browser_agent.think(dom)
            print(f"\n--- Step {browser_agent.step_count} ---")
            print(action.model_dump())

            if action.action_type == "done":
                if browser_agent.plan and not browser_agent.is_last_step():
                    completed_goal = browser_agent.plan.steps[browser_agent.current_step_index].goal
                    _emit("step", f"✓ Completed: {completed_goal}")
                    browser_agent.advance_step()
                    continue
                else:
                    _emit("step", "All steps complete.")
                    break

            # ------------------------------------------------------------------
            # GATE
            # ------------------------------------------------------------------
            try:
                enforce_action_contract(action)
            except GateRejected as e:
                _emit("error", f"Gate rejected action: {e}")
                print(f"\nGATE REJECTED: {e}")
                break

            # ------------------------------------------------------------------
            # POLICY ENGINE
            # ------------------------------------------------------------------
            result = policy.evaluate(
                action,
                hidden_content_detected=hidden["hidden_found"],
                user_task=browser_agent.user_task,
                visible_page_text=visible_page_text,
                hidden_page_text=hidden_page_text,
            )
            print(result.model_dump())

            # Emit policy result to chat if it's anything interesting
            if result.decision != PolicyDecision.ALLOW:
                _emit(
                    "step",
                    f"Policy: {result.decision} — {result.reason}",
                )

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
                _emit("step", f"→ {action.action_type} on {action.target}")
                _execute(page, action)
                browser_agent.advance_step()

            elif result.decision == PolicyDecision.ESCALATE:
                print(f"\nESCALATE — origin={result.origin}, reason: {result.reason}")
                if auto_approve_escalated:
                    _emit("step", f"Auto-approved escalated action: {action.action_type}")
                    _execute(page, action)
                    browser_agent.advance_step()
                else:
                    if queue is not None and loop is not None:
                        print(f"Waiting for human approval on action {action.action_id}...")
                        from app.agent.escalation_state import pending_escalations
                        pending_escalations[action.action_id] = "pending"

                        while pending_escalations.get(action.action_id) == "pending":
                            page.wait_for_timeout(1000)

                        decision_ui = pending_escalations.get(action.action_id)
                        if decision_ui == "approved":
                            _emit("step", f"Human approved — executing {action.action_type}")
                            print(f"Human APPROVED action {action.action_id}")
                            _execute(page, action)
                            browser_agent.advance_step()
                        else:
                            _emit("step", f"Human denied action — stopping.")
                            print(f"Human DENIED action {action.action_id}. Stopping.")
                            break
                    else:
                        _emit("error", "Escalated action requires human approval but no UI connected.")
                        break

            else:  # DENY
                _emit("step", f"Blocked: {result.reason}")
                print(f"DENY — {result.reason}")
                break

        page.wait_for_timeout(2000)
        browser.close()


def _execute(page, action):
    try:
        if action.action_type == "click":
            page.click(action.target, timeout=5000)
        elif action.action_type == "navigate":
            page.goto(action.target, timeout=10000)
        elif action.action_type in ("fill", "type"):
            page.fill(action.target, action.value or "", timeout=5000)
        else:
            print(f"Unhandled action_type: {action.action_type}")
    except Exception as e:
        print(f"Execution failed: {e}")


if __name__ == "__main__":
    run_browser_agent()
