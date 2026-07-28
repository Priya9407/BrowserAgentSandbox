# Frontier - AI Browser Agent Sandbox

> A secure browser automation framework that protects browser-controlling AI agents from hidden prompt injection attacks using a policy enforcement layer.

---

# What this repo contains

- `backend/` — FastAPI backend, Playwright browser automation, Gemini LLM integration, policy engine, and WebSocket payloads.
- `frontend/` — React + Vite dashboard for live agent action feed and provenance viewing.
- `test-pages/` — local example pages used by the Playwright agent.

---

# Quick start

## 1. Backend

1. Open a terminal in `version1/backend`
2. Create and activate a Python virtual environment:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

3. Install the required packages:

```powershell
pip install fastapi uvicorn python-dotenv google-genai playwright pydantic websockets
```

4. Install Playwright browsers:

```powershell
python -m playwright install chromium
```

5. Ensure your Gemini API key is available in `backend/.env` or as `GEMINI_API_KEY` in your environment.

6. Start the backend server:

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Backend endpoints

- `GET /` — health check returning `{ "status": "running" }`
- `POST /run-agent` — triggers the agent loop and begins Playwright browser automation
  - Query params available:
    - `page=shopping|login|hidden|testshopping`
    - `user_task=<text>`
    - `auto_approve_escalated=true|false`
  - Example:

```powershell
curl -X POST "http://localhost:8000/run-agent?page=hidden&user_task=Buy%20earbuds%20under%20%E2%82%B92000"
```

- `WS /ws` — WebSocket feed for real-time action + policy updates

---

## 2. Frontend

1. Open a second terminal in `version1/frontend`
2. Install Node dependencies:

```powershell
npm install
```

3. Start the frontend app:

```powershell
npm run dev
```

4. Open the browser at the printed Vite URL, typically `http://127.0.0.1:5173`.

---

# How to use the app

1. Start the backend first, then start the frontend.
2. Open the React dashboard in your browser.
3. Verify the WebSocket status badge in the top-right is `Connected`.
4. Click `Run Agent` to start the browser automation loop.
5. The dashboard will display actions under `Action Feed` and show details in `Provenance` when you select an action.

---

# Development status

- Day 1 completed: architecture locked, minimal agent loop, structured JSON action schema, policy engine, hidden-content detector, React dashboard shell, and two poisoned pages.
- Day 2 progress:
  - Day 2A: agent multi-step loop is present and uses history to build sequential actions.
  - Day 2B: source-classifier and risk taxonomy are implemented in `backend/app/policy/source_classifier.py` and `backend/app/policy/policy_engine.py`.
  - Day 2C: live backend WebSocket feed now streams real `action` + `policy` JSON to the dashboard, replacing the old conceptual stub.
  - Day 2D: started — the backend now supports page-targeted test runs via `POST /run-agent?page=hidden` and `page=login`.

---

# Features and how to verify them

## Action feed + provenance

- `Action Feed` lists each action the agent generates.
- Each entry includes:
  - `action_type`
  - `target` selector
  - policy decision (`ALLOW`, `ESCALATE`, or `DENY`)
  - risk level and hidden-content flag
- Click an action to view its provenance details:
  - cited source text
  - cited source location
  - reasoning
  - policy decision explanation

## Hidden prompt detection and policy gating

- The backend uses `backend/app/policy/hidden_detector.py` and `backend/app/policy/policy_engine.py`.
- If hidden page content is detected, the dashboard will show `⚠ hidden content` and the policy decision may change.
- The policy engine can allow, escalate, or deny actions before they execute in Playwright.

## Playwright browser automation

- The agent runs from `backend/app/agent/playwright_agent.py`.
- By default it loads `test-pages/shopping.html`.
- If the backend is running and the agent is allowed, a Chromium browser is launched and the action is executed.
- If you run the agent directly:

```powershell
python backend/app/agent/playwright_agent.py
```

## Demo action support

