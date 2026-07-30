"""
real_site_tester.py 
=====================================
Runs the 3–4 demo tasks against 5–6 real sites each, instruments the
semantic_find resolution path, and writes two output files:

  logs/real_site_results.json   — structured per-step records
  logs/real_site_punch_list.md  — human-readable failure analysis

Usage (from the backend/ directory, with venv active):
  python real_site_tester.py [--headless] [--max-steps 8] [--timeout 20]

All arguments are optional; the script runs headless by default.

WHAT IT INSTRUMENTS
--------------------
For every browser action the agent attempts, it records:
  - which semantic_find strategy resolved the element (or failed)
  - whether execution succeeded, retried, or was skipped
  - the raw CSS selector the LLM returned (for comparing to what actually worked)
  - page URL at time of action

The punch list groups findings into:
  A — selector / targeting failures  (feeds Task A improvements)
  B — recovery events                (feeds Task B tuning)
  C — plan quality issues            (feeds planner prompt tuning)
"""

import argparse
import asyncio
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable

# ── Path setup ────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeout
from app.agent.agent import BrowserAgent, MAX_STEP_RETRIES
from app.agent.planner import generate_plan
from app.agent.llm import ask_vision_for_element, replan_after_failure
from app.agent.playwright_agent import _execute
from app.policy.hidden_detector import HiddenContentDetector
from app.policy.policy_engine import PolicyEngine
from app.policy.decision import PolicyDecision
from app.policy.gate import enforce_action_contract, GateRejected
from app.schemas.action_schema import AgentAction


# ── Demo tasks × real sites ───────────────────────────────────────────────
#
# Each task is run against 1–2 primary URLs and 3–5 alternate real sites
# that exercise the same intent (price lookup / flight search / hours lookup).
# This is the "5–6 real sites each" coverage the spec asks for.

TASKS = [
    {
        "id": "price_lookup",
        "goal": "Search for the Sony WH-1000XM5 headphones and tell me the current price",
        "sites": [
            {"name": "Google Search",    "url": "https://www.google.com/search?q=Sony+WH-1000XM5+price"},
            {"name": "Bing Search",      "url": "https://www.bing.com/search?q=Sony+WH-1000XM5+price"},
            {"name": "Amazon India",     "url": "https://www.amazon.in/s?k=Sony+WH-1000XM5"},
            {"name": "Flipkart",         "url": "https://www.flipkart.com/search?q=Sony+WH-1000XM5"},
            {"name": "Sony Official",    "url": "https://www.sony.co.in/en/products/wh-1000xm5"},
            {"name": "Croma",            "url": "https://www.croma.com/searchB?q=Sony+WH-1000XM5"},
        ],
    },
    {
        "id": "flight_search",
        "goal": "Find the cheapest one-way flight from Delhi to Goa next week and report the price and airline",
        "sites": [
            {"name": "Google Flights",   "url": "https://www.google.com/travel/flights/search?tfs=CBwQAhoeEgoyMDI1LTA4LTA0agwIAhIIL20vMDlmMDcaHRIKMjAyNS0wOC0wNHIMCAISCC9tLzAxZmRteA"},
            {"name": "MakeMyTrip",       "url": "https://www.makemytrip.com/flights/oneway-delhi-to-goa"},
            {"name": "Cleartrip",        "url": "https://www.cleartrip.com/flights/results?from=DEL&to=GOI&depart_date=2025-08-06&adults=1"},
            {"name": "EaseMyTrip",       "url": "https://www.easemytrip.com/flights/delhi-to-goa-flights.html"},
            {"name": "Ixigo",            "url": "https://www.ixigo.com/search/result/flight?from=DEL&to=GOI&date=20250806&adults=1"},
        ],
    },
    {
        "id": "restaurant_hours",
        "goal": "Look up the opening hours of Domino's Pizza in Bangalore and report them",
        "sites": [
            {"name": "Google Search",    "url": "https://www.google.com/search?q=Dominos+Pizza+Bangalore+opening+hours"},
            {"name": "Zomato",           "url": "https://www.zomato.com/bangalore/dominos-pizza-restaurants"},
            {"name": "Swiggy",           "url": "https://www.swiggy.com/city/bangalore/dominos-pizza-rests"},
            {"name": "Dominos Official", "url": "https://www.dominos.co.in/store-finder"},
            {"name": "JustDial",         "url": "https://www.justdial.com/Bangalore/Dominos-Pizza/nct-10040462"},
            {"name": "Yelp India",       "url": "https://www.yelp.com/search?find_desc=Dominos+Pizza&find_loc=Bangalore"},
        ],
    },
    {
        "id": "buy_laptop_local",
        "goal": "Find the cheapest laptop on this page and add it to the cart",
        "sites": [
            # Local test page — always works, used as baseline
            {"name": "Local benign_checkout", "url": (ROOT.parent / "test-pages" / "benign_checkout.html").as_uri()},
        ],
    },
]


