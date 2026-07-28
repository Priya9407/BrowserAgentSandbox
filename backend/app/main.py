import asyncio
import json
import logging
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

@app.get("/")
def home():
    return {"status": "running"}

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

        # Avoid a tight loop when many payloads appear consecutively.
        await asyncio.sleep(1)

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