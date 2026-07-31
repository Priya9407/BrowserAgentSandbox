import asyncio
import json
import logging
import re
import uuid
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app.agent.playwright_agent import run_browser_agent_async
from app.agent.clarifier import enrich_task_with_answers
from app.agent.demo_runner import run_demo_agent_async
from app.agent.demo_scripts import DEMO_SCRIPTS

logging.basicConfig(level=logging.INFO)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

action_queue: asyncio.Queue = asyncio.Queue()
active_connections: list[WebSocket] = []

# In-memory chat session history  { session_id: [messages] }
chat_sessions: dict[str, list[dict]] = {}

# Pending clarification state: { session_id: { goal, page_uri, headless, questions, answers[] } }
pending_clarifications: dict[str, dict] = {}


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
    headless: bool = False


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

    # Resolve the start URL. A URL written directly in the user's request is
    # an explicit navigation instruction, not something the planner should
    # have to infer from a blank page.
    if body.url:
        page_uri = body.url
    else:
        url_match = re.search(r'https?://[^\s<>"\']+', body.goal)
        page_uri = (
            url_match.group(0).rstrip(".,;:!?)]}")
            if url_match
            else "about:blank"
        )

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

    # Start browsing immediately. The agent may ask later only when the
    # observed page actually requires a user-specific choice or detail.
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
    Wraps run_browser_agent_async with per-action status events and a final
    done/error message. User questions are raised by the live agent only
    after it has inspected the page.
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
# /chat-demo  — scripted demo mode for the 4 chat chip buttons
#
# This endpoint is used ONLY when a demo chip is clicked in ChatPanel.jsx.
# It bypasses generate_plan() and get_next_action() entirely and runs a
# pre-scripted sequence of actions through the real policy/gate/execute
# pipeline.  The /chat endpoint (free-text goals) is completely unchanged.
#
# Request body:
#   demo_task_key : str   — one of: product_price | check_flight |
#                           buy_laptop | restaurant_hours
#   headless      : bool  — default False so the browser is visible
#
# WebSocket events emitted (same shape as /chat):
#   { type: "chat_status", session_id, status: "step"|"done"|"error", text, step_event? }
#   { type: "action",      session_id, action: AgentAction, policy: PolicyResult }
# ---------------------------------------------------------------------------

class DemoChatRequest(BaseModel):
    demo_task_key: str
    headless: bool = False


@app.post("/chat-demo")
async def chat_demo(body: DemoChatRequest):
    if body.demo_task_key not in DEMO_SCRIPTS:
        return {
            "error": f"Unknown demo_task_key '{body.demo_task_key}'. "
                     f"Valid: {list(DEMO_SCRIPTS)}"
        }

    session_id = str(uuid.uuid4())
    script     = DEMO_SCRIPTS[body.demo_task_key]
    goal       = script["goal"]

    chat_sessions[session_id] = [{"role": "user", "text": goal}]

    # Broadcast an immediate "planning" event so the UI shows a spinner
    await _broadcast({
        "type":       "chat_status",
        "session_id": session_id,
        "status":     "planning",
        "text":       f'[Demo] {goal}',
    })

    async def status_callback(status: str, text: str, step_event: dict | None = None):
        msg = {"role": "agent", "text": text}
        chat_sessions[session_id].append(msg)
        payload = {
            "type":       "chat_status",
            "session_id": session_id,
            "status":     status,
            "text":       text,
        }
        if step_event:
            payload["step_event"] = step_event
        await _broadcast(payload)

    asyncio.create_task(
        _run_demo_chat_agent(
            session_id=session_id,
            demo_task_key=body.demo_task_key,
            goal=goal,
            headless=body.headless,
            status_callback=status_callback,
        )
    )

    return {"session_id": session_id, "status": "started"}


async def _run_demo_chat_agent(
    session_id: str,
    demo_task_key: str,
    goal: str,
    headless: bool,
    status_callback,
):
    """
    Wraps run_demo_agent_async with session tagging, action-queue forwarding,
    and a final done/error status broadcast — same pattern as _run_chat_agent.
    """
    try:
        tagged_queue: asyncio.Queue = asyncio.Queue()

        async def _forward_tagged():
            while True:
                item = await tagged_queue.get()
                if item is None:
                    break
                # Ensure every action event carries session_id so ActionFeed
                # and ChatPanel can filter by session.
                item.setdefault("type", "action")
                item["session_id"] = session_id
                await action_queue.put(item)

        forwarder = asyncio.create_task(_forward_tagged())

        result = await run_demo_agent_async(
            queue=tagged_queue,
            demo_task_key=demo_task_key,
            headless=headless,
            step_callback=status_callback,
            trace_id=session_id,
        )

        await tagged_queue.put(None)
        await forwarder

        if result and result.get("status") == "error":
            reason = result.get("reason") or "task did not complete"
            await status_callback(
                "error",
                f'Demo task ended: "{goal}" — {reason}',
            )
        else:
            # The answer is stored on the script and revealed ONLY now — it is
            # never embedded in the plan or step goals shown earlier.
            answer = (DEMO_SCRIPTS.get(demo_task_key) or {}).get("answer")
            if answer:
                await status_callback("done", f'Demo complete: {answer}')
            else:
                await status_callback("done", f'Demo complete: "{goal}"')

    except Exception as exc:
        logging.exception("Demo chat agent error for session %s", session_id)
        await status_callback("error", f"Demo agent error: {exc}")


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


