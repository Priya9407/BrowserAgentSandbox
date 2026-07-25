import { useEffect } from "react";
import { connectWebSocket } from "./services/websocket";

function App() {

  useEffect(() => {

    const ws = connectWebSocket();

    return () => ws.close();

  }, []);

  return (
    <div>
      <h1>Browser Agent Sandbox</h1>
    </div>
  );
}

export default App;