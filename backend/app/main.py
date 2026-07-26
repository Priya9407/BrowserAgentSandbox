import asyncio
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from app.agent.playwright_agent import run_browser_agent_async

app = FastAPI()
action_queue: asyncio.Queue = asyncio.Queue()
active_connections: list[WebSocket] = []

@app.get("/")
def home():
    return {"status": "running"}

@app.post("/run-agent")
async def run_agent():
    asyncio.create_task(run_browser_agent_async(action_queue))
    return {"status": "started"}

async def broadcaster():
    while True:
        payload = await action_queue.get()
        message = json.dumps(payload)
        dead = []
        for conn in active_connections:
            try:
                await conn.send_text(message)
            except Exception:
                dead.append(conn)
        for conn in dead:
            active_connections.remove(conn)

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
        print("Client disconnected — closing this connection cleanly.")
        if ws in active_connections:
            active_connections.remove(ws)