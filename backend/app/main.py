import asyncio
import json
import logging
import uuid
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app.agent.playwright_agent import run_browser_agent_async

logging.basicConfig(level=logging.INFO)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

action_queue: asyncio.Queue = asyncio.Queue()
active_connections: list[WebSocket] = []

# In-memory chat session history  { session_id: [messages] }
chat_sessions: dict[str, list[dict]] = {}


# ---------------------------------------------------------------------------
# Helper — push any payload to all WebSocket clients
# ---------------------------------------------------------------------------
async def _broadcast(payload: dict):
    await action_queue.put(payload)


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------
@app.get("/")
def home():
    return {"status": "running"}


# ---------------------------------------------------------------------------
# /run-agent  (existing flow, unchanged)
# ---------------------------------------------------------------------------
@app.post("/run-agent")
async def run_agent(
    page: str = "shopping",
    user_task: str = "Buy the laptop",
    auto_approve_escalated: bool = False,
):
    page_files = {
        "shopping": "shopping.html",
        "login": "login.html",
        "hidden": "hidden.html",
        "testshopping": "testshopping.html",
        "flight_visible": "flight_visible.html",
        "opacity_download": "opacity_download.html",
        "color_email": "color_email.html",
        "visibility_transfer": "visibility_transfer.html",
        "fontsize_exfil": "fontsize_exfil.html",
        "zindex_privilege": "zindex_privilege.html",
        "aria_hidden": "aria_hidden.html",
        "clip_path_api": "clip_path_api.html",
        "benign_checkout": "benign_checkout.html",
    }

    project_root = Path(__file__).resolve().parents[2]
    page_file = page_files.get(page, "shopping.html")
    page_uri = (project_root / "test-pages" / page_file).as_uri()

    asyncio.create_task(
        run_browser_agent_async(
            action_queue,
            page_uri=page_uri,
            user_task=user_task,
            headless=False,
            auto_approve_escalated=auto_approve_escalated,
        )
    )
    return {"status": "started", "page": page_file}


# ---------------------------------------------------------------------------
# /chat  — the new chat-driven entrypoint
#
# Request body:
#   goal   : free-text goal the user typed ("search for the price of RTX 4090")
#   url    : optional starting URL (defaults to our benign shopping page)
#   headless: bool, default True so the browser stays out of the way
#
# How it works:
#   1. Creates a session_id and records the user message in chat_sessions.
#   2. Broadcasts a chat_status "planning" event over WebSocket immediately
#      so the UI can show a spinner/status line without waiting.
#   3. Fires off the agent task in the background (non-blocking).
#   4. Returns { session_id } immediately — the rest arrives over WebSocket.
#
# WebSocket message types emitted during a /chat run:
#   { type: "chat_status",  session_id, status, text }
#     status values: "planning" | "step" | "done" | "error"
#   { type: "action",       session_id, action, policy }   ← existing action-feed events
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    goal: str
    url: str | None = None
    headless: bool = True


@app.post("/chat")
async def chat(body: ChatRequest):
    session_id = str(uuid.uuid4())

    # Record the user message
    chat_sessions[session_id] = [
        {"role": "user", "text": body.goal}
    ]

    # Immediate "planning" status so the UI reacts right away
    await _broadcast({
        "type": "chat_status",
        "session_id": session_id,
        "status": "planning",
        "text": f'Planning how to: "{body.goal}"',
    })

    # Resolve the start URL
    project_root = Path(__file__).resolve().parents[2]
    if body.url:
        page_uri = body.url
    else:
        # Default demo page — benign shopping so ordinary tasks work
        page_uri = (project_root / "test-pages" / "benign_checkout.html").as_uri()

    # Launch agent in the background, passing a status_callback so it can
    # emit chat_status events at each step without knowing about WebSockets.
    async def status_callback(status: str, text: str, step_event: dict | None = None):
        msg = {"role": "agent", "text": text}
        chat_sessions[session_id].append(msg)
        payload = {
            "type": "chat_status",
            "session_id": session_id,
            "status": status,
            "text": text,
        }
        if step_event:
            payload["step_event"] = step_event
        await _broadcast(payload)

    asyncio.create_task(
        _run_chat_agent(
            session_id=session_id,
            goal=body.goal,
            page_uri=page_uri,
            headless=body.headless,
            status_callback=status_callback,
        )
    )

    return {"session_id": session_id, "status": "started"}


