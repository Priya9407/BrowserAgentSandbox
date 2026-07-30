"""
demo_runner.py — Scripted demo execution engine.

Runs one of the 4 pre-scripted demo tasks through the REAL pipeline:

    HiddenContentDetector.detect()   → finds hidden DOM text (used for buy_laptop)
    enforce_action_contract()        → gate — rejects actions with missing fields
    PolicyEngine.evaluate()          → risk + provenance + decision
    semantic_find() + _execute()     → real Playwright element targeting
    tracer subsegments               → X-Ray-shaped local trace file
    step_callback / WebSocket events → ChatPanel step timeline + ActionFeed

What this does NOT touch:
    generate_plan() / get_next_action() in llm.py  — never called here
    run_browser_agent() in playwright_agent.py      — not called here
    /chat endpoint or its _run_chat_agent() helper  — completely separate path

Pacing
------
Each step has a small fixed delay (STEP_DELAY_S) so the timeline dots animate
step-by-step in the UI instead of appearing all at once.  This is purely for
demo watchability — nothing is actually slow.

Escalation flow (buy_laptop step 3)
------------------------------------
1. HiddenContentDetector finds the display:none div in shopping.html.
2. demo_runner passes hidden_page_text to PolicyEngine.evaluate().
3. SourceClassifier matches cited_source_text against hidden_page_text
   → Origin.HIDDEN_PAGE_CONTENT.
4. PolicyEngine._decide() returns ESCALATE (PAYMENT-level action from hidden content).
5. demo_runner registers action_id in pending_escalations["pending"] and
   polls until the human clicks Approve or Deny in ActionFeed.jsx.
6. On approval  → _execute() runs, step advances, run continues.
   On denial    → step is skipped, run ends with status="error".
"""

import asyncio
import time as _time
import uuid
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.agent.demo_scripts import DEMO_SCRIPTS
from app.policy.hidden_detector import HiddenContentDetector
from app.policy.policy_engine import PolicyEngine
from app.policy.decision import PolicyDecision
from app.policy.gate import enforce_action_contract, GateRejected
from app.schemas.action_schema import AgentAction, SemanticTarget
from app.schemas.plan_schema import TaskPlan, PlannedStep
from app.tracing.tracer import tracer
from app.aws.s3_client import upload_screenshot

# Re-use the same element-targeting and execution helpers from playwright_agent
from app.agent.playwright_agent import semantic_find, _execute

# Delay between steps — purely for visible animation pacing in the UI
STEP_DELAY_S = 0.55   # 550 ms — sits comfortably between 400 and 800 ms


# ---------------------------------------------------------------------------
# Async entry point — called from main.py via asyncio.create_task()
# ---------------------------------------------------------------------------