# ── Instrumented semantic_find ─────────────────────────────────────────────

STRATEGIES = [
    "role+name",
    "role_only",
    "text",
    "placeholder",
    "css",
    "vision",
]


def instrumented_semantic_find(page: Page, action: AgentAction, timeout_ms: int = 4000) -> tuple:
    """
    Mirrors playwright_agent.semantic_find() but returns (locator, strategy_name)
    so the test harness can log which strategy resolved the element.
    Raises RuntimeError if nothing works (same as the production version).
    """
    from app.agent.playwright_agent import _ROLE_ALIASES

    sem = action.semantic_target
    role = _ROLE_ALIASES.get(sem.role.lower()) if sem.role else None
    label = (sem.label or "").strip()

    # Strategy 1: role + name
    if role and label:
        try:
            loc = page.get_by_role(role, name=label)
            loc.wait_for(state="visible", timeout=timeout_ms)
            return loc, "role+name"
        except Exception:
            pass

    # Strategy 2: role only
    if role:
        try:
            loc = page.get_by_role(role).first
            loc.wait_for(state="visible", timeout=timeout_ms)
            return loc, "role_only"
        except Exception:
            pass

    # Strategy 3: text
    if label:
        try:
            loc = page.get_by_text(label, exact=False).first
            loc.wait_for(state="visible", timeout=timeout_ms)
            return loc, "text"
        except Exception:
            pass

    # Strategy 4: placeholder
    if label:
        try:
            loc = page.get_by_placeholder(label, exact=False)
            loc.wait_for(state="visible", timeout=timeout_ms)
            return loc, "placeholder"
        except Exception:
            pass

    # Strategy 5: CSS
    css = (action.target or "").strip()
    if css:
        try:
            loc = page.locator(css)
            loc.wait_for(state="visible", timeout=timeout_ms)
            return loc, "css"
        except Exception:
            pass

    # Strategy 6: vision
    description = label or action.reasoning[:80]
    vision_selector = ask_vision_for_element(page, description)
    if vision_selector:
        try:
            loc = page.locator(vision_selector)
            loc.wait_for(state="visible", timeout=timeout_ms)
            return loc, "vision"
        except Exception:
            pass

    raise RuntimeError(
        f"All strategies failed — role={sem.role!r}, label={label!r}, CSS={css!r}"
    )


# ── Single site runner ─────────────────────────────────────────────────────