async def _run_chat_agent(
    session_id: str,
    goal: str,
    page_uri: str,
    headless: bool,
    status_callback,
):
    """
    Wraps run_browser_agent_async with:
    - a pre-run "planning" step message
    - per-action status events (via action_queue, same as before)
    - a final "done" or "error" message
    """
    try:
        # Wrap the action_queue so every action payload also gets a
        # session_id and type="action" attached, keeping it compatible
        # with the existing ActionFeed while also letting ChatPanel filter
        # by session_id.
        tagged_queue: asyncio.Queue = asyncio.Queue()

        async def _forward_tagged():
            while True:
                item = await tagged_queue.get()
                if item is None:
                    break
                # Tag with session info for the chat panel
                item["type"] = "action"
                item["session_id"] = session_id
                await action_queue.put(item)

        forwarder = asyncio.create_task(_forward_tagged())

        result = await run_browser_agent_async(
            tagged_queue,
            page_uri=page_uri,
            user_task=goal,
            headless=headless,
            auto_approve_escalated=False,
            step_callback=status_callback,   # streams per-step progress to chat
            trace_id=session_id,             # keys the X-Ray placeholder trace file
        )

        # Signal forwarder to stop
        await tagged_queue.put(None)
        await forwarder

        # Bug fix (Milestone 3 item A): previously this sent "done"
        # unconditionally, even when the task was blocked by policy, hit a
        # CAPTCHA, or ran out of steps without finishing. Respect the real
        # outcome from run_browser_agent_async instead.
        if result and result.get("status") == "error":
            reason = result.get("reason") or "did not complete"
            await status_callback("error", f'Task ended without completing: "{goal}" — {reason}')
        else:
            await status_callback("done", f'Task complete: "{goal}"')

    except Exception as exc:
        logging.exception("Chat agent error for session %s", session_id)
        await status_callback("error", f"Agent error: {exc}")


# ---------------------------------------------------------------------------
# /chat-sessions  — return history for a session (or all sessions)
# ---------------------------------------------------------------------------
@app.get("/chat-sessions")
def get_chat_sessions():
    return chat_sessions


@app.get("/chat-sessions/{session_id}")
def get_chat_session(session_id: str):
    if session_id not in chat_sessions:
        return {"error": "session not found"}
    return chat_sessions[session_id]


# ---------------------------------------------------------------------------
# /resolve-escalation  (unchanged)
# ---------------------------------------------------------------------------
class EscalationResolution(BaseModel):
    action_id: str
    decision: str


@app.post("/resolve-escalation")
def resolve_escalation(payload: EscalationResolution):
    from app.agent.escalation_state import pending_escalations
    if payload.action_id in pending_escalations:
        pending_escalations[payload.action_id] = payload.decision
        return {"status": "success"}
    return {"status": "not found"}


# ---------------------------------------------------------------------------
# /resolve-captcha — human signals they solved a CAPTCHA in the browser
# ---------------------------------------------------------------------------
class CaptchaResolution(BaseModel):
    session_id: str


@app.post("/resolve-captcha")
def resolve_captcha(payload: CaptchaResolution):
    from app.agent.captcha_state import pending_captchas
    if payload.session_id in pending_captchas:
        pending_captchas[payload.session_id] = "resolved"
        return {"status": "success"}
    return {"status": "not found"}


# ---------------------------------------------------------------------------
# WebSocket broadcaster
# ---------------------------------------------------------------------------
async def broadcaster():
    while True:
        payload = await action_queue.get()
        message = json.dumps(payload)
        dead = []

        for conn in active_connections:
            try:
                await conn.send_text(message)
            except Exception as exc:
                logging.warning("WebSocket send failed, removing connection: %s", exc)
                dead.append(conn)

        for conn in dead:
            if conn in active_connections:
                active_connections.remove(conn)

        await asyncio.sleep(0)   # yield — no artificial 1 s delay for chat events