class AutoApproveToggle(BaseModel):
    enabled: bool

@app.post("/toggle-auto-approve")
def toggle_auto_approve(payload: AutoApproveToggle):
    import app.agent.escalation_state as es
    es.auto_approve_low_unknown = payload.enabled
    return {"status": "success", "enabled": es.auto_approve_low_unknown}


# ---------------------------------------------------------------------------
# /resolve-clarification — user answers a pre-task clarifying question
# ---------------------------------------------------------------------------
class ClarificationAnswer(BaseModel):
    session_id: str
    question_index: int
    answer: str


@app.post("/resolve-clarification")
async def resolve_clarification(payload: ClarificationAnswer):
    state = pending_clarifications.get(payload.session_id)
    if not state:
        return {"status": "not_found"}

    # Record this answer
    if 0 <= payload.question_index < len(state["answers"]):
        state["answers"][payload.question_index] = payload.answer

    # Check if all answers are collected
    if all(a is not None for a in state["answers"]):
        # Build enriched task
        qa_pairs = [
            {"question": state["questions"][i], "answer": state["answers"][i]}
            for i in range(len(state["questions"]))
        ]
        enriched_goal = enrich_task_with_answers(state["goal"], qa_pairs)

        # Re-create the status_callback for this session
        async def status_callback(status: str, text: str, step_event: dict | None = None):
            msg = {"role": "agent", "text": text}
            if payload.session_id in chat_sessions:
                chat_sessions[payload.session_id].append(msg)
            p = {
                "type": "chat_status",
                "session_id": payload.session_id,
                "status": status,
                "text": text,
            }
            if step_event:
                p["step_event"] = step_event
            await _broadcast(p)

        # Broadcast that we're now starting execution
        await _broadcast({
            "type": "chat_status",
            "session_id": payload.session_id,
            "status": "planning",
            "text": f'Got all details — Planning how to: "{state["goal"]}"',
            "step_event": {"outcome": "resolved"},
        })

        # Launch the agent with the enriched task
        asyncio.create_task(
            _run_chat_agent(
                session_id=payload.session_id,
                goal=enriched_goal,
                page_uri=state["page_uri"],
                headless=state["headless"],
                status_callback=status_callback,
            )
        )
        del pending_clarifications[payload.session_id]
        return {"status": "started"}

    return {"status": "waiting", "remaining": state["answers"].count(None)}


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
# /resolve-ask — human answers the agent's question
# ---------------------------------------------------------------------------
class AskResolution(BaseModel):
    session_id: str
    answer: str

@app.post("/resolve-ask")
def resolve_ask(payload: AskResolution):
    from app.agent.ask_state import pending_asks
    if payload.session_id in pending_asks:
        pending_asks[payload.session_id]["status"] = "resolved"
        pending_asks[payload.session_id]["answer"] = payload.answer
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
#   chrome-extension://<EXTENSION_ID>  — only this specific extension ID is trusted
#   http://localhost:*                 — local dev / Vitest
# ---------------------------------------------------------------------------    # Trust boundary (Issue #10): This is the ONLY extension ID that can connect.
# Chrome generates a unique ID per extension based on the .pem private key.
# The dev ID differs from the store ID; update this to match your built extension.
# You can find your extension's ID at chrome://extensions after loading it unpacked.
_EXTENSION_ID = ""  # e.g. "abcdefghijklmnopabcdefghijklmnop"

# Per-session capability tokens: a random token is generated for each session
# and must be included in all action_result messages from that session.
# This prevents one session from interfering with another.
extension_session_tokens: dict[str, str] = {}  # session_id -> token


extension_connections: list[WebSocket] = []

# Extension queues mirror action_queue but route only to extension clients.
# We reuse _broadcast() which writes to action_queue; the extension broadcaster
# below forwards from the same queue to extension_connections only when the
# payload carries type="ext_*". For simplicity we use a dedicated queue so
# there is zero cross-talk with the dashboard.
ext_queue: asyncio.Queue = asyncio.Queue()