- In the frontend, `Load demo action` adds a mock pre-built action to the dashboard without contacting the backend.
- Use this to verify the dashboard UI when the backend is not running.

---

# Test pages

The local examples are stored in `test-pages/`:

- `shopping.html` — default page used by the agent
- `login.html` — login scenario example
- `hidden.html` — hidden content example for prompt-injection testing
- `testshopping.html` — alternate shopping page

Open these in the browser or inspect them to see how hidden content is embedded.

---

# Running tests

From `version1/backend`:

```powershell
.\.venv\Scripts\Activate.ps1
pytest
```

This runs the backend unit tests in `backend/tests/`, including agent behavior, policy rules, hidden-content detection, and schema validation.

---

# Notes

- The frontend dashboard uses WebSockets to receive action updates from the backend at `ws://localhost:8000/ws`.
- The actual agent uses Gemini via `google-genai`, so make sure `GEMINI_API_KEY` is set.
- If the backend is not running, the dashboard will still connect but will not receive live actions.
- The main data flow is:
  1. user task → browser agent
  2. browser DOM → Gemini
  3. structured JSON → policy check
  4. allowed actions → Playwright execution

---

## AgentAction

Represents one browser action.

```python
class AgentAction(BaseModel):

    action_id: str

    action_type: str

    target: str

    reasoning: str

    cited_source_text: str

    cited_source_location: str

    timestamp: str
```

---

## Playwright

Responsible for

- Opening browser
- Reading HTML
- Executing browser actions

Example

```python
page.click(action.target)
```

---

## WebSocket

Used for real-time communication between

Backend

↓

Frontend

Current implementation streams JSON payloads with the shape:

```json
{
  "action": { ... },
  "policy": { ... }
}
```

This includes AgentAction data plus PolicyResult data, so the dashboard can render real live updates.

---

# Tech Stack

## Frontend

- React
- Vite

---

## Backend

- FastAPI
- Pydantic
- WebSockets

---

## AI

- Google Gemini API
- google-genai SDK

---

## Browser Automation

- Playwright

---

## Environment

- Python 3.11+
- Node.js 20+
- Chromium

---

# Installation

## Clone Repository

```bash
git clone <repository-url>
```

---

## Backend

Create virtual environment

```bash
python -m venv venv
```

Activate

Windows

```bash
venv\Scripts\activate
```

Install dependencies

```bash
pip install fastapi uvicorn playwright google-genai python-dotenv
```

Install Playwright browser

```bash
playwright install
```

---

## Environment Variables

Create

```
.env
```

```
GOOGLE_API_KEY=YOUR_API_KEY
```

---

## Frontend

```bash
cd frontend

npm install

npm run dev
```

---

# Running Individual Modules

## 1. FastAPI

```bash
uvicorn app.main:app --reload
```

Runs backend server.

---

## 2. React

```bash
npm run dev
```

Runs frontend dashboard.

---

## 3. Test Gemini

```bash
python -m tests.test_agent
```

Expected

```
Gemini

↓

Structured JSON

↓

AgentAction
```

---

## 4. Browser Automation

```bash
python -m app.agent.playwright_agent
```

Expected

```
Open Browser

↓

Read DOM

↓

Gemini Decision

↓

Click Button

↓

Laptop Added To Cart
```

---

# Current End-to-End Flow

```
User Task

↓

BrowserAgent

↓

Gemini

↓

AgentAction

↓

Playwright

↓

Browser
```

---

# Current Features

- AI-powered browser reasoning
- DOM extraction
- Structured browser actions
- Browser automation
- WebSocket communication
- React dashboard skeleton
- Modular architecture

---

# Future Roadmap

```
User

↓

Browser Agent

↓

Gemini

↓

Policy Engine

↓

ALLOW / DENY / ESCALATE

↓

Playwright

↓

Browser

↓

Audit Logs

↓

React Dashboard
```

---

Built for Frontier Hackathon.