async def run_demo_agent_async(
    queue: asyncio.Queue,
    demo_task_key: str,
    headless: bool = False,
    step_callback=None,
    trace_id: str | None = None,
):
    """Async wrapper so the sync Playwright call runs in a thread executor."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: run_demo_agent(
            queue=queue,
            loop=loop,
            demo_task_key=demo_task_key,
            headless=headless,
            step_callback=step_callback,
            trace_id=trace_id,
        ),
    )
    return result


# ---------------------------------------------------------------------------
# Sync runner — executes in a thread pool worker
# ---------------------------------------------------------------------------

def run_demo_agent(
    queue: asyncio.Queue,
    loop: asyncio.AbstractEventLoop,
    demo_task_key: str,
    headless: bool = False,
    step_callback=None,
    trace_id: str | None = None,
) -> dict:

    # ── Validate task key ────────────────────────────────────────────────────
    script = DEMO_SCRIPTS.get(demo_task_key)
    if script is None:
        raise ValueError(
            f"Unknown demo_task_key {demo_task_key!r}. "
            f"Valid keys: {list(DEMO_SCRIPTS)}"
        )

    steps      = script["steps"]
    page_uri   = script["page_uri"]
    user_task  = script["goal"]
    total      = len(steps)

    # ── _emit helper — mirrors playwright_agent._emit ────────────────────────
    def _emit(status: str, text: str, step_event: dict | None = None):
        if step_callback is not None and loop is not None:
            asyncio.run_coroutine_threadsafe(
                step_callback(status, text, step_event), loop
            )

    # ── Tracing ──────────────────────────────────────────────────────────────
    trace_seg   = tracer.start_segment(
        "demo_task", trace_id=trace_id, user_task=user_task
    )
    _task_start = _time.time()
    _success_count = 0
    _fail_count    = 0

    # ── Build a synthetic TaskPlan so step events match the real UI shape ────
    plan = TaskPlan(
        original_task=user_task,
        steps=[
            PlannedStep(
                step_number=i + 1,
                goal=s["goal"],
                action_type_hint=s["action_type"],
            )
            for i, s in enumerate(steps)
        ],
    )

    _emit("step", f"Demo mode — plan ready ({total} steps): "
          + " → ".join(s["goal"] for s in steps))

    detector = HiddenContentDetector()
    policy   = PolicyEngine()

    # Final outcome — flipped to "done" only on clean completion
    task_outcome        = "error"
    task_outcome_reason = "Demo task ended before completion."

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=0)
        page    = browser.new_page()
        page.set_viewport_size({"width": 1280, "height": 900})

        # Navigate to starting page immediately (before the step loop)
        page.goto(page_uri, timeout=15_000, wait_until="domcontentloaded")
        _emit("step", "Browser open — starting demo…")

        # ================================================================
        # Step loop
        # ================================================================
        for step_idx, step_spec in enumerate(steps):
            step_num  = step_idx + 1
            step_goal = step_spec["goal"]

            # ── Pacing delay (skip for first step — navigate is instant) ──
            if step_idx > 0:
                _time.sleep(STEP_DELAY_S)

            # ── Emit "running" into chat timeline ─────────────────────────
            step_evt_running = {
                "step_number": step_num,
                "total_steps": total,
                "goal":        step_goal,
                "outcome":     "running",
                "retry":       0,
            }
            _emit("step", f"Step {step_num}/{total}: {step_goal}", step_evt_running)

            # ── Detect hidden content on the current page ─────────────────
            hidden_result   = detector.detect(page)
            hidden_found    = hidden_result.get("hidden_found", False)
            visible_text: str = page.evaluate(
                "() => document.body.innerText || ''"
            )
            hidden_text: str = " ".join(
                el.get("text", "") or ""
                for el in hidden_result.get("elements", [])
            )

            # ── Build AgentAction from the script spec ─────────────────────
            # For navigate actions the full file:// URI goes into action.target,
            # which feeds the RiskClassifier's combined text.  A file:// URI
            # for our sandbox contains "BrowserAgentSandbox" which includes the
            # substring "browse" — that incorrectly triggers the FILE_UPLOAD
            # category.  We pass a clean label to the classifier by temporarily
            # swapping target to the bare filename during policy evaluation,
            # then restoring the real URI for _execute().
            raw_target = step_spec["target"]
            if step_spec["action_type"] == "navigate" and raw_target.startswith("file://"):
                # e.g. "file:///…/testshopping.html" → "testshopping.html"
                classifier_target = Path(raw_target.replace("file:///", "")).name
            else:
                classifier_target = raw_target

            action = AgentAction(
                action_id=str(uuid.uuid4()),
                action_type=step_spec["action_type"],
                target=raw_target,          # real URI — gate needs non-empty
                semantic_target=SemanticTarget(
                    role=step_spec.get("semantic_role", "generic"),
                    label=step_spec.get("semantic_label", ""),
                ),
                value=step_spec.get("value"),
                reasoning=step_spec["reasoning"],
                cited_source_text=step_spec["cited_source_text"],
                cited_source_location=step_spec["cited_source_location"],
                timestamp=datetime.now().isoformat(),
            )

            # ── Gate ──────────────────────────────────────────────────────
            _gate_sub = trace_seg.start_subsegment(
                "gate.enforce_action_contract", step=step_num
            )
            try:
                enforce_action_contract(action)
                trace_seg.finish_subsegment(_gate_sub)
            except GateRejected as e:
                trace_seg.finish_subsegment(_gate_sub, error=str(e))
                _emit("error", f"Gate rejected demo action at step {step_num}: {e}")
                _fail_count += 1
                task_outcome        = "error"
                task_outcome_reason = f"Gate rejected action: {e}"
                break

            # ── Policy engine ─────────────────────────────────────────────
            # Temporarily swap to the classifier-safe target (bare filename)
            # so the RiskClassifier's combined-text check doesn't see the
            # "browse" substring in the file:// URI.  Restore immediately after.
            _saved_target  = action.target
            action.target  = classifier_target
            _policy_sub = trace_seg.start_subsegment(
                "policy.evaluate", step=step_num
            )
            result = policy.evaluate(
                action,
                hidden_content_detected=hidden_found,
                user_task=user_task,
                visible_page_text=visible_text,
                hidden_page_text=hidden_text,
            )
            trace_seg.finish_subsegment(_policy_sub)
            action.target = _saved_target   # restore real URI for _execute()

            print(
                f"[demo_runner] step {step_num} "
                f"action={action.action_type} "
                f"decision={result.decision} "
                f"origin={result.origin} "
                f"hidden={hidden_found}"
            )

            # ── Push action + policy to WebSocket dashboard (ActionFeed) ──
            if queue is not None and loop is not None:
                payload = {
                    "type":       "action",
                    "session_id": trace_id,
                    "action":     action.model_dump(mode="json"),
                    "policy":     result.model_dump(mode="json"),
                }
                asyncio.run_coroutine_threadsafe(queue.put(payload), loop)

            # ── Emit policy decision into chat status line ─────────────────
            if result.decision != PolicyDecision.ALLOW:
                _emit(
                    "step",
                    f"Policy: {result.decision.value} — {result.reason}",
                )

            # ── Execute / escalate / deny ─────────────────────────────────
            if result.decision == PolicyDecision.ALLOW:
                _exec_sub = trace_seg.start_subsegment(
                    "browser.execute_action", step=step_num,
                    action_type=action.action_type,
                )
                try:
                    if action.action_type != "done":
                        _execute(page, action)
                    trace_seg.finish_subsegment(_exec_sub)
                    _success_count += 1
                    _emit(
                        "step",
                        f"✓ Step {step_num}/{total}: {step_goal}",
                        {
                            "step_number": step_num,
                            "total_steps": total,
                            "goal":        step_goal,
                            "outcome":     "success",
                            "retry":       0,
                        },
                    )
                except Exception as exc:
                    trace_seg.finish_subsegment(_exec_sub, error=str(exc))
                    _fail_count += 1
                    _emit(
                        "step",
                        f"✗ Step {step_num} execution failed: {exc}",
                        {
                            "step_number": step_num,
                            "total_steps": total,
                            "goal":        step_goal,
                            "outcome":     "failed",
                            "retry":       0,
                        },
                    )
                    task_outcome        = "error"
                    task_outcome_reason = f"Step {step_num} execution failed: {exc}"
                    break

            elif result.decision == PolicyDecision.ESCALATE:
                # ── Human approval gate ────────────────────────────────────
                from app.agent.escalation_state import pending_escalations

                pending_escalations[action.action_id] = "pending"

                _emit(
                    "step",
                    (
                        f"⏸ Step {step_num} escalated — awaiting human approval. "
                        f"Reason: {result.reason}"
                    ),
                    {
                        "step_number": step_num,
                        "total_steps": total,
                        "goal":        step_goal,
                        "outcome":     "paused",
                        "retry":       0,
                    },
                )
                print(
                    f"[demo_runner] waiting for human approval on {action.action_id}"
                )

                # Poll until the human resolves the escalation
                waited_ms   = 0
                timeout_ms  = 10 * 60 * 1000  # 10 minute safety ceiling
                while (
                    pending_escalations.get(action.action_id) == "pending"
                    and waited_ms < timeout_ms
                ):
                    page.wait_for_timeout(1000)
                    waited_ms += 1000

                decision_ui = pending_escalations.pop(action.action_id, "denied")

                if decision_ui == "approved":
                    _emit(
                        "step",
                        f"▶ Human approved step {step_num} — executing…",
                        {
                            "step_number": step_num,
                            "total_steps": total,
                            "goal":        step_goal,
                            "outcome":     "running",
                            "retry":       0,
                        },
                    )
                    _exec_sub = trace_seg.start_subsegment(
                        "browser.execute_action.approved", step=step_num,
                        action_type=action.action_type,
                    )
                    try:
                        if action.action_type != "done":
                            _execute(page, action)
                        trace_seg.finish_subsegment(_exec_sub)
                        _success_count += 1
                        _emit(
                            "step",
                            f"✓ Step {step_num}/{total}: {step_goal}",
                            {
                                "step_number": step_num,
                                "total_steps": total,
                                "goal":        step_goal,
                                "outcome":     "success",
                                "retry":       0,
                            },
                        )
                    except Exception as exc:
                        trace_seg.finish_subsegment(_exec_sub, error=str(exc))
                        _fail_count += 1
                        _emit(
                            "step",
                            f"✗ Step {step_num} failed after approval: {exc}",
                            {
                                "step_number": step_num,
                                "total_steps": total,
                                "goal":        step_goal,
                                "outcome":     "failed",
                                "retry":       0,
                            },
                        )
                        task_outcome        = "error"
                        task_outcome_reason = (
                            f"Step {step_num} failed after human approval: {exc}"
                        )
                        break
                else:
                    # Human denied — skip this step and stop the run
                    _emit(
                        "step",
                        f"✗ Human denied step {step_num} — task stopped.",
                        {
                            "step_number": step_num,
                            "total_steps": total,
                            "goal":        step_goal,
                            "outcome":     "skipped",
                            "retry":       0,
                        },
                    )
                    _fail_count += 1
                    task_outcome        = "error"
                    task_outcome_reason = (
                        f"Human denied escalated action at step {step_num}."
                    )
                    break

            else:  # DENY
                _emit(
                    "step",
                    f"✗ Step {step_num} blocked by policy: {result.reason}",
                    {
                        "step_number": step_num,
                        "total_steps": total,
                        "goal":        step_goal,
                        "outcome":     "failed",
                        "retry":       0,
                    },
                )
                _fail_count += 1
                task_outcome        = "error"
                task_outcome_reason = f"Blocked by policy: {result.reason}"
                break

        else:
            # for…else fires when the loop completed without a break
            task_outcome        = "done"
            task_outcome_reason = None

        # ── Screenshot ───────────────────────────────────────────────────────
        page.wait_for_timeout(1000)
        try:
            screenshot_dir = (
                Path(__file__).resolve().parents[3]
                / "backend" / "logs" / "screenshots"
            )
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            screenshot_path = screenshot_dir / f"{trace_seg.trace_id}.png"
            page.screenshot(path=str(screenshot_path))
            screenshot_url = upload_screenshot(
                str(screenshot_path), key=f"{trace_seg.trace_id}.png"
            )
            trace_seg.set_metadata(screenshot_url=screenshot_url)
        except Exception as exc:
            print(f"[demo_runner] screenshot/upload skipped: {exc}")

        browser.close()

    # ── Close trace ──────────────────────────────────────────────────────────
    trace_seg.set_metadata(
        success_count=_success_count,
        fail_count=_fail_count,
        elapsed_seconds=round(_time.time() - _task_start, 2),
        demo_task_key=demo_task_key,
    )
    tracer.finish_segment(trace_seg)

    return {
        "status":          task_outcome,
        "reason":          task_outcome_reason,
        "trace_id":        trace_seg.trace_id,
        "success_count":   _success_count,
        "fail_count":      _fail_count,
        "elapsed_seconds": round(_time.time() - _task_start, 2),
    }
