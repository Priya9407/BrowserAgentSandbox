import { useState } from "react";
import { useAgentSocket } from "./services/websocket";
import ChatPanel from "./components/ChatPanel";
import ActionFeed from "./components/ActionFeed";
import Provenance from "./components/Provenance";
import CustomCursor from "./components/CustomCursor";
import Scene3D from "./components/Scene3D";
import "./App.css";
import logo from "./assets/logo.png"

const STATUS_LABEL = {
  connecting: { dot: "dot-yellow", text: "Connecting…" },
  open:       { dot: "dot-green",  text: "Connected" },
  closed:     { dot: "dot-red",    text: "Disconnected" },
  error:      { dot: "dot-red",    text: "Error" },
};

function App() {
  const { status, actions, rawEvents } = useAgentSocket();
  const [selectedId,      setSelectedId]      = useState(null);
  const [activeSessionId, setActiveSessionId] = useState(null);

  const selected = actions.find((item) => item.action?.action_id === selectedId) || null;
  const statusInfo = STATUS_LABEL[status] || STATUS_LABEL.error;

  const pingBackend = async () => {
    try {
      const r = await fetch("http://localhost:8000/ping");
      const d = await r.json();
      alert(d.status ?? JSON.stringify(d));
    } catch { alert("Backend unreachable"); }
  };

  return (
    <div className="app">
      <CustomCursor />
      <Scene3D />

      {/* ── Header ─────────────────────────────────────────── */}
      <header className="app-header">
        <div className="header-brand">
          <div className="brand-shield">
            <img src={logo} alt="Aegis Vigilis Logo" className="brand-logo" />
          </div>
          <span className="brand-name">AEGIS VIGILIS- <i>The Shield Behind Every Agent</i></span>
        </div>

        <nav className="header-nav">
          <div className="nav-status">
            <span className={`dot ${statusInfo.dot}`} />
            <span className="status-text">{statusInfo.text}</span>
          </div>
        </nav>
      </header>

      <section className="hero-section">
        <div className="hero-copy">
          <p className="hero-subtitle">
            Gain complete visibility into AI browser automation with real-time action monitoring, provenance tracking, dynamic risk analysis,
            and explainable policy enforcement—all from a single security dashboard.
           </p>
          <div className="hero-features">
            <div className="hero-card">
              <strong>Watch every action</strong>
              <p>Each agent step is intercepted before it touches the page.</p>
            </div>
            <div className="hero-card">
              <strong>Trace every instruction</strong>
              <p>Provenance links a decision back to the exact DOM node that caused it.</p>
            </div>
            <div className="hero-card">
              <strong>Trust nothing hidden</strong>
              <p>Invisible text, alt-text payloads and off-screen nodes are flagged on sight.</p>
            </div>
          </div>
        </div>
      </section>

      <main className="app-body">
        <section className="col-chat">
          <ChatPanel
            socketEvents={rawEvents}
            activeSessionId={activeSessionId}
            onSessionStart={setActiveSessionId}
          />
        </section>

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
