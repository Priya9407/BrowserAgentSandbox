"""
playwright_agent.py — Browser execution engine
"""

import asyncio
import time as _time
from pathlib import Path
from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeout

from app.agent.agent import BrowserAgent, MAX_STEP_RETRIES
from app.policy.hidden_detector import HiddenContentDetector
from app.policy.policy_engine import PolicyEngine
from app.policy.decision import PolicyDecision
from app.policy.gate import enforce_action_contract, GateRejected
from app.agent.planner import generate_plan
from app.agent.llm import ask_vision_for_element, replan_after_failure
from app.schemas.action_schema import AgentAction
from app.tracing.tracer import tracer
from app.aws.s3_client import upload_screenshot

# ---------------------------------------------------------------------------
# ARIA role map — maps our coarse labels to Playwright's role strings
# ---------------------------------------------------------------------------
_ROLE_ALIASES: dict[str, str] = {
    "button":    "button",
    "link":      "link",
    "textbox":   "textbox",
    "combobox":  "combobox",
    "checkbox":  "checkbox",
    "radio":     "radio",
    "listbox":   "listbox",
    "menuitem":  "menuitem",
    "heading":   "heading",
    "img":       "img",
    "searchbox": "searchbox",
    "generic":   None,         # no role — fall through to text search
}


# ---------------------------------------------------------------------------
# Semantic element resolution 
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# CAPTCHA / bot-check detection — bug fix (Milestone 3 item A)
#
# We do NOT attempt to solve image/visual CAPTCHA challenges. That's a
# deliberate scope boundary, not a missing feature: CAPTCHAs exist to stop
# automated agents, and this project isn't built to defeat that check.
#
# Before this fix, hitting a challenge (e.g. after clicking "I'm not a
# robot" and getting an image-selection puzzle) made the agent grind
# through the retry/re-plan loop uselessly until the whole task's step
# budget ran out — a silent, confusing timeout. This detects the
# challenge and fails honestly instead, same pattern as every other
# unrecoverable failure in this codebase.
# ---------------------------------------------------------------------------
def detect_captcha(page: Page) -> bool:
    try:
        return bool(
            page.evaluate(
                """() => {
                    const html = document.documentElement.innerHTML.toLowerCase();
                    return (
                        html.includes('recaptcha') ||
                        html.includes('hcaptcha') ||
                        html.includes('g-recaptcha') ||
                        document.querySelector('iframe[src*="recaptcha"]') !== null ||
                        document.querySelector('iframe[title*="captcha" i]') !== null
                    );
                }"""
            )
        )
    except Exception:
        return False


def semantic_find(page: Page, action: AgentAction, timeout_ms: int = 4000):
    """
    Multi-strategy element locator.  Returns a Playwright Locator or raises
    an exception if nothing works.

    Resolution order:
      1. get_by_role(role, name=label)     — most reliable on accessible pages
      2. get_by_role(role)                 — if label match fails (takes first)
      3. get_by_text(label, exact=False)   — text content search
      4. get_by_placeholder(label)         — inputs with placeholder
      5. CSS selector (action.target)      — LLM-provided fallback
      6. Vision pass (screenshot → LLM)   — last resort
    """
    sem = action.semantic_target
    role = _ROLE_ALIASES.get(sem.role.lower()) if sem.role else None
    label = (sem.label or "").strip()

    # ── Strategy 1: role + name ──────────────────────────────────────────
    if role and label:
        try:
            loc = page.get_by_role(role, name=label)
            loc.wait_for(state="visible", timeout=timeout_ms)
            print(f"[semantic_find] ✓ role={role} name='{label}'")
            return loc
        except Exception:
            pass

    # ── Strategy 2: role only (first visible) ────────────────────────────
    if role:
        try:
            loc = page.get_by_role(role).first
            loc.wait_for(state="visible", timeout=timeout_ms)
            print(f"[semantic_find] ✓ role={role} (first)")
            return loc
        except Exception:
            pass

    # ── Strategy 3: text content ─────────────────────────────────────────
    if label:
        try:
            loc = page.get_by_text(label, exact=False).first
            loc.wait_for(state="visible", timeout=timeout_ms)
            print(f"[semantic_find] ✓ text='{label}'")
            return loc
        except Exception:
            pass

    # ── Strategy 4: placeholder ──────────────────────────────────────────
    if label:
        try:
            loc = page.get_by_placeholder(label, exact=False)
            loc.wait_for(state="visible", timeout=timeout_ms)
            print(f"[semantic_find] ✓ placeholder='{label}'")
            return loc
        except Exception:
            pass

    # ── Strategy 5: CSS selector ─────────────────────────────────────────
    css = (action.target or "").strip()
    if css:
        try:
            loc = page.locator(css)
            loc.wait_for(state="visible", timeout=timeout_ms)
            print(f"[semantic_find] ✓ CSS '{css}'")
            return loc
        except Exception:
            pass

    # ── Strategy 6: vision fallback ──────────────────────────────────────
    description = label or action.reasoning[:80]
    print(f"[semantic_find] falling back to vision for: '{description}'")
    vision_selector = ask_vision_for_element(page, description)
    if vision_selector:
        try:
            loc = page.locator(vision_selector)
            loc.wait_for(state="visible", timeout=timeout_ms)
            print(f"[semantic_find] ✓ vision selector '{vision_selector}'")
            return loc
        except Exception:
            pass

    raise RuntimeError(
        f"Could not locate element — role={sem.role!r}, label={label!r}, "
        f"CSS={css!r}"
    )


