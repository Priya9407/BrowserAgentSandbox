# Demo Script — Locked Order (Milestone 3, Item D)

> Lock the final 3–4 live demo tasks, in order, timed. Lead with something
> simple and reliable, end with the most impressive one. Record the backup
> demo video against this exact script — not on the last day.

Built from the tasks already proven out in `real_site_punch_list.md` and
wired as one-click chips in the chat UI (`DEMO_TASKS` in `ChatPanel.jsx`).

---

## Locked run order

| # | Task | Why this position | Target time |
|---|------|--------------------|-------------|
| 1 | **Product price lookup** — "Search for the Sony WH-1000XM5 headphones and tell me the current price" | Simple, single-fact, visibly reliable. Opens the demo with a clean win. | ~20–30s |
| 2 | **Restaurant hours** — "Look up the opening hours of Domino's Pizza in Bangalore and report them" | Different site shape (local business listing), shows generality. | ~20–30s |
| 3 | **Flight search** — "Find the cheapest one-way flight from Delhi to Goa next week and report the price and airline" | Multi-step, more complex targeting (date pickers, dynamic aria-labels) — shows off the recovery loop if it stumbles. | ~40–60s |
| 4 | **Multi-site price comparison** (finale) — "Compare the price of the Sony WH-1000XM5 across Amazon India and Flipkart and tell me which is cheaper" | Most impressive: multi-step, multi-navigation, judgement call at the end. Closes strong. | ~60–90s |

**Total run time target: ~3–4 minutes.**

---

## Before every rehearsal run

- [ ] Backend running (`uvicorn app.main:app --reload`), confirm `GET /` returns `{"status": "running"}`
- [ ] Frontend running (`npm run dev`), WebSocket badge shows **Connected**
- [ ] `.env` has a valid `NVIDIA_API_KEY`
- [ ] Chat cleared (`Clear` button) before each task

## Sync checkpoint

- [ ] Full run-through done by **everyone on the team**, not just whoever built each task
- [ ] All 4 tasks complete without a hard `DENY` or unhandled error
- [ ] Backup demo video recorded against this exact script, saved somewhere the whole team can access it before the last day

## If a task breaks mid-rehearsal

Don't improvise a new demo task under time pressure. Either:
1. Fix the specific selector/plan issue (see `real_site_punch_list.md` → Section A/B for known fragile patterns), or
2. Swap in the next-most-reliable task from the punch list's test matrix, keeping the same 4-task shape (simple → simple → complex → showcase).