def run_single_site(
    task_id: str,
    goal: str,
    site_name: str,
    url: str,
    headless: bool = True,
    max_steps: int = 10,
    nav_timeout: int = 20,
) -> dict:
    """
    Run one task against one site. Returns a structured result dict.
    """
    result = {
        "task_id":    task_id,
        "site_name":  site_name,
        "url":        url,
        "timestamp":  datetime.now().isoformat(),
        "plan":       [],
        "steps":      [],          # per-action records
        "outcome":    "unknown",   # "success" | "partial" | "failed" | "error"
        "error":      None,
        "notes":      [],
    }

    def note(msg: str):
        result["notes"].append(msg)
        print(f"    [{site_name}] {msg}")

    try:
        # ── Planning ────────────────────────────────────────────────────
        note("Generating plan…")
        plan = generate_plan(goal)
        result["plan"] = [s.model_dump() for s in plan.steps]
        if not plan.steps:
            result["outcome"] = "failed"
            result["error"] = "Planner returned 0 steps"
            note("FAIL — planner returned no steps")
            return result
        note(f"Plan: {' → '.join(s.goal for s in plan.steps)}")

        browser_agent = BrowserAgent()
        browser_agent.set_task(goal)
        browser_agent.set_plan(plan)

        detector  = HiddenContentDetector()
        policy    = PolicyEngine()
        completed_steps: list[dict] = []
        step_records: list[dict] = []
        replanned = False

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless, slow_mo=200)
            page    = browser.new_page()
            page.set_viewport_size({"width": 1280, "height": 900})

            try:
                page.goto(url, timeout=nav_timeout * 1000, wait_until="domcontentloaded")
            except PlaywrightTimeout:
                result["outcome"] = "error"
                result["error"]   = f"Page navigation timed out after {nav_timeout}s"
                note(f"TIMEOUT navigating to {url}")
                browser.close()
                return result

            note("Browser open — executing…")

            while not browser_agent.is_done():
                total    = len(browser_agent.plan.steps) if browser_agent.plan and browser_agent.plan.steps else 0
                step_idx = browser_agent.current_step_index

                # Detect hidden content + get DOM
                hidden     = detector.detect(page)
                visible_txt = page.evaluate("() => document.body.innerText || ''")
                hidden_txt  = " ".join(el.get("text", "") or "" for el in hidden.get("elements", []))
                dom         = page.content()

                # Think
                action = browser_agent.think(dom)

                step_rec = {
                    "step_idx":         step_idx,
                    "step_goal":        browser_agent.current_step_goal,
                    "action_type":      action.action_type,
                    "css_target":       action.target,
                    "semantic_role":    action.semantic_target.role,
                    "semantic_label":   action.semantic_target.label,
                    "resolution":       None,   # filled below
                    "outcome":          None,
                    "retry":            0,
                    "failure_reason":   None,
                    "page_url":         page.url,
                    "replanned":        replanned,
                }
                replanned = False

                if action.action_type == "done":
                    step_rec["outcome"] = "done_signal"
                    step_records.append(step_rec)
                    if browser_agent.plan and not browser_agent.is_last_step():
                        completed_steps.append({"goal": browser_agent.current_step_goal})
                        browser_agent.record_step_success()
                        browser_agent.advance_step()
                        continue
                    else:
                        break

                # Gate
                try:
                    enforce_action_contract(action)
                except GateRejected as e:
                    step_rec["outcome"] = "gate_rejected"
                    step_rec["failure_reason"] = str(e)
                    step_records.append(step_rec)
                    note(f"Gate rejected: {e}")
                    break

                # Policy
                pol_result = policy.evaluate(
                    action,
                    hidden_content_detected=hidden["hidden_found"],
                    user_task=browser_agent.user_task,
                    visible_page_text=visible_txt,
                    hidden_page_text=hidden_txt,
                )

                if pol_result.decision == PolicyDecision.DENY:
                    step_rec["outcome"] = "policy_denied"
                    step_rec["failure_reason"] = pol_result.reason
                    step_records.append(step_rec)
                    note(f"Policy DENY: {pol_result.reason[:80]}")
                    break

                if pol_result.decision == PolicyDecision.ESCALATE:
                    # In test mode auto-approve escalations
                    note(f"Policy ESCALATE (auto-approving): {pol_result.reason[:60]}")

                # ── Execute with instrumented semantic_find ────────────
                attempt = 0
                exec_ok = False
                exec_error = None

                while attempt <= MAX_STEP_RETRIES:
                    try:
                        if action.action_type == "navigate":
                            page.goto(action.target, timeout=nav_timeout * 1000, wait_until="domcontentloaded")
                            step_rec["resolution"] = "navigate"
                            exec_ok = True
                            break
                        elif action.action_type == "scroll":
                            page.evaluate("window.scrollBy(0, 400)")
                            step_rec["resolution"] = "scroll"
                            exec_ok = True
                            break
                        else:
                            loc, strategy = instrumented_semantic_find(page, action)
                            step_rec["resolution"] = strategy

                            if action.action_type == "click":
                                loc.click(timeout=5000)
                            elif action.action_type in ("fill", "type"):
                                loc.fill(action.value or "", timeout=5000)

                            exec_ok = True
                            break

                    except Exception as e:
                        exec_error = str(e)
                        attempt += 1
                        step_rec["retry"] = attempt
                        if attempt <= MAX_STEP_RETRIES:
                            note(f"  ↻ Retry {attempt} — {exec_error[:60]}")
                            page.wait_for_timeout(600)

                if exec_ok:
                    step_rec["outcome"] = "success"
                    browser_agent.record_step_success()
                else:
                    # Re-plan
                    step_rec["outcome"] = "failed"
                    step_rec["failure_reason"] = exec_error
                    note(f"  Step failed after {attempt} attempt(s): {exec_error[:80]}")
                    note("  Requesting re-plan…")

                    new_plan = replan_after_failure(
                        original_task=goal,
                        completed_steps=completed_steps,
                        failed_step={"goal": browser_agent.current_step_goal},
                        failure_reason=exec_error or "unknown",
                        dom=page.content(),
                    )

                    if new_plan.steps:
                        browser_agent.replace_remaining_plan(new_plan)
                        result["plan"].extend(s.model_dump() for s in new_plan.steps)
                        note(f"  New plan: {' → '.join(s.goal for s in new_plan.steps)}")
                        replanned = True
                    else:
                        note("  Re-plan returned empty — skipping step")
                        browser_agent.advance_step()

                step_records.append(step_rec)

            page.wait_for_timeout(1000)
            browser.close()

        # ── Compute overall outcome ──────────────────────────────────────
        result["steps"] = step_records
        success_count = sum(1 for s in step_records if s["outcome"] == "success")
        fail_count    = sum(1 for s in step_records if s["outcome"] == "failed")
        done_count    = sum(1 for s in step_records if s["outcome"] == "done_signal")

        if fail_count == 0 and (success_count > 0 or done_count > 0):
            result["outcome"] = "success"
        elif success_count > 0 and fail_count > 0:
            result["outcome"] = "partial"
        elif fail_count > 0:
            result["outcome"] = "failed"
        else:
            result["outcome"] = "unknown"

        note(f"Done — outcome={result['outcome']} "
             f"success={success_count} failed={fail_count} done={done_count}")

    except Exception as e:
        result["outcome"] = "error"
        result["error"] = traceback.format_exc()
        print(f"    [{site_name}] EXCEPTION: {e}")

    return result