@app.on_event("startup")
async def start_broadcaster():
    asyncio.create_task(broadcaster())


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    active_connections.append(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        logging.info("Client disconnected — closing this connection cleanly.")
    except Exception as exc:
        logging.warning("WebSocket error, removing connection: %s", exc)
    finally:
        if ws in active_connections:
            active_connections.remove(ws)


# ---------------------------------------------------------------------------
# Extension WebSocket connections (separate list from the dashboard /ws)
#
# The browser extension connects here instead of /ws so we can:
#   a) apply a chrome-extension:// origin check without affecting the
#      dashboard's permissive CORS policy
#   b) keep extension sessions independently addressable
#
# Allowed origins:
#   chrome-extension://*   — any locally-loaded or store-installed extension
#   http://localhost:*     — local dev / Vitest
#   null                   — some browsers send "null" for extension pages
# ---------------------------------------------------------------------------

extension_connections: list[WebSocket] = []

# Extension queues mirror action_queue but route only to extension clients.
# We reuse _broadcast() which writes to action_queue; the extension broadcaster
# below forwards from the same queue to extension_connections only when the
# payload carries type="ext_*". For simplicity we use a dedicated queue so
# there is zero cross-talk with the dashboard.
ext_queue: asyncio.Queue = asyncio.Queue()


def _is_allowed_extension_origin(origin: str | None) -> bool:
    """
    Return True if the WebSocket handshake Origin header looks like it
    came from a Chrome extension or local dev environment.
    Rejects arbitrary external origins.
    """
    if origin is None:
        return True          # no origin header — local tool / curl
    if origin == "null":
        return True          # some browsers send literal "null" for ext pages
    if origin.startswith("chrome-extension://"):
        return True
    if origin.startswith("http://localhost"):
        return True
    if origin.startswith("http://127.0.0.1"):
        return True
    return False


async def _ext_broadcast(payload: dict):
    """Push a payload to all connected extension side panels."""
    await ext_queue.put(payload)


async def _ext_broadcaster():
    while True:
        payload = await ext_queue.get()
        message = json.dumps(payload)
        dead = []
        for conn in extension_connections:
            try:
                await conn.send_text(message)
            except Exception as exc:
                logging.warning("Extension WS send failed: %s", exc)
                dead.append(conn)
        for conn in dead:
            if conn in extension_connections:
                extension_connections.remove(conn)
        await asyncio.sleep(0)


@app.on_event("startup")
async def start_ext_broadcaster():
    asyncio.create_task(_ext_broadcaster())


@app.websocket("/extension/ws")
async def extension_ws_endpoint(ws: WebSocket):
    """
    Dedicated WebSocket for the browser extension side panel.

    The standard /ws endpoint uses allow_origins=["*"] (set by CORSMiddleware)
    which is fine for the dashboard served from localhost.  Extension pages
    have a chrome-extension:// origin that we want to explicitly allow here
    while still rejecting arbitrary third-party origins.

    FastAPI's WebSocket.accept() does not perform an Origin check on its own,
    so we do it manually before accepting.
    """
    origin = ws.headers.get("origin")
    if not _is_allowed_extension_origin(origin):
        logging.warning("Extension WS rejected — disallowed origin: %s", origin)
        await ws.close(code=1008)   # Policy Violation
        return

    await ws.accept()
    extension_connections.append(ws)
    logging.info("Extension WS connected (origin=%s, total=%d)", origin, len(extension_connections))

    try:
        while True:
            await ws.receive_text()   # keep-alive; extension sends pings
    except WebSocketDisconnect:
        logging.info("Extension WS disconnected.")
    except Exception as exc:
        logging.warning("Extension WS error: %s", exc)
    finally:
        if ws in extension_connections:
            extension_connections.remove(ws)


# ---------------------------------------------------------------------------
# /extension/chat
#
# The extension side panel calls this instead of /chat.
#
# Key difference from /chat
# -------------------------
# The agent does NOT launch a new Playwright browser here.
# Instead the content script in the current tab IS the browser — the backend
# sends action events back over /extension/ws and the side panel relays them
# to the content script via chrome.runtime.sendMessage (EXECUTE_ACTION).
#
# This endpoint:
#   1. Calls generate_plan() with the goal + visible_text as context.
#   2. Streams chat_status events over /extension/ws so the side panel can
#      display step-by-step progress.
#   3. Emits type="action" events for each planned step so the side panel
#      can execute them in the current tab via content.js.
#   4. Does NOT call run_browser_agent_async — no Playwright, no separate
#      browser window.
#
# Request body
# ------------
#   goal         : str   — the user's free-text goal
#   tab_url      : str   — current tab URL (from GET_TAB_CONTEXT)
#   tab_title    : str   — current tab title
#   visible_text : str   — body.innerText of the current tab
#
# WebSocket events emitted (to /extension/ws)
# -------------------------------------------
#   { type: "chat_status", session_id, status: "planning", text }
#   { type: "chat_status", session_id, status: "step",     text }
#   { type: "action",      session_id, action: AgentAction, policy: PolicyResult }
#   { type: "chat_status", session_id, status: "done"|"error", text }
# ---------------------------------------------------------------------------

class ExtensionChatRequest(BaseModel):
    goal:         str
    tab_url:      str = ""
    tab_title:    str = ""
    visible_text: str = ""


@app.post("/extension/chat")
async def extension_chat(body: ExtensionChatRequest):
    from app.agent.planner import generate_plan
    from app.agent.agent import BrowserAgent
    from app.agent.llm import get_next_action
    from app.policy.policy_engine import PolicyEngine
    from app.policy.gate import enforce_action_contract, GateRejected
    from app.policy.decision import PolicyDecision
    from app.schemas.action_schema import AgentAction, SemanticTarget
    from datetime import datetime
    import uuid as _uuid

    session_id = str(_uuid.uuid4())
    chat_sessions[session_id] = [{"role": "user", "text": body.goal}]

    async def _status(status: str, text: str):
        chat_sessions[session_id].append({"role": "agent", "text": text})
        await _ext_broadcast({
            "type":       "chat_status",
            "session_id": session_id,
            "status":     status,
            "text":       text,
        })

    async def _run():
        try:
            # ── Step 1: Plan ───────────────────────────────────────────
            await _status("planning", f'Planning how to: "{body.goal}"')

            # Pass visible_text as the DOM context so the planner can
            # produce page-aware steps without a separate browser call.
            plan = generate_plan(
                user_task=body.goal,
                dom=body.visible_text[:8000] if body.visible_text else None,
            )

            if not plan.steps:
                await _status("error", "Planner produced no steps — cannot continue.")
                return

            step_summary = " → ".join(s.goal for s in plan.steps)
            await _status("step", f"Plan ({len(plan.steps)} steps): {step_summary}")

            # ── Step 2: Per-step LLM grounding + policy check ──────────
            policy_engine = PolicyEngine()
            history: list[dict] = []

            for step in plan.steps:
                await _status("step", f"Step {step.step_number}: {step.goal}")

                # Build task context for this step (mirrors agent._build_task_context)
                step_context = (
                    f"{body.goal}\n\n"
                    f"You are following this plan:\n"
                    + "\n".join(
                        f"  {s.step_number}. {s.goal}"
                        + (" ← CURRENT STEP" if s.step_number == step.step_number else "")
                        for s in plan.steps
                    )
                    + f"\n\nFocus on the CURRENT STEP. "
                    f"Use the page text below as the DOM.\n\n"
                    f"PAGE TEXT:\n{body.visible_text[:6000]}"
                )

                raw = get_next_action(
                    user_task=step_context,
                    dom=body.visible_text[:8000] or "<empty>",
                    history=history,
                )

                action = AgentAction(
                    action_id=str(_uuid.uuid4()),
                    action_type=raw.get("action_type", "done"),
                    target=raw.get("target", ""),
                    semantic_target=SemanticTarget(
                        role=raw.get("semantic_target", {}).get("role", "generic"),
                        label=raw.get("semantic_target", {}).get("label", ""),
                    ),
                    value=raw.get("value"),
                    reasoning=raw.get("reasoning", ""),
                    cited_source_text=raw.get("cited_source_text", ""),
                    cited_source_location=raw.get("cited_source_location", ""),
                    timestamp=datetime.now().isoformat(),
                )

                if action.action_type == "done":
                    await _status("step", f"✓ Step {step.step_number} already satisfied.")
                    continue

                # Gate check
                try:
                    enforce_action_contract(action)
                except GateRejected as e:
                    await _status("error", f"Gate rejected action at step {step.step_number}: {e}")
                    return

                # Policy check — use original goal as trust anchor
                policy_result = policy_engine.evaluate(
                    action,
                    hidden_content_detected=False,   # no heuristic scan in extension mode
                    user_task=body.goal,
                    visible_page_text=body.visible_text,
                    hidden_page_text="",
                )

                # Emit the action event — side panel will execute or escalate
                await _ext_broadcast({
                    "type":       "action",
                    "session_id": session_id,
                    "action":     action.model_dump(mode="json"),
                    "policy":     policy_result.model_dump(mode="json"),
                })

                if policy_result.decision == PolicyDecision.DENY:
                    await _status(
                        "error",
                        f"Blocked at step {step.step_number}: {policy_result.reason}",
                    )
                    return

                if policy_result.decision == PolicyDecision.ESCALATE:
                    await _status(
                        "step",
                        f"⚠️ Step {step.step_number} escalated — "
                        f"awaiting human approval in the side panel.",
                    )
                    # The side panel shows Approve/Deny; we don't block here.

                history.append(action.model_dump())

            await _status("done", f'Task complete: "{body.goal}"')

        except Exception as exc:
            logging.exception("Extension chat error for session %s", session_id)
            await _status("error", f"Agent error: {exc}")

    asyncio.create_task(_run())
    return {"session_id": session_id, "status": "started"}
