export const connectWebSocket = () => {
  const ws = new WebSocket("ws://localhost:8000/ws");

  ws.onopen = () => {
    console.log("Connected");
  };

  ws.onmessage = (event) => {
    console.log(event.data);
  };

  ws.onclose = () => {
    console.log("Disconnected");
  };

  return ws;
};
