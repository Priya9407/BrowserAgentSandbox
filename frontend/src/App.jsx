import { useState } from "react";
import { useAgentSocket } from "./services/websocket";
import ChatPanel from "./components/ChatPanel";
import ActionFeed from "./components/ActionFeed";
import Provenance from "./components/Provenance";
import Scene3D from "./components/Scene3D";
import { ArrowRight, Eye, GitBranch, Home, ShieldCheck } from "lucide-react";
import "./App.css";
import logo from "./assets/logo.png"

const STATUS_LABEL = {
  connecting: { dot: "dot-yellow", text: "Connecting…" },
  open:       { dot: "dot-green",  text: "Connected" },
  closed:     { dot: "dot-red",    text: "Disconnected" },
  error:      { dot: "dot-red",    text: "Error" },
};

const HERO_FEATURES = [
  {
    icon: <Eye size={22} strokeWidth={2.2} />,
    title: "Watch every action",
    body: "Each agent step is intercepted before it touches the page.",
  },
  {
    icon: <GitBranch size={22} strokeWidth={2.2} />,
    title: "Trace every instruction",
    body: "Provenance links a decision back to the exact DOM node that caused it.",
  },
  {
    icon: <ShieldCheck size={22} strokeWidth={2.2} />,
    title: "Trust nothing hidden",
    body: "Invisible text, alt-text payloads and off-screen nodes are flagged on sight.",
  },
];

function App() {
  const { status, actions, rawEvents } = useAgentSocket();
  const [selectedId,      setSelectedId]      = useState(null);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [view,            setView]            = useState("landing"); // "landing" | "chat"

  const selected = actions.find((item) => item.action?.action_id === selectedId) || null;
  const statusInfo = STATUS_LABEL[status] || STATUS_LABEL.error;

  return (
    <div className={`app view-${view}`}>
      <Scene3D />

      {/* ── Header ─────────────────────────────────────────── */}
      <header className="app-header">
        <button
          className="brand-home-btn"
          onClick={() => setView("landing")}
          title="Back to home"
        >
          <div className="brand-shield">
            <img src={logo} alt="Aegis Vigilis Logo" className="brand-logo" />
          </div>
          <span className="brand-name">AEGIS VIGILIS <i>The Shield Behind Every Agent</i></span>
        </button>

        <nav className="header-nav">
          {view === "chat" && (
            <button className="nav-btn" onClick={() => setView("landing")}>
              <Home size={14} strokeWidth={2.5} /> Home
            </button>
          )}
          <div className="nav-status">
            <span className={`dot ${statusInfo.dot}`} />
            <span className="status-text">{statusInfo.text}</span>
          </div>
        </nav>
      </header>

      {/* ── Landing view ───────────────────────────────────── */}
      {view === "landing" ? (
        <main className="landing-body">
          <section className="hero-section">
            <div className="hero-copy">
              <span className="hero-tag">AI Browser Agent Security</span>
              <h1 className="hero-title">AEGIS&nbsp;VIGILIS</h1>
              <p className="hero-subtitle">
                Gain complete visibility into AI browser automation with real-time action monitoring, provenance tracking, dynamic risk analysis,
                and explainable policy enforcement—all from a single security dashboard.
              </p>
              <div className="hero-features">
                {HERO_FEATURES.map(f => (
                  <div className="hero-card" key={f.title}>
                    <span className="hero-card-icon">{f.icon}</span>
                    <strong>{f.title}</strong>
                    <p>{f.body}</p>
                  </div>
                ))}
              </div>
              <div className="hero-cta">
                <button className="start-chat-btn" onClick={() => setView("chat")}>
                  Start Chatting <ArrowRight size={18} strokeWidth={2.5} />
                </button>
                <p className="hero-cta-sub">
                  No signup needed — pick a demo task or type a goal to watch the agent work.
                </p>
              </div>
            </div>
          </section>
        </main>
      ) : (
        /* ── Chat view ─────────────────────────────────────── */
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
      )}
    </div>
  );
}

export default App;
