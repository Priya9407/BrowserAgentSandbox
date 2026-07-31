# BrowserAgentSandbox — Submission README

> Polished README prepared for shortlisting submission. Includes architecture guidance, demo video placeholder, and step-by-step run instructions.

## Quick summary

BrowserAgentSandbox is a research-grade secure browser automation agent that executes multi-step user tasks in a sandboxed browser. The system combines a FastAPI backend, a React frontend, Playwright-based browser automation, and LLM grounding for action selection and vision fallbacks. This README is intended for reviewers and the demo submission.

## Highlights

- Secure multi-step web automation with semantic and vision-based element targeting.
- Chat-driven and existing run-agent HTTP endpoints (see backend/app/main.py).
- Test pages included for safety and evaluation: [test-pages](/C:/Users/archi/BrowserAgentSandbox/test-pages)
- Automated demos and test runners under `backend/`.

## Architecture (place diagram here)

Add an architecture diagram image at `docs/architecture.png` in the repo. Example markdown to embed after adding the file:

![Architecture diagram](docs/architecture.png)

Suggested diagram elements:
- Frontend (React/Vite) — user chat UI and action feed
- Backend (FastAPI + uvicorn) — chat endpoints, websocket, demo runner
- Agent components — planner, llm grounding, policy engine, playwright executor
- External services — LLM provider (NVIDIA/OpenAI), S3 for screenshots (optional)


## Running the system (developer-friendly)

Prerequisites:
- Python 3.10+ (or 3.11)
- Node 18+
- Git

Backend steps (from repository root):

1. Create and activate a virtual environment

```bash
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1   # PowerShell on Windows
# or .\\.venv\\Scripts\\activate  for cmd
```

2. Install Python dependencies (recommended)

# If you maintain a requirements file, run:
# pip install -r backend/requirements.txt

A minimal suggested install:

```bash
pip install fastapi uvicorn python-dotenv playwright pydantic openai pytest
python -m playwright install
```

3. Run the backend API (from `backend/`):

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

4. Run tests / demo scripts

```bash
# example test script
python run_tests.py
```


Frontend steps (from repository root):

```bash
cd frontend
npm install
npm run dev
# open http://localhost:5173
```

Files of interest:
- [backend/app/main.py](/C:/Users/archi/BrowserAgentSandbox/backend/app/main.py)
- [frontend/src/main.jsx](/C:/Users/archi/BrowserAgentSandbox/frontend/src/main.jsx)
- [extension/sidepanel.html](/C:/Users/archi/BrowserAgentSandbox/extension/sidepanel.html)


## Demo video (placeholder)

Place the demo video in `docs/demo.mp4` or upload to YouTube/Vimeo and put the link below. Example:

**Demo video:** https://example.com/your-demo-video (replace with actual URL)

Markdown space for an embedded video (GitHub does not render mp4 inline; link is recommended):

[Demo video — click to view](docs/demo.mp4)


## Architecture & Design Notes

- LLM grounding uses a layered approach: semantic_target (role+label) → CSS selector → vision fallback.
- Policy engine evaluates actions for safety and sensitive content before execution (see `backend/app/policy/`).
- WebSocket-based action feed streams step-level updates to the frontend UI.


## How to record the demo

1. Start the backend (uvicorn) and frontend (vite).
2. Navigate the UI and start a demo run via the chat endpoint or the `/run-agent` endpoint.
3. Capture the screen focused on the UI and the terminal showing agent logs.
4. Keep the demo short (3-5 minutes), highlight:
   - planning phase (agent outlines steps)
   - step-by-step action execution in the browser
   - policy escalation or clarifier interactions (if any)
   - successful task completion or graceful failure handling


## Files to review (quick pointers)
- [Agent core](/C:/Users/archi/BrowserAgentSandbox/backend/app/agent/)
- [Policy engine](/C:/Users/archi/BrowserAgentSandbox/backend/app/policy/)
- [Frontend](/C:/Users/archi/BrowserAgentSandbox/frontend/)
- [Test pages](/C:/Users/archi/BrowserAgentSandbox/test-pages)


## Contact / Authors

See the repository authors and Git history. For questions about submission, contact the repo owner.

---

*Notes for maintainers*: add `docs/architecture.png` and `docs/demo.mp4` (or external video link) before final submission. Also consider adding a `backend/requirements.txt` pinned to tested versions.

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
