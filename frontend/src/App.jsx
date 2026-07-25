import { useState } from "react";
import { useAgentSocket } from "./services/websocket";
import ActionFeed from "./components/ActionFeed";
import Provenance from "./components/Provenance";
import { mockScenarios } from "./mock/mockActions";
import "./App.css";

const STATUS_LABEL = {
  connecting: { icon: "🟡", text: "Connecting…" },
  open: { icon: "🟢", text: "Connected" },
  closed: { icon: "🔴", text: "Disconnected — retrying" },
  error: { icon: "🔴", text: "Connection error" },
};

let mockIndex = 0;

function App() {
  const { status, actions, sendPing, addMockAction } = useAgentSocket();
  const [selectedId, setSelectedId] = useState(null);

  const selected =
    actions.find((item) => item.action.action_id === selectedId) || null;

  const statusInfo = STATUS_LABEL[status] || STATUS_LABEL.error;

  const handleLoadDemo = () => {
    const scenario = mockScenarios[mockIndex % mockScenarios.length];
    mockIndex += 1;
    addMockAction(scenario());
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>Browser Agent Sandbox</h1>
        <div className="header-controls">
          <span className="status-badge">
            {statusInfo.icon} {statusInfo.text}
          </span>
          <button onClick={sendPing} className="ping-btn">
            Ping backend
          </button>
          <button onClick={handleLoadDemo} className="demo-btn">
            Load demo action
          </button>
        </div>
      </header>

      <main className="app-body">
        <ActionFeed
          actions={actions}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
        <Provenance item={selected} />
      </main>
    </div>
  );
}

export default App;