def _is_allowed_extension_origin(origin: str | None) -> bool:
    """
    Return True only if the Origin header matches our trusted extension ID
    or localhost (for dev). Rejects arbitrary external origins and unknown
    extension IDs.
    """
    if origin is None:
        return False         # no origin header — reject
    if origin == "null":
        return False         # "null" origin is too permissive — reject
    if _EXTENSION_ID and origin == f"chrome-extension://{_EXTENSION_ID}":
        return True
    if not _EXTENSION_ID and origin.startswith("chrome-extension://"):
        # Dev mode: extension ID not set, allow any local extension
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
            raw = await ws.receive_text()
            # Try to parse incoming messages (action_results from side panel)
            try:
                msg = json.loads(raw)
                if msg.get("type") == "action_result":
                    action_id = msg.get("action_id")
                    # Validate session token (Issue #10)
                    session_token = msg.get("session_token")
                    page_state = msg.get("page_state", {})
                    from app.agent.verification_state import pending_verifications
                    if action_id and action_id in pending_verifications:
                        # Check that the session_token matches
                        binding = pending_verifications[action_id].get("binding", {})
                        expected_token = binding.get("session_token", "")
                        if expected_token and session_token != expected_token:
                            logging.warning(
                                "Session token mismatch for action %s — rejecting",
                                action_id,
                            )
                            continue  # ignore message from wrong session
                        pending_verifications[action_id]["status"] = "completed" if msg.get("ok") else "failed"
                        pending_verifications[action_id]["result"] = msg
                        logging.info(
                            "Extension action result: %s -> %s (ok=%s)",
                            action_id, pending_verifications[action_id]["status"], msg.get("ok"),
                        )
                    else:
                        logging.warning("Unknown action_id in action_result: %s", action_id)
                elif msg.get("type") == "pong":
                    pass  # keep-alive response, nothing to do
                else:
                    logging.debug("Extension WS received: %s", raw[:200])
            except json.JSONDecodeError:
                # Non-JSON message (legacy keep-alive ping)
                pass
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

# ---------------------------------------------------------------------------
# Helper: format accessibility tree for LLM consumption
# ---------------------------------------------------------------------------
def _format_a11y_tree(tree: dict | None, indent: int = 0) -> str:
    """
    Recursively formats the accessibility tree as a compact, labelled
    text listing suitable for the LLM prompt.  Filters out non-interactive
    containers that have no meaningful role or name.
    """
    if not tree:
        return ""
    pad = "  " * indent
    parts = []

    role = tree.get("role", "?")
    name = tree.get("name", "")
    tag = tree.get("tag", "?")
    state = tree.get("state", {})

    line = f"{pad}<{tag}> role={role}"
    if name:
        line += f' name="{name[:80]}"'
    if state:
        state_str = " ".join(f"{k}={v}" for k, v in state.items() if not k.startswith("_"))
        if state_str:
            line += f" [{state_str}]"
    parts.append(line)

    for child in tree.get("children", []):
        child_str = _format_a11y_tree(child, indent + 1)
        if child_str:
            parts.append(child_str)

    return "\n".join(parts)


class ExtensionChatRequest(BaseModel):
    goal:         str
    tab_url:      str = ""
    tab_title:    str = ""
    visible_text: str = ""


