/**
 * ChatPanel.jsx 
 *
 * Changes from the previous version:
 *  - Consumes the `step_event` field on chat_status WebSocket messages.
 *  - Maintains a `stepTimeline` array (keyed by step_number) that is
 *    upserted on every step_event — so the timeline mutates in place
 *    (running → success/failed/skipped) rather than appending duplicates.
 *  - Renders <StepTimeline> inside the message thread immediately after the
 *    "planning" bubble, so the full history of what happened is always visible.
 *  - Flat status lines (planning/done/error) are still shown for non-step events.
 */

import { useEffect, useRef, useState } from "react";
import StepTimeline from "./StepTimeline";

const STATUS_ICON = {
  planning: "🧠",
  done:     "✅",
  error:    "❌",
};

// Demo task suggestions — prefer simple, reliable pages for demo lock
const DEMO_TASKS = [
  {
    label: "Product price",
    goal:  "Search for the Sony WH-1000XM5 headphones and tell me the current price",
    // Use a simple search results page (less dynamic than travel widgets)
    url:   "https://www.google.com/search?q=Sony+WH-1000XM5+price",
  },
  {
    label: "Check a flight (simple)",
    goal:  "Find one flight result for Delhi to Goa next week and report the price and airline",
    // Use a generic search for flights instead of the Google Flights widget which can be flaky
    url:   "https://www.google.com/search?q=delhi+to+goa+flight+one+way+next+week",
  },
  {
    label: "Restaurant hours",
    goal:  "Look up the opening hours of Domino's Pizza in Bangalore and report them",
    url:   "https://www.google.com/search?q=Dominos+Pizza+Bangalore+opening+hours",
  },
  {
    label: "Example site",
    goal:  "Open example.com and tell me the page title",
    // A static, highly reliable page for demos
    url:   "https://example.com/",
  },
];

// ---------------------------------------------------------------------------
// Timeline helpers
// ---------------------------------------------------------------------------

/**
 * Upsert a step into the timeline array.
 *
 * Rules:
 *  - First time we see a step_number: append a new entry.
 *  - Subsequent events for the same step_number: update outcome/retry in place
 *    so the user sees the dot change colour without the list growing.
 *  - A new entry after a re-plan (isReplan=true) always appends, because it
 *    belongs to a different plan and might have the same step_number.
 */