# ---------------------------------------------------------------------------
# Action execution 
# ---------------------------------------------------------------------------

def _execute(page: Page, action: AgentAction) -> None:
    """
    Execute a single browser action using semantic targeting with CSS fallback.
    Raises RuntimeError / PlaywrightTimeout on failure so the recovery loop
    in the caller can catch and handle it.
    """
    if action.action_type == "navigate":
        page.goto(action.target, timeout=15_000, wait_until="domcontentloaded")
        return

    if action.action_type == "scroll":
        page.evaluate("window.scrollBy(0, 400)")
        return

    loc = semantic_find(page, action)

    if action.action_type == "click":
        loc.click(timeout=5_000)

    elif action.action_type in ("fill", "type"):
        loc.fill(action.value or "", timeout=5_000)

    else:
        print(f"[_execute] unhandled action_type: {action.action_type}")


# ---------------------------------------------------------------------------
# Async wrapper
# ---------------------------------------------------------------------------

async def run_browser_agent_async(
    queue: asyncio.Queue,
    page_uri: str | None = None,
    user_task: str = "Buy the laptop",
    headless: bool = False,
    auto_approve_escalated: bool = False,
    step_callback=None,
    trace_id: str | None = None,
):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: run_browser_agent(
            queue,
            loop,
            page_uri=page_uri,
            user_task=user_task,
            headless=headless,
            auto_approve_escalated=auto_approve_escalated,
            step_callback=step_callback,
            trace_id=trace_id,
        ),
    )
    return result


# ---------------------------------------------------------------------------
# Main execution loop
# ---------------------------------------------------------------------------