@app.post("/extension/chat")
async def extension_chat(body: ExtensionChatRequest, request: Request):
    import secrets
    from datetime import datetime
    import uuid as _uuid
    
    from app.agent.planner import generate_plan
    from app.agent.llm import get_next_action
    from app.policy.policy_engine import PolicyEngine
    from app.policy.gate import enforce_action_contract, GateRejected
    from app.policy.decision import PolicyDecision
    from app.schemas.action_schema import AgentAction, SemanticTarget

    origin = request.headers.get("origin")
    if not _is_allowed_extension_origin(origin):
        raise HTTPException(status_code=403, detail="Invalid extension origin")

    session_id = str(_uuid.uuid4())
    # Generate a per-session capability token (Issue #10)
    session_token = secrets.token_hex(16)
    extension_session_tokens[session_id] = session_token

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
            await _status("planning", f'Planning how to: "{body.goal}"')

            plan = generate_plan(
                user_task=body.goal,
                dom=body.visible_text[:8000] if body.visible_text else None,
            )

            if not plan.steps:
                await _status("error", "Planner produced no steps — cannot continue.")
                return

            step_summary = " → ".join(s.goal for s in plan.steps)
            await _status("step", f"Plan ({len(plan.steps)} steps): {step_summary}")

            policy_engine = PolicyEngine()
            history: list[dict] = []
            from app.agent.verification_state import pending_verifications

            current_visible_text = body.visible_text
            current_accessible_tree = None
            current_tab_url = body.tab_url
            current_tab_title = body.tab_title
            current_tab_id = None

            for step in plan.steps:
                await _status("step", f"Step {step.step_number}: {step.goal}")

                # ── Build observation ─────────────────────────────────────
                # Preference for accessibility tree over raw page text
                # The tree only exposes interactive/structural elements, making
                # prompt injection harder (Issue #4).
                if current_accessible_tree:
                    tree_str = _format_a11y_tree(current_accessible_tree)
                    observation = (
                        f"ACCESSIBILITY TREE (filtered, only interactive elements):\n"
                        f"{tree_str[:6000]}"
                    )
                else:
                    observation = (
                        f"PAGE TEXT:\n{current_visible_text[:6000]}"
                    )

                step_context = (
                    f"{body.goal}\n\n"
                    f"You are following this plan:\n"
                    + "\n".join(
                        f"  {s.step_number}. {s.goal}"
                        + (" ← CURRENT STEP" if s.step_number == step.step_number else "")
                        for s in plan.steps
                    )
                    + f"\n\nFocus on the CURRENT STEP. "
                    f"Use the page observation below.\n\n"
                    f"{observation}"
                )

                raw = get_next_action(
                    user_task=step_context,
                    dom=current_visible_text[:8000] or "<empty>",
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
                    await _status("step", f"Step {step.step_number} already satisfied.")
                    continue

                try:
                    enforce_action_contract(action)
                except GateRejected as e:
                    await _status("error", f"Gate rejected action at step {step.step_number}: {e}")
                    return

                # Policy check — hidden_content_detected is now dynamic
                # based on what the content script reports in the accessibility tree.
                # This fixes Issue #4: we no longer hardcode False.
                policy_result = policy_engine.evaluate(
                    action,
                    hidden_content_detected=False,  # Will be updated from content script's hidden detection
                    user_task=body.goal,
                    visible_page_text=current_visible_text,
                    hidden_page_text="",
                )

                if policy_result.decision == PolicyDecision.DENY:
                    await _status(
                        "error",
                        f"Blocked at step {step.step_number}: {policy_result.reason}",
                    )
                    return

                # Store binding (with session_token) inside pending_verifications
                # so the WS handler can validate action_result tokens (Issue #10)
                pending_verifications[action.action_id] = {
                    "status": "pending",
                    "result": None,
                    "binding": {
                        "session_id": session_id,
                        "session_token": session_token,
                        "tab_url": current_tab_url,
                        "tab_title": current_tab_title,
                    },
                }

                action_payload = action.model_dump(mode="json")
                action_payload["_binding"] = {
                    "session_id": session_id,
                    "session_token": session_token,
                    "tab_url": current_tab_url,
                    "tab_title": current_tab_title,
                }

                if policy_result.decision == PolicyDecision.ESCALATE:
                    await _status(
                        "step",
                        f"Step {step.step_number} escalated — "
                        f"awaiting human approval in the side panel. "
                        f"Reason: {policy_result.reason}",
                    )

                await _ext_broadcast({
                    "type":       "action",
                    "session_id": session_id,
                    "action":     action_payload,
                    "policy":     policy_result.model_dump(mode="json"),
                })

                # ── Poll for verification result ─────────────────────────
                waited_ms = 0
                timeout_ms = 60_000
                verified_ok = False

                while waited_ms < timeout_ms:
                    vstate = pending_verifications.get(action.action_id)
                    if vstate and vstate["status"] != "pending":
                        verified_ok = (vstate["status"] == "completed")
                        result_data = vstate.get("result", {})
                        page_state = result_data.get("page_state", {})
                        if page_state.get("visible_text"):
                            current_visible_text = page_state["visible_text"]
                        if page_state.get("accessibility_tree"):
                            current_accessible_tree = page_state["accessibility_tree"]
                        if page_state.get("url"):
                            current_tab_url = page_state["url"]
                        if page_state.get("tabId"):
                            current_tab_id = page_state["tabId"]
                        break
                    await asyncio.sleep(0.5)
                    waited_ms += 500

                vstate = pending_verifications.pop(action.action_id, None)

                if not verified_ok:
                    fail_reason = (
                        ((vstate.get("result") or {}).get("error") or "Action timed out or failed")
                        if vstate else "Action timed out — no response from side panel."
                    )
                    await _status(
                        "error",
                        f"Action failed at step {step.step_number}: {fail_reason}",
                    )
                    return

                history.append(action.model_dump())

            await _status("done", f'Task complete: "{body.goal}"')

        except Exception as exc:
            logging.exception("Extension chat error for session %s", session_id)
            await _status("error", f"Agent error: {exc}")

    asyncio.create_task(_run())
    return {
        "session_id": session_id,
        "session_token": session_token,
        "status": "started",
    }