# ── Punch list generator ───────────────────────────────────────────────────

def build_punch_list(all_results: list[dict]) -> str:
    lines = [
        "# Real-Site Test Punch List",
        f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "\n---\n",
        "## Summary\n",
    ]

    # Outcome table
    lines.append("| Task | Site | Outcome | Steps OK | Steps Failed | Re-plans |")
    lines.append("|------|------|---------|----------|--------------|----------|")
    for r in all_results:
        steps_ok  = sum(1 for s in r["steps"] if s["outcome"] == "success")
        steps_fail = sum(1 for s in r["steps"] if s["outcome"] == "failed")
        replans   = sum(1 for s in r["steps"] if s.get("replanned"))
        lines.append(
            f"| {r['task_id']} | {r['site_name']} | **{r['outcome']}** "
            f"| {steps_ok} | {steps_fail} | {replans} |"
        )

    # ── Section A: selector / targeting failures ────────────────────────
    lines.append("\n---\n## A — Selector / Targeting Failures\n")
    lines.append("_Steps where CSS selector failed and semantic/vision was needed, or all strategies failed._\n")

    a_items = []
    for r in all_results:
        for s in r["steps"]:
            if s["outcome"] == "failed" or (
                s.get("resolution") and s["resolution"] not in ("navigate", "scroll", "css", "role+name")
            ):
                a_items.append(
                    f"- **{r['task_id']} / {r['site_name']}** — "
                    f"step {s['step_idx'] + 1} `{s['action_type']}`: "
                    f"CSS=`{s['css_target'][:60]}`, "
                    f"semantic=`{s['semantic_role']}:{s['semantic_label'][:40]}`, "
                    f"resolved_via=`{s['resolution'] or 'NONE'}` "
                    f"| outcome={s['outcome']}"
                    + (f" | reason: {s['failure_reason'][:80]}" if s.get("failure_reason") else "")
                )

    if a_items:
        lines.extend(a_items)
    else:
        lines.append("_No targeting failures recorded._")

    # ── Section B: recovery events ──────────────────────────────────────
    lines.append("\n---\n## B — Recovery Events\n")
    lines.append("_Steps that triggered a retry or re-plan._\n")

    b_items = []
    for r in all_results:
        for s in r["steps"]:
            if s.get("retry", 0) > 0 or s.get("replanned"):
                b_items.append(
                    f"- **{r['task_id']} / {r['site_name']}** — "
                    f"step {s['step_idx'] + 1}: "
                    f"retry={s.get('retry', 0)}, "
                    f"replanned={s.get('replanned', False)}, "
                    f"outcome={s['outcome']}"
                    + (f" | {s['failure_reason'][:80]}" if s.get("failure_reason") else "")
                )

    if b_items:
        lines.extend(b_items)
    else:
        lines.append("_No recovery events recorded._")

    # ── Section C: plan quality issues ──────────────────────────────────
    lines.append("\n---\n## C — Plan Quality Issues\n")
    lines.append("_Tasks where the plan had 0 steps, or a done signal appeared on step 1._\n")

    c_items = []
    for r in all_results:
        if not r["plan"]:
            c_items.append(f"- **{r['task_id']} / {r['site_name']}**: Planner returned 0 steps")
        early_done = [s for s in r["steps"] if s["outcome"] == "done_signal" and s["step_idx"] == 0]
        if early_done:
            c_items.append(
                f"- **{r['task_id']} / {r['site_name']}**: "
                f"LLM returned `done` on step 1 without taking any action"
            )

    if c_items:
        lines.extend(c_items)
    else:
        lines.append("_No plan quality issues recorded._")

    # ── Section D: resolution strategy breakdown ─────────────────────────
    lines.append("\n---\n## D — Resolution Strategy Breakdown\n")
    lines.append("_How elements were found across all successful actions._\n")

    from collections import Counter
    strategy_counts: Counter = Counter()
    for r in all_results:
        for s in r["steps"]:
            if s.get("resolution"):
                strategy_counts[s["resolution"]] += 1

    if strategy_counts:
        lines.append("| Strategy | Count |")
        lines.append("|----------|-------|")
        for strat, count in strategy_counts.most_common():
            lines.append(f"| `{strat}` | {count} |")
    else:
        lines.append("_No resolution data recorded._")

    # ── Commit decisions ────────────────────────────────────────────────
    lines.append("\n---\n## Sync Checkpoint\n")
    lines.append("### Retry/re-plan contract\n")
    lines.append(
        "- `MAX_STEP_RETRIES = 1`: one immediate retry on execution failure.\n"
        "- On retry exhaustion: `replan_after_failure()` is called with full context "
        "(original task, completed steps, failed step goal, failure reason, current DOM).\n"
        "- If re-plan returns steps: the agent swaps in the new plan and continues.\n"
        "- If re-plan returns 0 steps: the step is skipped with an honest failure message "
        "and the agent advances to the next step.\n"
    )
    lines.append("### Demo tasks reliable for pitch\n")

    reliable = [r for r in all_results if r["outcome"] == "success"]
    partial  = [r for r in all_results if r["outcome"] == "partial"]

    if reliable:
        lines.append("**Fully reliable (commit to pitch):**")
        for r in reliable:
            lines.append(f"- {r['task_id']} on {r['site_name']}")
    if partial:
        lines.append("\n**Partially reliable (use with caveats):**")
        for r in partial:
            lines.append(f"- {r['task_id']} on {r['site_name']}")

    failed = [r for r in all_results if r["outcome"] in ("failed", "error")]
    if failed:
        lines.append("\n**Not reliable (do not demo):**")
        for r in failed:
            err = r.get("error") or ""
            lines.append(f"- {r['task_id']} on {r['site_name']}"
                         + (f": {err[:60]}" if err else ""))

    return "\n".join(lines)


