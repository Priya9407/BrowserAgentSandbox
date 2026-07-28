import { useEffect, useRef, useState } from "react";

const STATUS_ICON = {
  planning: "🧠",
  step:     "⚙️",
  done:     "✅",
  error:    "❌",
};

// Demo task suggestions — 4 real ordinary tasks (Day 28 D requirement).
// url is the starting page handed to the agent. goal is what the user typed.
const DEMO_TASKS = [
  {
    label: "Product price",
    goal:  "Search for the Sony WH-1000XM5 headphones and tell me the current price",
    url:   "https://www.google.com/search?q=Sony+WH-1000XM5+price",
  },
  {
    label: "Check a flight",
    goal:  "Find the cheapest one-way flight from Delhi to Goa next week and report the price and airline",
    url:   "https://www.google.com/travel/flights/search?tfs=CBwQAhoeEgoyMDI1LTA4LTA0agwIAhIIL20vMDlmMDcaHRIKMjAyNS0wOC0wNHIMCAISCC9tLzAxZmRteA",
  },
  {
    label: "Restaurant hours",
    goal:  "Look up the opening hours of Domino's Pizza in Bangalore and report them",
    url:   "https://www.google.com/search?q=Dominos+Pizza+Bangalore+opening+hours",
  },
  {
    label: "Buy laptop (demo)",
    goal:  "Find the cheapest laptop on this page and add it to the cart",
    url:   null,   // uses the local benign_checkout.html test page
  },
];

export default function ChatPanel({ socketEvents, activeSessionId, onSessionStart }) {
  const [input, setInput]         = useState("");
  const [url, setUrl]             = useState("");
  const [showUrl, setShowUrl]     = useState(false);
  const [messages, setMessages]   = useState([]);  // { role, text, status?, id }
  const [running, setRunning]     = useState(false);
  const bottomRef                 = useRef(null);
  const inputRef                  = useRef(null);

  // -----------------------------------------------------------------------
  // Consume WebSocket events from the parent (passed down to avoid a second
  // socket connection). Filter to chat_status events for the active session.
  // -----------------------------------------------------------------------
  useEffect(() => {
    if (!socketEvents || socketEvents.length === 0) return;
    const latest = socketEvents[0]; // parent prepends newest first

    if (latest.type !== "chat_status") return;
    if (activeSessionId && latest.session_id !== activeSessionId) return;

    const isTerminal = latest.status === "done" || latest.status === "error";

    setMessages(prev => {
      // Deduplicate: don't append the exact same text twice
      if (prev.length > 0 && prev[prev.length - 1].text === latest.text) return prev;
      return [
        ...prev,
        {
          id:     `${latest.session_id}-${prev.length}`,
          role:   "status",
          status: latest.status,
          text:   latest.text,
        },
      ];
    });

    if (isTerminal) setRunning(false);
  }, [socketEvents, activeSessionId]);

  // Auto-scroll to bottom whenever messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // -----------------------------------------------------------------------
  // Submit
  // -----------------------------------------------------------------------
  const handleSubmit = async (goalText, startUrl) => {
    const goal = (goalText ?? input).trim();
    if (!goal || running) return;

    // startUrl: from a demo chip (may be null for local page),
    //           falls back to the manual URL field, then undefined (backend default).
    const resolvedUrl = startUrl !== undefined ? startUrl : (url.trim() || undefined);

    setInput("");
    setRunning(true);

    // Append the user bubble immediately
    setMessages(prev => [
      ...prev,
      { id: `user-${Date.now()}`, role: "user", text: goal },
    ]);

    try {
      const res = await fetch("http://localhost:8000/chat", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ goal, url: resolvedUrl, headless: false }),
      });
      const data = await res.json();
      onSessionStart?.(data.session_id);
    } catch (err) {
      setMessages(prev => [
        ...prev,
        { id: `err-${Date.now()}`, role: "status", status: "error", text: `Failed to start: ${err.message}` },
      ]);
      setRunning(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleClear = () => {
    setMessages([]);
    setRunning(false);
  };

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------
  return (
    <div className="chat-panel">
      {/* Header */}
      <div className="chat-header">
        <span className="chat-title">Chat</span>
        {messages.length > 0 && (
          <button className="chat-clear-btn" onClick={handleClear} title="Clear chat">
            Clear
          </button>
        )}
      </div>

      {/* Message thread */}
      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-empty">
            <p className="chat-empty-heading">What should the agent do?</p>
            <p className="chat-empty-sub">Type a goal below, or pick a demo task.</p>
            <div className="demo-chips">
              {DEMO_TASKS.map(t => (
                <button
                  key={t.label}
                  className="demo-chip"
                  onClick={() => handleSubmit(t.goal, t.url)}
                  disabled={running}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map(msg => {
          if (msg.role === "user") {
            return (
              <div key={msg.id} className="chat-bubble chat-bubble-user">
                {msg.text}
              </div>
            );
          }

          // status line (planning / step / done / error)
          const icon = STATUS_ICON[msg.status] ?? "•";
          const cls  = `chat-status-line chat-status-${msg.status}`;
          return (
            <div key={msg.id} className={cls}>
              <span className="chat-status-icon">{icon}</span>
              <span className="chat-status-text">{msg.text}</span>
            </div>
          );
        })}

        {/* Typing indicator while agent is running */}
        {running && (
          <div className="chat-status-line chat-status-step chat-typing">
            <span className="chat-status-icon">⚙️</span>
            <span className="chat-typing-dots">
              <span /><span /><span />
            </span>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Optional URL override */}
      {showUrl && (
        <div className="chat-url-row">
          <input
            className="chat-url-input"
            type="text"
            placeholder="Starting URL (optional)"
            value={url}
            onChange={e => setUrl(e.target.value)}
          />
        </div>
      )}

      {/* Input bar */}
      <div className="chat-input-row">
        <button
          className="chat-url-toggle"
          title={showUrl ? "Hide URL field" : "Set starting URL"}
          onClick={() => setShowUrl(v => !v)}
        >
          🔗
        </button>
        <textarea
          ref={inputRef}
          className="chat-input"
          rows={1}
          placeholder="Type a goal and press Enter…"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={running}
        />
        <button
          className="chat-send-btn"
          onClick={() => handleSubmit()}
          disabled={!input.trim() || running}
        >
          {running ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}