def run_browser_agent(
    queue: asyncio.Queue = None,
    loop: asyncio.AbstractEventLoop = None,
    page_uri: str | None = None,
    user_task: str = "Buy the laptop",
    headless: bool = False,
    auto_approve_escalated: bool = False,
    step_callback=None,
    trace_id: str | None = None,
):
    # ── _emit helper ────────────────────────────────────────────────────
    def _emit(status: str, text: str, step_event: dict | None = None):
        """
        Fire the async step_callback from this sync thread.

        step_event (optional) carries structured timeline metadata:
          {
            "step_number":  int,
            "total_steps":  int,
            "goal":         str,
            "outcome":      "running" | "success" | "failed" | "skipped",
            "retry":        int,    # 0 = first attempt
          }
        """
        if step_callback is not None and loop is not None:
            payload = {"status": status, "text": text}
            if step_event:
                payload["step_event"] = step_event
            asyncio.run_coroutine_threadsafe(
                step_callback(status, text, step_event), loop
            )

    # ── Initialise agent ────────────────────────────────────────────────
    browser_agent = BrowserAgent()
    browser_agent.set_task(user_task)

    # ── Tracing (X-Ray placeholder — see app/tracing/tracer.py) ──────────
    trace_seg = tracer.start_segment("chat_task", trace_id=trace_id, user_task=user_task)
    _task_start = _time.time()
    _success_count = 0
    _fail_count = 0

    # ── Planning ─────────────────────────────────────────────────────────
    _emit("step", "Generating plan…")
    _plan_sub = trace_seg.start_subsegment("planner.generate_plan")
    plan = generate_plan(user_task)
    trace_seg.finish_subsegment(_plan_sub)
    print("\n========== GENERATED PLAN ==========")
    print(plan.model_dump_json(indent=2))
    print("=====================================\n")
    browser_agent.set_plan(plan)

    total = len(plan.steps) if plan.steps else 0
    if total:
        summary = " → ".join(s.goal for s in plan.steps)
        _emit("step", f"Plan ready ({total} steps): {summary}")
    else:
        _emit("step", "No plan steps generated — running freeform.")

    detector = HiddenContentDetector()
    policy = PolicyEngine()

    # Track completed steps for re-planning context
    completed_steps: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        page.set_viewport_size({"width": 1280, "height": 900})

        project_root = Path(__file__).resolve().parents[3]
        if page_uri is None:
            page_uri = (project_root / "test-pages" / "shopping.html").as_uri()
        page.goto(page_uri, timeout=15_000, wait_until="domcontentloaded")
        _emit("step", "Browser open — starting task…")

        # ================================================================
        # Main execution loop
        # ================================================================
        # ── Task outcome tracking — bug fix (Milestone 3 item A) ───────────
        # Previously, ANY exit from the loop below (CAPTCHA block, policy
        # DENY, gate rejection, or simply running out of steps) fell through
        # to the same code path as genuine success, and main.py reported
        # "done" unconditionally regardless of why the loop actually
        # stopped. Default to "error/incomplete" here; only the explicit
        # "all steps complete" path below flips this to "done".
        task_outcome = "error"
        task_outcome_reason = "Task ended before completion (step budget exhausted)."

        while not browser_agent.is_done():
            total = len(browser_agent.plan.steps) if browser_agent.plan and browser_agent.plan.steps else 0
            step_idx = browser_agent.current_step_index
            retry_count = browser_agent.current_step_failure_count()

            # ── Emit current step into chat timeline ────────────────────
            if browser_agent.plan and browser_agent.plan.steps:
                current = browser_agent.plan.steps[step_idx]
                step_evt = {
                    "step_number": step_idx + 1,
                    "total_steps": total,
                    "goal": current.goal,
                    "outcome": "running",
                    "retry": retry_count,
                }
                retry_label = f" (retry {retry_count})" if retry_count else ""
                _emit(
                    "step",
                    f"Step {step_idx + 1}/{total}: {current.goal}{retry_label}",
                    step_evt,
                )

            # ── Hidden content detection ─────────────────────────────────
            hidden = detector.detect(page)
            visible_page_text: str = page.evaluate("() => document.body.innerText || ''")
            hidden_page_text: str = " ".join(
                el.get("text", "") or "" for el in hidden.get("elements", [])
            )
            dom = page.content()

            # ── CAPTCHA / bot-check detection ─────────────────────────────
            # See detect_captcha() docstring — we never attempt to solve the
            # challenge ourselves. Instead: pause, ask the human to solve it
            # in the visible browser window, and resume once they signal
            # they're done (via POST /resolve-captcha). Mirrors the existing
            # human-approval pattern used for escalated actions.
            if detect_captcha(page):
                from app.agent.captcha_state import pending_captchas

                pending_captchas[trace_seg.trace_id] = "pending"
                _emit(
                    "step",
                    "⏸ CAPTCHA detected — please solve it in the browser "
                    "window, then click Resume.",
                    {
                        "step_number": step_idx + 1,
                        "total_steps": total,
                        "goal": browser_agent.current_step_goal,
                        "outcome": "paused",
                        "retry": retry_count,
                        "session_id": trace_seg.trace_id,
                    },
                )

                waited_ms = 0
                timeout_ms = 5 * 60 * 1000  # 5 minutes — don't hang forever
                while (
                    pending_captchas.get(trace_seg.trace_id) == "pending"
                    and waited_ms < timeout_ms
                ):
                    page.wait_for_timeout(1000)
                    waited_ms += 1000

                resolved = pending_captchas.pop(trace_seg.trace_id, None) == "resolved"
                if resolved:
                    _emit(
                        "step",
                        "▶ Resuming after human solved the CAPTCHA…",
                        {
                            "step_number": step_idx + 1,
                            "total_steps": total,
                            "goal": browser_agent.current_step_goal,
                            "outcome": "running",
                            "retry": retry_count,
                        },
                    )
                    continue  # re-loop: re-check the page fresh, no LLM call spent

                task_outcome = "error"
                task_outcome_reason = (
                    "CAPTCHA was not resolved within the timeout — "
                    "could not complete automatically."
                )
                break
            _llm_sub = trace_seg.start_subsegment(
                "llm.get_next_action", step=browser_agent.step_count
            )
            action = browser_agent.think(dom)
            trace_seg.finish_subsegment(_llm_sub)
            print(f"\n--- Step {browser_agent.step_count} ---")
            print(action.model_dump())

            # ── Ask signal ────────────────────────────────────────────────
            if action.action_type == "ask":
                from app.agent.ask_state import pending_asks
                pending_asks[trace_seg.trace_id] = {"status": "pending", "question": action.value, "answer": None}
                
                _emit(
                    "step",
                    f"❓ Agent asks: {action.value}",
                    {
                        "step_number": step_idx + 1,
                        "total_steps": total,
                        "goal": browser_agent.current_step_goal,
                        "outcome": "paused",
                        "retry": retry_count,
                        "session_id": trace_seg.trace_id,
                        "ask_question": action.value,
                    },
                )
                
                waited_ms = 0
                timeout_ms = 5 * 60 * 1000
                while pending_asks.get(trace_seg.trace_id, {}).get("status") == "pending" and waited_ms < timeout_ms:
                    page.wait_for_timeout(1000)
                    waited_ms += 1000
                    
                ask_state = pending_asks.pop(trace_seg.trace_id, {})
                if ask_state.get("status") == "resolved":
                    ans = ask_state.get("answer")
                    if browser_agent.history:
                        browser_agent.history[-1]["reasoning"] += f"\n[User answered: {ans}]"
                    _emit(
                        "step",
                        f"▶ Resuming with user answer: {ans}",
                        {
                            "step_number": step_idx + 1,
                            "total_steps": total,
                            "goal": browser_agent.current_step_goal,
                            "outcome": "running",
                            "retry": retry_count,
                        },
                    )
                    continue
                else:
                    task_outcome = "error"
                    task_outcome_reason = "Timed out waiting for user answer."
                    break

            # ── Done signal ───────────────────────────────────────────────
            if action.action_type == "done":
                if browser_agent.plan and not browser_agent.is_last_step():
                    goal = browser_agent.current_step_goal
                    _emit(
                        "step",
                        f"✓ Completed: {goal}",
                        {
                            "step_number": step_idx + 1,
                            "total_steps": total,
                            "goal": goal,
                            "outcome": "success",
                            "retry": retry_count,
                        },
                    )
                    completed_steps.append({"goal": goal})
                    browser_agent.record_step_success()
                    browser_agent.advance_step()
                    continue
                else:
                    ans = action.value or (action.reasoning if "price" in action.reasoning.lower() else None)
                    msg = f"All steps complete. Result: {ans}" if action.value else "All steps complete."
                    
                    if browser_agent.plan and browser_agent.plan.steps:
                        goal = browser_agent.current_step_goal
                        _emit(
                            "step",
                            f"✓ Completed: {goal}\n\n{msg}",
                            {
                                "step_number": step_idx + 1,
                                "total_steps": total,
                                "goal": goal,
                                "outcome": "success",
                                "retry": retry_count,
                            },
                        )
                        browser_agent.record_step_success()
                    else:
                        _emit("step", msg)
                    
                    task_outcome = "done"
                    task_outcome_reason = ans
                    break

            # ── Gate ─────────────────────────────────────────────────────
            try:
                enforce_action_contract(action)
            except GateRejected as e:
                _emit("error", f"Gate rejected action: {e}")
                print(f"\nGATE REJECTED: {e}")
                task_outcome = "error"
                task_outcome_reason = f"Gate rejected action: {e}"
                break

            # ── Policy engine ─────────────────────────────────────────────
            result = policy.evaluate(
                action,
                hidden_content_detected=hidden["hidden_found"],
                user_task=browser_agent.user_task,
                visible_page_text=visible_page_text,
                hidden_page_text=hidden_page_text,
            )
            import app.agent.escalation_state as es
            if result.decision == PolicyDecision.ESCALATE and es.auto_approve_low_unknown and result.risk_level in ("LOW", "UNKNOWN"):
                result.decision = PolicyDecision.ALLOW
                result.reason = f"Auto-approved {result.risk_level} risk action."
                _emit("step", f"Auto-approved {result.risk_level} risk action: {action.action_type}")

            print(result.model_dump())

            if result.decision != PolicyDecision.ALLOW:
                _emit("step", f"Policy: {result.decision} — {result.reason}")

            # ── Push to WebSocket dashboard ───────────────────────────────
            if queue is not None and loop is not None:
                payload = {
                    "action": action.model_dump(mode="json"),
                    "policy": result.model_dump(mode="json"),
                }
                asyncio.run_coroutine_threadsafe(queue.put(payload), loop)

            # ── Execute / escalate / deny ─────────────────────────────────
            if result.decision == PolicyDecision.ALLOW:
                _exec_sub = trace_seg.start_subsegment(
                    "browser.execute_action", action_type=action.action_type
                )
                execution_ok = _execute_with_recovery(
                    page=page,
                    action=action,
                    browser_agent=browser_agent,
                    completed_steps=completed_steps,
                    dom=dom,
                    emit=_emit,
                    total=total,
                )
                trace_seg.finish_subsegment(
                    _exec_sub, error=None if execution_ok else "execution_failed"
                )
                if execution_ok:
                    _success_count += 1
                    browser_agent.record_step_success()
                else:
                    _fail_count += 1
                    # advance_step() only when the action is done-like
                    # (the step goal advance is handled per-done signal
                    #  or after a successful non-done action within a step)
                    # We only advance if the action type hints completion
                    _maybe_advance(browser_agent, action, completed_steps, _emit, total)

            elif result.decision == PolicyDecision.ESCALATE:
                _handle_escalation(
                    page=page,
                    action=action,
                    result=result,
                    browser_agent=browser_agent,
                    completed_steps=completed_steps,
                    auto_approve=auto_approve_escalated,
                    queue=queue,
                    loop=loop,
                    emit=_emit,
                    total=total,
                )

            else:  # DENY
                _emit("step", f"Blocked by policy: {result.reason}")
                print(f"DENY — {result.reason}")
                task_outcome = "error"
                task_outcome_reason = f"Blocked by policy: {result.reason}"
                break

        # removed arbitrary 2s delay

        # ── Screenshot placeholder (Milestone 3 item C — S3, optional) ────
        # Falls back to a local file path when AWS isn't configured yet;
        # see app/aws/s3_client.py. Never raises — a failed screenshot
        # should not take down the whole task run.
        try:
            screenshot_dir = Path(__file__).resolve().parents[3] / "backend" / "logs" / "screenshots"
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            screenshot_path = screenshot_dir / f"{trace_seg.trace_id}.png"
            page.screenshot(path=str(screenshot_path))
            screenshot_url = upload_screenshot(
                str(screenshot_path), key=f"{trace_seg.trace_id}.png"
            )
            trace_seg.set_metadata(screenshot_url=screenshot_url)
        except Exception as exc:
            print(f"[playwright_agent] screenshot/upload skipped: {exc}")

        if not headless:
            print("[playwright_agent] Task complete. Keeping browser open for 1 hour for manual inspection...")
            try:
                page.wait_for_timeout(3600_000)
            except Exception:
                pass

        browser.close()

    # ── Close out the trace segment with final run stats ──────────────────
    trace_seg.set_metadata(
        success_count=_success_count,
        fail_count=_fail_count,
        elapsed_seconds=round(_time.time() - _task_start, 2),
    )
    tracer.finish_segment(trace_seg)

    # ── Bug fix (Milestone 3 item A) ────────────────────────────────────
    # Return the real outcome instead of letting callers assume success.
    # Previously this function returned nothing, and main.py sent a
    # hardcoded "done" status regardless of whether the task actually
    # completed, was blocked by policy, hit a CAPTCHA, or ran out of steps.
    return {
        "status": task_outcome,               # "done" | "error"
        "reason": task_outcome_reason,
        "trace_id": trace_seg.trace_id,
        "success_count": _success_count,
        "fail_count": _fail_count,
        "elapsed_seconds": round(_time.time() - _task_start, 2),
    }


