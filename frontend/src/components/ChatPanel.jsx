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
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  HelpCircle,
  Link2,
  Loader2,
  Send,
  Trash2,
} from "lucide-react";

const STATUS_ICON = {
  planning: <Loader2 size={13} className="spin" />,
  done:     <CheckCircle2 size={13} />,
  error:    <AlertCircle size={13} />,
};

// Demo task suggestions. Most use hardwired scripts for deterministic demos;
// the quiz shortcut deliberately uses the live LLM path so it reasons about
// the questions currently shown on the target page.
//
// A chip with `demo_task_key` maps to a pre-scripted demo in
// backend/app/agent/demo_scripts.py and posts to POST /chat-demo. Chips with
// a URL but no key post to the live /chat endpoint, preserving LLM reasoning
// and the same policy/gate/execute pipeline.
const DEMO_TASKS = [
  {
    label: "Complete quiz (LLM)",
    goal:  "Go to this website and complete the quiz by answering every visible question: https://priya9407.github.io/QuizForFrontier/",
    url:   "https://priya9407.github.io/QuizForFrontier/",
  },
  {
    label: "Product price",
    demo_task_key: "product_price",
    goal:  "Search for the SoundWave Buds Lite earbuds and tell me the current price",
  },
  {
    label: "Check a flight",
    demo_task_key: "check_flight",
    goal:  "Find a flight result on SkyHigh Flights and report the price",
  },
  {
    label: "Buy laptop",
    demo_task_key: "buy_laptop",
    goal:  "Buy the laptop listed on the shopping page",
  },
  {
    label: "Restaurant hours",
    demo_task_key: "restaurant_hours",
    goal:  "Look up the opening hours of Spice Garden restaurant and report them",
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
  const [captchaPending, setCaptchaPending] = useState(false);
  const [askPending, setAskPending]   = useState(false);
  const [askQuestion, setAskQuestion] = useState("");
  const [askOptions, setAskOptions]   = useState([]);
  const [askAnswer, setAskAnswer]     = useState("");
  // Clarification state (pre-task questions)
  const [clarifyQueue, setClarifyQueue]   = useState([]); // [{question, index, total}]
  const [clarifyAnswer, setClarifyAnswer] = useState("");
  const clarifySessionRef = useRef(null);
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

    // ── Questions (any shape — always show an input box) ──────────────────
    // 1. Legacy pre-task clarifier: status="ask" with ask_index/ask_total.
    //    Route into the clarify queue (answered one at a time via
    //    /resolve-clarification), matching the original protocol.
    // 2. Live agent question: step_event.ask_question (current backend).
    //    Route into the ask banner (options + Other + text box).
    // 3. Bare "ask" text with no structured event: fall back to the ask
    //    banner so the user ALWAYS gets an input box.
    if (status === "ask") {
      if (se?.ask_question != null && se?.ask_index != null) {
        clarifySessionRef.current = evt.session_id;
        setClarifyQueue(prev => {
          if (prev.some(q => q.index === se.ask_index)) return prev;
          return [...prev, { question: se.ask_question, index: se.ask_index, total: se.ask_total }];
        });
      } else {
        setAskPending(true);
        setAskQuestion(se?.ask_question ?? text);
        setAskOptions(Array.isArray(se?.ask_options) ? se.ask_options : []);
        setAskAnswer("");
      }
      return; // never render an ask as a bare flat line without an input box
    }

    if (se?.ask_question) {
      setAskPending(true);
      setAskQuestion(se.ask_question);
      setAskOptions(Array.isArray(se.ask_options) ? se.ask_options : []);
      setAskAnswer("");
    }

    // Once all questions answered (status=planning with outcome=resolved), clear queue
    if (status === "planning" && se && se.outcome === "resolved") {
      setClarifyQueue([]);
      clarifySessionRef.current = null;
    }

    // ── Update step timeline ────────────────────────────────────────────────
    if (se && typeof se.step_number === "number") {
      // Detect re-plan: the re-plan recovery emits "↻ Re-planning" in text
      const isReplan =
        text.startsWith("↻") || (se.outcome === "failed" && replanSeenRef.current);

      // CAPTCHA or Ask pause/resume — show or hide the Resume banners
      if (se.outcome === "paused") {
        if (!se.ask_question) {
          setCaptchaPending(true);
        }
      } else {
        setCaptchaPending(false);
        setAskPending(false);
        setAskOptions([]);
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
  // demoTaskKey — when provided, the chip runs the hardwired /chat-demo script
  // (deterministic, no LLM). Otherwise it falls back to the live /chat path.
  const handleSubmit = async (goalText, startUrl, demoTaskKey) => {
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
      // ── Hardwired demo path: POST /chat-demo with the script key ──────
      if (demoTaskKey) {
        const res = await fetch("http://localhost:8000/chat-demo", {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ demo_task_key: demoTaskKey, headless: false }),
        });

        if (!res.ok) {
          const text = await res.text().catch(() => res.statusText);
          throw new Error(`Server returned ${res.status}: ${text}`);
        }

        const data = await res.json();
        if (data.error) throw new Error(data.error);
        onSessionStart?.(data.session_id);
        return;
      }

      // ── Live LLM path ──────────────────────────────────────────────────
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
    setAskPending(false);
    setClarifyQueue([]);
    setClarifyAnswer("");
    clarifySessionRef.current = null;
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

  const handleSubmitAsk = async (e) => {
    e.preventDefault();
    if (!activeSessionId) return;
    setAskPending(false);
    try {
      await fetch("http://localhost:8000/resolve-ask", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ session_id: activeSessionId, answer: askAnswer }),
      });
      setAskAnswer("");
    } catch (err) {
      setMessages(prev => [
        ...prev,
        {
          id:     `err-${Date.now()}`,
          role:   "status",
          status: "error",
          text:   `Failed to submit answer: ${err.message}`,
        },
      ]);
      setAskPending(true);
    }
  };

  const handleSubmitClarification = async (e) => {
    e.preventDefault();
    if (!clarifySessionRef.current || !clarifyQueue.length) return;
    const current = clarifyQueue[0]; // answer them one at a time
    const sessionId = clarifySessionRef.current;
    const answer = clarifyAnswer.trim();
    if (!answer) return;

    // Remove the first question from the queue
    setClarifyQueue(prev => prev.slice(1));
    setClarifyAnswer("");

    try {
      const resp = await fetch("http://localhost:8000/resolve-clarification", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          question_index: current.index,
          answer,
        }),
      });
      const data = await resp.json();
      if (data.status === "started") {
        // Agent is now running
        setRunning(true);
      }
    } catch (err) {
      console.error("Failed to submit clarification:", err);
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
            <Trash2 size={13} /> Clear
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
                  onClick={() => handleSubmit(t.goal, t.url, t.demo_task_key)}
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
                {Math.max(...stepTimeline.map(s => s.totalSteps || stepTimeline.length), stepTimeline.length)} done
              </span>
              <span className="tl-card-chevron">
                {timelineOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
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
                {summary.status === "done" ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
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

        {/* ── Pre-task Clarification banner ─────────────────────────── */}
        {clarifyQueue.length > 0 && (() => {
          const current = clarifyQueue[0];
          const answeredCount = current.total - clarifyQueue.length;
          return (
            <div className="captcha-banner" style={{ borderColor: "#6366f1", background: "rgba(99,102,241,0.12)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "6px" }}>
                <span className="captcha-banner-icon"><HelpCircle size={18} /></span>
                <span style={{ fontSize: "11px", color: "#a5b4fc", fontWeight: 600 }}>
                  Question {answeredCount + 1} of {current.total}
                </span>
              </div>
              <span className="captcha-banner-text" style={{ color: "#e0e7ff" }}>
                {current.question}
              </span>
              <form onSubmit={handleSubmitClarification} style={{ display: "flex", gap: "8px", marginTop: "8px", width: "100%" }}>
                <input
                  type="text"
                  value={clarifyAnswer}
                  onChange={e => setClarifyAnswer(e.target.value)}
                  style={{ flex: 1, padding: "6px 10px", borderRadius: "6px", border: "1px solid #6366f1", background: "rgba(99,102,241,0.15)", color: "white" }}
                  placeholder="Your answer…"
                  autoFocus
                />
                <button type="submit" className="captcha-resume-btn" style={{ background: "#6366f1" }}>
                  {answeredCount + 1 < current.total ? "Next →" : "Start Task ▶"}
                </button>
              </form>
            </div>
          );
        })()}

        {/* ── CAPTCHA pause banner ─────────────────────────────────────── */}
        {captchaPending && (
          <div className="captcha-banner">
            <span className="captcha-banner-icon"><AlertTriangle size={18} /></span>
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

        {/* ── Ask User banner — options + Other + text box ────────── */}
        {askPending && (
          <div className="captcha-banner" style={{ alignItems: "flex-start", flexDirection: "column" }}>
            <div style={{ display: "flex", alignItems: "flex-start", gap: "10px", width: "100%" }}>
              <span className="captcha-banner-icon">?</span>
              <span className="captcha-banner-text">{askQuestion}</span>
            </div>

            {askOptions.length > 0 && (
              <div className="ask-options" style={{ display: "flex", flexWrap: "wrap", gap: "8px", marginTop: "6px" }}>
                {askOptions.map(opt => (
                  <button
                    key={opt}
                    type="button"
                    onClick={() => setAskAnswer(opt)}
                    style={{
                      border: askAnswer === opt ? "1px solid #38d9a9" : "1px solid rgba(255,255,255,0.2)",
                      background: askAnswer === opt ? "rgba(56,217,169,0.25)" : "rgba(255,255,255,0.05)",
                      color: askAnswer === opt ? "#38d9a9" : "#d6cfdf",
                      borderRadius: "999px",
                      padding: "6px 14px",
                      fontSize: "12px",
                      fontWeight: 700,
                      cursor: "pointer",
                    }}
                  >
                    {opt}
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => { setAskAnswer(""); document.getElementById("__ask-text-input")?.focus(); }}
                  style={{
                    border: "1px dashed rgba(255,255,255,0.3)",
                    background: "transparent",
                    color: "#b6adc7",
                    borderRadius: "999px",
                    padding: "6px 14px",
                    fontSize: "12px",
                    fontWeight: 700,
                    cursor: "pointer",
                  }}
                >
                  Other
                </button>
              </div>
            )}

            <form onSubmit={handleSubmitAsk} style={{ display: "flex", gap: "8px", marginTop: "8px", width: "100%" }}>
              <input
                id="__ask-text-input"
                type="text"
                value={askAnswer}
                onChange={e => setAskAnswer(e.target.value)}
                style={{ flex: 1, padding: "6px", borderRadius: "4px", border: "1px solid #ccc", background: "rgba(255, 255, 255, 0.1)", color: "white" }}
                placeholder="Type your answer, or pick an option..."
                autoFocus
              />
              <button
                type="submit"
                className="captcha-resume-btn"
                disabled={!askAnswer.trim()}
              >
                Submit Answer
              </button>
            </form>
          </div>
        )}

        {/* Typing indicator */}          {running && (
          <div className="chat-status-line chat-status-step chat-typing">
            <span className="chat-status-icon"><Loader2 size={13} className="spin" /></span>
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
          <Link2 size={15} />
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
          {running ? <Loader2 size={15} className="spin" /> : <><Send size={15} /> Send</>}
        </button>
      </div>
    </div>
  );
}