function upsertStep(prev, evt, isReplan) {
  const entry = {
    key:        `${evt.step_number}-${isReplan ? "rp-" + Date.now() : "orig"}`,
    stepNumber: evt.step_number,
    totalSteps: evt.total_steps,
    goal:       evt.goal,
    outcome:    evt.outcome,
    retry:      evt.retry ?? 0,
    isReplan,
  };

  if (isReplan) {
    return [...prev, entry];
  }

  const existingIdx = prev.findIndex(
    s => s.stepNumber === evt.step_number && !s.isReplan,
  );

  if (existingIdx === -1) {
    return [...prev, entry];
  }

  // Update in-place — only upgrade outcome (don't regress success → running)
  const existingOutcome = prev[existingIdx].outcome;
  const finalOutcome =
    existingOutcome === "success" ? "success" : entry.outcome;

  const updated = [...prev];
  updated[existingIdx] = {
    ...updated[existingIdx],
    outcome: finalOutcome,
    retry:   Math.max(updated[existingIdx].retry, entry.retry),
    goal:    entry.goal,          // goal text may be refined on retry
  };
  return updated;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ChatPanel({ socketEvents, activeSessionId, onSessionStart }) {
  const [input, setInput]             = useState("");
  const [url, setUrl]                 = useState("");
  const [showUrl, setShowUrl]         = useState(false);
  const [messages, setMessages]       = useState([]);   // flat chat messages
  const [stepTimeline, setTimeline]   = useState([]);   // structured step history
  const [running, setRunning]         = useState(false);
  const [timelineOpen, setTimelineOpen] = useState(true);
  const [summary, setSummary]         = useState(null);  // done-summary card data
  const [captchaPending, setCaptchaPending] = useState(false); // human needs to solve a CAPTCHA
  const replanSeenRef                 = useRef(false);  // track whether a re-plan occurred this run
  const stepTimelineRef               = useRef([]);     // mirrors stepTimeline, read at terminal event
  const taskStartRef                  = useRef(null);    // Date.now() when a task starts, for elapsed time
  const bottomRef                     = useRef(null);
  const inputRef                      = useRef(null);

  // -------------------------------------------------------------------------
  // Consume WebSocket events
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (!socketEvents || socketEvents.length === 0) return;
    const evt = socketEvents[0];

    if (evt.type !== "chat_status") return;
    if (activeSessionId && evt.session_id !== activeSessionId) return;

    const { status, text, step_event: se } = evt;

    // ── Update step timeline ────────────────────────────────────────────────
    if (se && typeof se.step_number === "number") {
      // Detect re-plan: the re-plan recovery emits "↻ Re-planning" in text
      const isReplan =
        text.startsWith("↻") || (se.outcome === "failed" && replanSeenRef.current);

      // CAPTCHA pause/resume — show or hide the Resume banner
      if (se.outcome === "paused") {
        setCaptchaPending(true);
      } else if (captchaPending) {
        setCaptchaPending(false);
      }

      if (text.startsWith("↻ New plan")) {
        replanSeenRef.current = true;
      }

      setTimeline(prev => {
        const next = upsertStep(prev, se, isReplan);
        stepTimelineRef.current = next;
        return next;
      });

      // Step events don't add a flat message — the timeline IS the history.
      return;
    }

    // ── Flat message (planning / done / error / re-plan announcement) ───────
    const isTerminal = status === "done" || status === "error";
    if (isTerminal) {
      setRunning(false);
      replanSeenRef.current = false;

      // Build the done-summary card from the timeline gathered so far.
      const timeline = stepTimelineRef.current;
      const successCount = timeline.filter(s => s.outcome === "success").length;
      const failCount = timeline.filter(
        s => s.outcome === "failed" || s.outcome === "skipped"
      ).length;
      const elapsedSeconds = taskStartRef.current
        ? ((Date.now() - taskStartRef.current) / 1000).toFixed(1)
        : null;

      setSummary({
        status,
        text,
        successCount,
        failCount,
        totalSteps: timeline.length,
        elapsedSeconds,
      });
    }

    // Don't repeat identical consecutive messages
    setMessages(prev => {
      if (prev.length > 0 && prev[prev.length - 1].text === text) return prev;
      return [
        ...prev,
        {
          id:     `${evt.session_id ?? "s"}-${Date.now()}-${prev.length}`,
          role:   "status",
          status,
          text,
        },
      ];
    });
  }, [socketEvents, activeSessionId]);

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, stepTimeline]);

  // -------------------------------------------------------------------------
  // Submit
  // -------------------------------------------------------------------------
  const handleSubmit = async (goalText, startUrl) => {
    const goal = (goalText ?? input).trim();
    if (!goal || running) return;

    const resolvedUrl =
      startUrl !== undefined ? startUrl : url.trim() || undefined;

    setInput("");
    setRunning(true);
    setTimeline([]);
    setSummary(null);
    setCaptchaPending(false);
    stepTimelineRef.current = [];
    taskStartRef.current = Date.now();
    replanSeenRef.current = false;

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

      // Surface HTTP-level failures clearly
      if (!res.ok) {
        const text = await res.text().catch(() => res.statusText);
        throw new Error(`Server returned ${res.status}: ${text}`);
      }

      const data = await res.json();
      onSessionStart?.(data.session_id);
    } catch (err) {
      setMessages(prev => [
        ...prev,
        {
          id:     `err-${Date.now()}`,
          role:   "status",
          status: "error",
          text:   `Failed to start: ${err.message}`,
        },
      ]);
      setRunning(false);
    }
  };

  const handleKeyDown = e => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleClear = () => {
    setMessages([]);
    setTimeline([]);
    setSummary(null);
    setCaptchaPending(false);
    stepTimelineRef.current = [];
    taskStartRef.current = null;
    setRunning(false);
    replanSeenRef.current = false;
  };

  // Human clicks "I solved it — Resume" after completing a CAPTCHA
  // challenge in the visible browser window. This never solves anything
  // itself — it just signals the paused agent loop to continue.
  const handleResumeCaptcha = async () => {
    if (!activeSessionId) return;
    setCaptchaPending(false);
    try {
      await fetch("http://localhost:8000/resolve-captcha", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ session_id: activeSessionId }),
      });
    } catch (err) {
      setMessages(prev => [
        ...prev,
        {
          id:     `err-${Date.now()}`,
          role:   "status",
          status: "error",
          text:   `Failed to resume: ${err.message}`,
        },
      ]);
      setCaptchaPending(true);
    }
  };

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------
  const hasContent = messages.length > 0 || stepTimeline.length > 0;

  return (
    <div className="chat-panel">
      {/* Header */}
      <div className="chat-header">
        <span className="chat-title">Chat</span>
        {hasContent && (
          <button
            className="chat-clear-btn"
            onClick={handleClear}
            title="Clear chat"
          >
            Clear
          </button>
        )}
      </div>

      {/* Message thread */}
      <div className="chat-messages">
        {/* Empty state */}
        {!hasContent && (
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

        {/* Flat messages (user bubbles + planning/done/error status lines) */}
        {messages.map(msg => {
          if (msg.role === "user") {
            return (
              <div key={msg.id} className="chat-bubble chat-bubble-user">
                {msg.text}
              </div>
            );
          }
          const icon = STATUS_ICON[msg.status] ?? "•";
          return (
            <div
              key={msg.id}
              className={`chat-status-line chat-status-${msg.status}`}
            >
              <span className="chat-status-icon">{icon}</span>
              <span className="chat-status-text">{msg.text}</span>
            </div>
          );
        })}

        {/* ── Step Timeline ────────────────────────────────────────────── */}
        {stepTimeline.length > 0 && (
          <div className="tl-card">
            {/* Collapsible header */}
            <button
              className="tl-card-header"
              onClick={() => setTimelineOpen(o => !o)}
              aria-expanded={timelineOpen}
              aria-controls="step-timeline-body"
            >
              <span className="tl-card-title">Step History</span>
              <span className="tl-card-meta">
                {stepTimeline.filter(s => s.outcome === "success").length}/
                {stepTimeline.length} done
              </span>
              <span className="tl-card-chevron">
                {timelineOpen ? "▲" : "▼"}
              </span>
            </button>

            {timelineOpen && (
              <div id="step-timeline-body" className="tl-card-body">
                <StepTimeline steps={stepTimeline} />
              </div>
            )}
          </div>
        )}

        {/* ── Done summary card ────────────────────────────────────────── */}
        {summary && !running && (
          <div className={`summary-card summary-card-${summary.status}`}>
            <div className="summary-card-header">
              <span className="summary-card-icon">
                {summary.status === "done" ? "✅" : "❌"}
              </span>
              <span className="summary-card-title">
                {summary.status === "done" ? "Task complete" : "Task ended with an error"}
              </span>
            </div>
            <div className="summary-card-stats">
              <div className="summary-stat">
                <span className="summary-stat-value">{summary.successCount}</span>
                <span className="summary-stat-label">succeeded</span>
              </div>
              <div className="summary-stat">
                <span className="summary-stat-value">{summary.failCount}</span>
                <span className="summary-stat-label">failed / skipped</span>
              </div>
              <div className="summary-stat">
                <span className="summary-stat-value">
                  {summary.elapsedSeconds != null ? `${summary.elapsedSeconds}s` : "—"}
                </span>
                <span className="summary-stat-label">elapsed</span>
              </div>
            </div>
          </div>
        )}

        {/* ── CAPTCHA pause banner ─────────────────────────────────────── */}
        {captchaPending && (
          <div className="captcha-banner">
            <span className="captcha-banner-icon">⏸</span>
            <span className="captcha-banner-text">
              CAPTCHA detected — solve it in the browser window, then click Resume.
            </span>
            <button
              type="button"
              className="captcha-resume-btn"
              onClick={handleResumeCaptcha}
            >
              I solved it — Resume
            </button>
          </div>
        )}

        {/* Typing indicator */}
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
