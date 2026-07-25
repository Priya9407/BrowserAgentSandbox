from fastapi import FastAPI
from fastapi import WebSocket

app = FastAPI()


@app.get("/")
def home():
    return {"status": "running"}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    while True:
        await ws.send_text("Hello")
