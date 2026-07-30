# Real-Site Test Punch List 

> **Run `python real_site_tester.py` from `backend/` to regenerate this file with live data.**
> This pre-seeded version documents the test methodology and known risk categories.

Generated: 2025-07-29 (pre-run)

---

## Test Matrix

| Task | # Sites | Sites |
|------|---------|-------|
| `price_lookup` | 6 | Google Search, Bing, Amazon India, Flipkart, Sony Official, Croma |
| `flight_search` | 5 | Google Flights, MakeMyTrip, Cleartrip, EaseMyTrip, Ixigo |
| `restaurant_hours` | 6 | Google Search, Zomato, Swiggy, Dominos Official, JustDial, Yelp |
| `buy_laptop_local` | 1 | Local benign_checkout (baseline) |

**Total combinations: 18**

---

## A — Selector / Targeting Failures

_Populated by live run. Pre-seeded with known risk categories from design._

### Known fragile patterns (identified during Milestone 2 design)

- **Dynamic class names** (React/Angular SPAs): Amazon, Flipkart, MakeMyTrip use
  generated class names like `_2B099` — CSS selector will always fail here.
  Mitigation: semantic_find() role+name or text strategy should catch these.

- **Shadow DOM** (Croma, Swiggy): Some components use shadow roots; Playwright's
  `get_by_role` pierces shadow DOM by default, but `page.locator(css)` does not.
  Mitigation: role+name strategy resolves through shadow DOM automatically.

- **CAPTCHA / consent banners** (Google, Bing): A consent overlay may cover the
  search box on first visit; the agent may time out on `wait_for(visible)`.
  Mitigation: vision fallback gets a screenshot and can identify the dismiss button.

- **Infinite scroll / lazy loading** (Flipkart product grid): Items load on scroll;
  the LLM may return a selector for an element not yet in the DOM.
  Mitigation: retry loop gives the page an 800 ms settle before retry.

- **Obfuscated ARIA** (flight aggregators): MakeMyTrip and Ixigo use `aria-label`
  with dynamic route strings ("Delhi → Goa – ₹3,499"); label matching on partial
  text via `exact=False` is required.

---

## B — Recovery Events

_Populated by live run._

### Expected recovery scenarios

| Site | Expected failure | Expected recovery |
|------|-----------------|-------------------|
| Amazon India | CSS selector for product card | Retry via `role+name` ("Add to Cart button") |
| Google Flights | Consent banner blocks search box | Vision fallback identifies "I agree" button |
| MakeMyTrip | Date picker overlay covers input | Re-plan: navigate directly to results URL |
| Flipkart | Login wall interrupts add-to-cart | Honest skip + "couldn't complete: login required" |

### Retry/re-plan contract (locked)

```
Failure → retry once (800 ms settle) → replan_after_failure() with:
  { original_task, completed_steps[], failed_step{goal}, failure_reason, dom[:3000] }
→ new plan replaces remaining steps
→ if new plan is empty → skip step, advance, emit "couldn't complete: {reason}"
```

**MAX_STEP_RETRIES = 1** — tunable in `backend/app/agent/agent.py`.

---

## C — Plan Quality Issues

_Populated by live run._

### Known risk: premature `done` on information-rich pages

The LLM sometimes returns `action_type = "done"` on step 1 when the target
information (e.g., price, hours) is already visible in the initial page DOM
passed to the planner. This is technically correct behaviour but skips
navigation steps that would get more accurate/current data.

**Mitigation**: The planner prompt now explicitly says "return done only when
the CURRENT STEP is satisfied", not when any prior information is visible.

---

## D — Resolution Strategy Breakdown

_Populated by live run._

### Expected distribution (hypothesis before live run)

| Strategy | Expected % | Reason |
|----------|-----------|--------|
| `role+name` | ~45% | Most accessible pages (Google, Amazon) have correct ARIA |
| `css` | ~20% | Local test pages and simple CMS sites |
| `text` | ~20% | Sites with good visible text but weak ARIA |
| `role_only` | ~10% | Sites where label matching fails due to dynamic text |
| `placeholder` | ~3% | Form inputs with placeholder but no aria-label |
| `vision` | ~2% | Complete fallback on heavily obfuscated UIs |
| `navigate`/`scroll` | counted separately | |

---

## Sync Checkpoint

### Retry/re-plan contract — LOCKED

- `MAX_STEP_RETRIES = 1` in `agent.py`
- retry waits 800 ms for page to settle
- re-plan gets: `original_task`, `completed_steps[]`, `failed_step.goal`, `failure_reason`, `dom[:3000]`
- new plan replaces remaining steps; step counter resets to 0 on new plan
- empty re-plan → skip + advance + honest message

### Demo tasks reliable enough to commit to pitch

Run `python real_site_tester.py` and check the **Sync Checkpoint → Demo tasks reliable for pitch**
section that gets written here automatically.

---

## How to run

```bash
cd backend/

# Full run (headless, all tasks × all sites)
python real_site_tester.py

# Show browsers (useful for debugging)
python real_site_tester.py --no-headless

# Single task only
python real_site_tester.py --task price_lookup

# Single task, single site
python real_site_tester.py --task price_lookup --site Google

# Increase step budget or navigation timeout (ms)
python real_site_tester.py --max-steps 15 --timeout 30
```

Results are written to:
- `backend/logs/real_site_results_<timestamp>.json` — full structured log
- `backend/logs/real_site_results_latest.json` — always the most recent run
- `real_site_punch_list.md` — this file (overwritten on each run)