# ---------------------------------------------------------------------------
# Recovery loop (Task B)
# ---------------------------------------------------------------------------

def _execute_with_recovery(
    page: Page,
    action: AgentAction,
    browser_agent: BrowserAgent,
    completed_steps: list[dict],
    dom: str,
    emit,
    total: int,
) -> bool:
    """
    Execute action with the recovery ladder:
      1. Try execution (semantic_find already handles multi-strategy targeting)
      2. On failure: if retry budget remains, retry immediately (same action)
      3. If retries exhausted: request a re-plan from the LLM
      4. If re-plan also fails or returns empty: emit honest failure, skip step

    Returns True if the action eventually succeeded, False otherwise.
    """
    step_idx = browser_agent.current_step_index
    goal = browser_agent.current_step_goal

    try:
        _execute(page, action)
        emit("step", f"→ {action.action_type}: {action.semantic_target.label or action.target}")
        return True

    except Exception as exc:
        failure_msg = str(exc)
        failure_count = browser_agent.record_step_failure()
        print(f"[Recovery] execution failed (attempt {failure_count}): {failure_msg}")

        # ── Retry (one attempt) ───────────────────────────────────────────
        if failure_count <= MAX_STEP_RETRIES:
            emit(
                "step",
                f"⚠ Step {step_idx + 1} failed — retrying… ({failure_msg[:80]})",
                {
                    "step_number": step_idx + 1,
                    "total_steps": total,
                    "goal": goal,
                    "outcome": "running",
                    "retry": failure_count,
                },
            )
            try:
                # Give the page a moment to settle before the retry
                page.wait_for_timeout(800)
                _execute(page, action)
                emit("step", f"✓ Retry succeeded: {goal}")
                return True
            except Exception as retry_exc:
                failure_msg = str(retry_exc)
                browser_agent.record_step_failure()
                print(f"[Recovery] retry also failed: {failure_msg}")

        # ── Re-plan ───────────────────────────────────────────────────────
        emit(
            "step",
            f"↻ Re-planning after failed step {step_idx + 1}: {failure_msg[:100]}",
            {
                "step_number": step_idx + 1,
                "total_steps": total,
                "goal": goal,
                "outcome": "failed",
                "retry": failure_count,
            },
        )

        failed_step = {"goal": goal}
        current_dom = page.content()
        new_plan = replan_after_failure(
            original_task=browser_agent.user_task,
            completed_steps=completed_steps,
            failed_step=failed_step,
            failure_reason=failure_msg,
            dom=current_dom,
        )

        if new_plan.steps:
            browser_agent.replace_remaining_plan(new_plan)
            new_total = len(new_plan.steps)
            emit(
                "step",
                f"↻ New plan ({new_total} steps): "
                + " → ".join(s.goal for s in new_plan.steps),
            )
            return False  # let the main loop re-run with the new plan

        # ── Honest failure: couldn't complete this part ────────────────
        emit(
            "step",
            f"✗ Couldn't complete: \"{goal}\" — {failure_msg[:120]}. Moving on.",
            {
                "step_number": step_idx + 1,
                "total_steps": total,
                "goal": goal,
                "outcome": "skipped",
                "retry": failure_count,
            },
        )
        # Skip the failed step and continue with the next
        browser_agent.advance_step()
        return False


