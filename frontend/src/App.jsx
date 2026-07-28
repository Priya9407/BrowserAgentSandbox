import { useState } from "react";
import { useAgentSocket } from "./services/websocket";
import ChatPanel from "./components/ChatPanel";
import ActionFeed from "./components/ActionFeed";
import Provenance from "./components/Provenance";
import "./App.css";

const STATUS_LABEL = {
  connecting: { dot: "dot-yellow", text: "Connecting…" },
  open:       { dot: "dot-green",  text: "Connected" },
  closed:     { dot: "dot-red",    text: "Disconnected" },
  error:      { dot: "dot-red",    text: "Error" },
};

function App() {
  // rawEvents is the full array (newest first) — ChatPanel filters chat_status,
  // ActionFeed filters action events.
  const { status, actions, rawEvents } = useAgentSocket();

  const [selectedId,      setSelectedId]      = useState(null);
  const [activeSessionId, setActiveSessionId] = useState(null);

  const selected =
    actions.find((item) => item.action?.action_id === selectedId) || null;

  const statusInfo = STATUS_LABEL[status] || STATUS_LABEL.error;

  return (
    <div className="app">
      {/* ── Header ─────────────────────────────────────────── */}
      <header className="app-header">
        <h1 className="app-title">
          <span className="app-title-main">Frontier</span>
          <span className="app-title-sub">Browser Agent Sandbox</span>
        </h1>
        <div className="header-right">
          <span className={`dot ${statusInfo.dot}`} />
          <span className="status-text">{statusInfo.text}</span>
        </div>
      </header>

      {/* ── Body: chat (left) + side panel (right) ─────────── */}
      <main className="app-body">

        {/* LEFT — chat is the primary surface */}
        <section className="col-chat">
          <ChatPanel
            socketEvents={rawEvents}
            activeSessionId={activeSessionId}
            onSessionStart={setActiveSessionId}
          />
        </section>

        {/* RIGHT — action feed + provenance stacked */}
        <section className="col-side">
          <ActionFeed
            actions={actions}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
          <Provenance item={selected} />
        </section>

      </main>
    </div>
  );
}

export default App;