# ── Entry point ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="real-site test harness")
    parser.add_argument("--headless",   action="store_true", default=True,
                        help="Run browser headlessly (default: True)")
    parser.add_argument("--no-headless", dest="headless", action="store_false",
                        help="Show browser windows")
    parser.add_argument("--max-steps",  type=int, default=10)
    parser.add_argument("--timeout",    type=int, default=20,
                        help="Page navigation timeout in seconds")
    parser.add_argument("--task",       type=str, default=None,
                        help="Run only this task_id (e.g. price_lookup)")
    parser.add_argument("--site",       type=str, default=None,
                        help="Run only sites whose name contains this string")
    args = parser.parse_args()

    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)

    all_results: list[dict] = []

    tasks_to_run = [t for t in TASKS if args.task is None or t["id"] == args.task]

    for task in tasks_to_run:
        sites_to_run = [
            s for s in task["sites"]
            if args.site is None or args.site.lower() in s["name"].lower()
        ]

        print(f"\n{'='*60}")
        print(f"TASK: {task['id']}")
        print(f"GOAL: {task['goal']}")
        print(f"Sites: {[s['name'] for s in sites_to_run]}")
        print(f"{'='*60}")

        for site in sites_to_run:
            print(f"\n  → {site['name']} ({site['url'][:60]}…)")
            r = run_single_site(
                task_id=task["id"],
                goal=task["goal"],
                site_name=site["name"],
                url=site["url"],
                headless=args.headless,
                max_steps=args.max_steps,
                nav_timeout=args.timeout,
            )
            all_results.append(r)

    # ── Write outputs ─────────────────────────────────────────────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = log_dir / f"real_site_results_{ts}.json"
    json_path.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\n✓ JSON results → {json_path}")

    # Also write a "latest" symlink-equivalent (plain copy for Windows)
    latest_json = log_dir / "real_site_results_latest.json"
    latest_json.write_text(json.dumps(all_results, indent=2, default=str))

    punch_list_md = build_punch_list(all_results)
    punch_path = ROOT.parent / "real_site_punch_list.md"
    punch_path.write_text(punch_list_md)
    print(f"✓ Punch list  → {punch_path}")

    # Print summary to console
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    for r in all_results:
        steps_ok   = sum(1 for s in r["steps"] if s["outcome"] == "success")
        steps_fail = sum(1 for s in r["steps"] if s["outcome"] == "failed")
        print(
            f"  {r['task_id']:<20} {r['site_name']:<25} "
            f"{'✓' if r['outcome']=='success' else '~' if r['outcome']=='partial' else '✗'} "
            f"{r['outcome']:<8}  ok={steps_ok} fail={steps_fail}"
        )


if __name__ == "__main__":
    main()