def _maybe_advance(browser_agent, action, completed_steps, emit, total):
    """
    After a successful non-done action, decide whether to advance the step
    pointer.  We advance immediately so the next think() call focuses on
    the next step goal — unless the action is a multi-action step (the LLM
    will return done when the step is satisfied).
    """
    # We don't force-advance here; we let the next think() return "done"
    # for the step when it's satisfied.  This matches the original contract.
    pass


# ---------------------------------------------------------------------------
# Escalation handler
# ---------------------------------------------------------------------------

def _handle_escalation(
    page, action, result, browser_agent, completed_steps,
    auto_approve, queue, loop, emit, total,
):
    step_idx = browser_agent.current_step_index
    goal = browser_agent.current_step_goal

    if auto_approve:
        emit("step", f"Auto-approved escalated action: {action.action_type}")
        _execute_with_recovery(
            page=page, action=action, browser_agent=browser_agent,
            completed_steps=completed_steps, dom=page.content(),
            emit=emit, total=total,
        )
        browser_agent.advance_step()
        return

    if queue is not None and loop is not None:
        print(f"Waiting for human approval on action {action.action_id}…")
        from app.agent.escalation_state import pending_escalations
        pending_escalations[action.action_id] = "pending"

        while pending_escalations.get(action.action_id) == "pending":
            page.wait_for_timeout(1000)

        decision_ui = pending_escalations.get(action.action_id)
        if decision_ui == "approved":
            emit("step", f"Human approved — executing {action.action_type}")
            print(f"Human APPROVED action {action.action_id}")
            _execute_with_recovery(
                page=page, action=action, browser_agent=browser_agent,
                completed_steps=completed_steps, dom=page.content(),
                emit=emit, total=total,
            )
            browser_agent.advance_step()
        else:
            emit(
                "step",
                f"Human denied action — skipping step {step_idx + 1}.",
                {
                    "step_number": step_idx + 1,
                    "total_steps": total,
                    "goal": goal,
                    "outcome": "skipped",
                    "retry": 0,
                },
            )
            print(f"Human DENIED action {action.action_id}.")
            browser_agent.advance_step()
    else:
        emit("error", "Escalated action requires human approval but no UI connected.")
