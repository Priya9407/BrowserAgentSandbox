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

// ---------------------------------------------------------------------------
// Demo task chips — use local static pages for zero network dependency.
// Each entry with a `demo_task_key` is routed to POST /chat-demo (scripted,
// instant, deterministic).  Entries without a key fall through to POST /chat
// (live LLM pipeline) — none currently, but the shape supports it.
//
// file:// URLs here are informational only (shown in the URL field if the
// user toggles it); the actual page URI is resolved server-side in
// demo_scripts.py so the backend path is always correct regardless of OS.
// ---------------------------------------------------------------------------
const DEMO_TASKS = [
  {
    label:         "Product price",
    goal:          "Search for the SoundWave Buds Lite earbuds and tell me the current price",
    demo_task_key: "product_price",
  },
  {
    label:         "Check a flight",
    goal:          "Find a flight result on SkyHigh Flights and report the price",
    demo_task_key: "check_flight",
  },
  {
    label:         "Buy laptop",
    goal:          "Buy the laptop listed on the shopping page",
    demo_task_key: "buy_laptop",
  },
  {
    label:         "Restaurant hours",
    goal:          "Look up the opening hours of Spice Garden restaurant and report them",
    demo_task_key: "restaurant_hours",
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
  // Now stores ALL questions at once for simultaneous display.
  const [clarifyQueue, setClarifyQueue]   = useState([]); // [{question, index, total}]
  const [clarifyAnswers, setClarifyAnswers] = useState({}); // {[index]: "answer"}
  const [clarifyTotal, setClarifyTotal]   = useState(0);
  const [clarifyTimedOut, setClarifyTimedOut] = useState(false); // true after 10s if questions hang
  const clarifySessionRef = useRef(null);
  const clarifySubmittedRef = useRef(false); // true after user clicks Start Task — prevents late "ask" events from re-opening banner
  const replanSeenRef                 = useRef(false);  // track whether a re-plan occurred this run
  const stepTimelineRef               = useRef([]);     // mirrors stepTimeline, read at terminal event
  const taskStartRef                  = useRef(null);    // Date.now() when a task starts, for elapsed time
  const bottomRef                     = useRef(null);
  const inputRef                      = useRef(null);
  const processedEventCountRef        = useRef(0);    // tracks how many socketEvents have been consumed

  // -------------------------------------------------------------------------
  // Consume WebSocket events
  // -------------------------------------------------------------------------
  // -------------------------------------------------------------------------
  // Consume WebSocket events
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (!socketEvents || socketEvents.length === 0) return;

    const prevCount = processedEventCountRef.current;
    const currentCount = socketEvents.length;
    processedEventCountRef.current = currentCount;
    const newEventCount = currentCount - prevCount;
    if (newEventCount <= 0) return;

    // Events are prepended (newest at index 0). New events are at indices
    // [0, newEventCount). Process them in chronological order (oldest first):
    // iterate from newEventCount-1 down to 0.
    for (let j = newEventCount - 1; j >= 0; j--) {
      const evt = socketEvents[j];

      if (evt.type !== "chat_status") continue;
      if (activeSessionId && evt.session_id !== activeSessionId) continue;

      const { status, text, step_event: se } = evt;

      // ── Clarification questions (pre-task) ────────────────────────────────
      // Skip late "ask" events after the user has already submitted answers
      if (status === "ask" && se && se.ask_question != null && se.ask_index != null) {
        if (clarifySubmittedRef.current) continue; // already submitted — ignore orphaned questions
        clarifySessionRef.current = evt.session_id;
        setClarifyTotal(se.ask_total || 1);
        setClarifyQueue(prev => {
          // Only add if not already in queue
          if (prev.some(q => q.index === se.ask_index)) return prev;
          return [...prev, { question: se.ask_question, index: se.ask_index, total: se.ask_total }];
        });
        continue;
      }

      // Once all questions answered (status=planning with outcome=resolved), clear queue
      if (status === "planning" && se && se.outcome === "resolved") {
        setClarifyQueue([]);
        setClarifyAnswers({});
        setClarifyTotal(0);
        clarifySessionRef.current = null;
      }

      // ── Update step timeline ──────────────────────────────────────────────
      if (se && typeof se.step_number === "number") {
        // Detect re-plan: the re-plan recovery emits "↻ Re-planning" in text
        const isReplan =
          text.startsWith("↻") || (se.outcome === "failed" && replanSeenRef.current);

        // CAPTCHA or Ask pause/resume — show or hide the Resume banners
        if (se.outcome === "paused") {
          if (se.ask_question) {
            setAskPending(true);
            setAskQuestion(se.ask_question);
            setAskOptions(se.ask_options || []);
          } else {
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
        continue;
      }

      // ── Flat message (planning / done / error / re-plan announcement) ─────
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
    }
  }, [socketEvents, activeSessionId]);

  // ── Fallback timeout: if questions don't arrive within 10s, enable the form anyway ──
  useEffect(() => {
    if (clarifyQueue.length > 0 && clarifyQueue.length < clarifyTotal && clarifyTotal > 0) {
      const timer = setTimeout(() => {
        setClarifyTimedOut(true);
      }, 10000);
      return () => clearTimeout(timer);
    } else {
      setClarifyTimedOut(false);
    }
  }, [clarifyQueue.length, clarifyTotal]);

  // Derived — the form is ready when all questions have arrived OR timed out
  const clarifyReady = clarifyQueue.length >= clarifyTotal || clarifyTimedOut;

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, stepTimeline]);

  // -------------------------------------------------------------------------
  // Submit
  // -------------------------------------------------------------------------

  /**
   * handleSubmit — called by both the free-text Send button and the demo chips.
   *
   * @param {string}      [goalText]     - pre-filled goal (demo chips only)
   * @param {string}      [startUrl]     - pre-filled URL (free-text path only)
   * @param {string|null} [demoTaskKey]  - if set, routes to POST /chat-demo
   *                                      instead of POST /chat
   */
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
    clarifySubmittedRef.current = false;  // reset for new task

    setMessages(prev => [
      ...prev,
      { id: `user-${Date.now()}`, role: "user", text: goal },
    ]);

    try {
      // ── Demo chip path → /chat-demo (scripted, no LLM) ─────────────────
      if (demoTaskKey) {
        const res = await fetch("http://localhost:8000/chat-demo", {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ demo_task_key: demoTaskKey, headless: false }),
        });

        if (!res.ok) {
          const errText = await res.text().catch(() => res.statusText);
          throw new Error(`Server returned ${res.status}: ${errText}`);
        }

        const data = await res.json();
        onSessionStart?.(data.session_id);
        return;
      }

      // ── Free-text path → /chat (live LLM pipeline, unchanged) ──────────
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
    setAskOptions([]);
    setClarifyQueue([]);
    setClarifyAnswers({});
    setClarifyTotal(0);
    setClarifyTimedOut(false);
    clarifySessionRef.current = null;
    clarifySubmittedRef.current = false;
    stepTimelineRef.current = [];
    taskStartRef.current = null;
    processedEventCountRef.current = 0;
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
    const sessionId = clarifySessionRef.current;

    // Submit ALL questions in order
    let taskStarted = false;
    for (const q of clarifyQueue) {
      const answer = (clarifyAnswers[q.index] || "").trim();
      if (!answer) {
        // Focus the unanswered question
        const inputEl = document.getElementById(`clarify-input-${q.index}`);
        inputEl?.focus();
        return;
      }

      try {
        const resp = await fetch("http://localhost:8000/resolve-clarification", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: sessionId,
            question_index: q.index,
            answer,
          }),
        });
        const data = await resp.json();
        if (data.status === "started") {
          taskStarted = true;
        }
      } catch (err) {
        console.error("Failed to submit clarification:", err);
      }
    }

    // Build Q&A summary for chat history
    const qaLines = clarifyQueue.map(q =>
      `Q: ${q.question}\nA: ${clarifyAnswers[q.index] || ""}`
    );

    if (taskStarted) {
      // All questions answered — agent is starting now
      setMessages(prev => [
        ...prev,
        {
          id:   `qa-${Date.now()}`,
          role: "user",
          text: qaLines.join("\n\n"),
        },
      ]);
      setRunning(true);
    } else {
      // Partial answers submitted (Continue Anyway with fewer questions)
      // Show Q&A + a status message so the user isn't left staring at stale inputs
      setMessages(prev => [
        ...prev,
        {
          id:   `qa-${Date.now()}`,
          role: "user",
          text: qaLines.join("\n\n"),
        },
        {
          id:   `status-wait-${Date.now()}`,
          role: "status",
          status: "step",
          text: "📤 Answers submitted — waiting for remaining questions to arrive via WebSocket…",
        },
      ]);
    }

    // Mark submitted — prevents late "ask" WebSocket events from re-opening the banner
    clarifySubmittedRef.current = true;

    // Clear the banner in ALL cases — prevent stale-input dead-end
    setClarifyQueue([]);
    setClarifyAnswers({});
    setClarifyTotal(0);
    setClarifyTimedOut(false);
  };

  const handleClarifyChange = (index, value) => {
    setClarifyAnswers(prev => ({ ...prev, [index]: value }));
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
                  onClick={() => handleSubmit(t.goal, undefined, t.demo_task_key)}
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

        {/* ── Pre-task Clarification — ALL questions shown at once ── */}
        {clarifyQueue.length > 0 && (
          <div className="captcha-banner" style={{
            borderColor: "#6366f1",
            background: "rgba(99,102,241,0.12)",
            padding: "16px",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px" }}>
              <span className="captcha-banner-icon">🤖</span>
              <span style={{ fontSize: "11px", color: "#a5b4fc", fontWeight: 600 }}>
                {clarifyQueue.length < clarifyTotal
                  ? `Loading ${clarifyTotal} question${clarifyTotal !== 1 ? "s" : ""}… (${clarifyQueue.length}/${clarifyTotal} received)`
                  : `Please answer ${clarifyTotal} question${clarifyTotal !== 1 ? "s" : ""} to continue`
                }
              </span>
            </div>

            <form onSubmit={handleSubmitClarification}>
              {clarifyQueue.map((q, i) => (
                <div key={q.index} style={{ marginBottom: i < clarifyQueue.length - 1 ? "14px" : "10px" }}>
                  <div style={{
                    fontSize: "13px",
                    color: "#c7d2fe",
                    fontWeight: 500,
                    marginBottom: "6px",
                    lineHeight: 1.4,
                  }}>
                    <span style={{ color: "#818cf8", marginRight: "6px", fontWeight: 700 }}>
                      {i + 1}.
                    </span>
                    {q.question}
                  </div>
                  <input
                    id={`clarify-input-${q.index}`}
                    type="text"
                    value={clarifyAnswers[q.index] || ""}
                    onChange={e => handleClarifyChange(q.index, e.target.value)}
                    disabled={clarifyQueue.length < clarifyTotal}
                    style={{
                      width: "100%",
                      padding: "8px 12px",
                      borderRadius: "8px",
                      border: "1px solid #4f46e5",
                      background: clarifyQueue.length < clarifyTotal
                        ? "rgba(99,102,241,0.06)"
                        : "rgba(99,102,241,0.12)",
                      color: "white",
                      fontSize: "13px",
                      outline: "none",
                      boxSizing: "border-box",
                      opacity: clarifyQueue.length < clarifyTotal ? 0.5 : 1,
                    }}
                    placeholder={clarifyQueue.length < clarifyTotal ? "Loading…" : "Your answer…"}
                    autoFocus={i === 0 && clarifyQueue.length >= clarifyTotal}
                  />
                </div>
              ))}

              {/* Show loading spinner while questions are still arriving */}
              {!clarifyReady && clarifyQueue.length < clarifyTotal && (
                <>
                  <div style={{
                    textAlign: "center",
                    padding: "12px 0 4px",
                    fontSize: "12px",
                    color: "#a5b4fc",
                  }}>
                    <span style={{ animation: "pulse 1.5s ease-in-out infinite", display: "inline-block" }}>
                      ⏳ Receiving questions…
                    </span>
                  </div>
                  {/* „Continue anyway“ button when loading hangs */}
                  <button
                    type="button"
                    onClick={() => setClarifyTimedOut(true)}
                    style={{
                      background: "transparent",
                      border: "1px solid #6366f1",
                      color: "#a5b4fc",
                      width: "100%",
                      marginTop: "4px",
                      padding: "8px 0",
                      fontWeight: 600,
                      fontSize: "12px",
                      borderRadius: "8px",
                      cursor: "pointer",
                    }}
                  >
                    Continue anyway →
                  </button>
                </>
              )}

              {/* Show Start Task when ready (all questions arrived OR timed out) */}
              {clarifyReady && (
                <>
                  {clarifyTimedOut && (
                    <div style={{
                      textAlign: "center",
                      padding: "6px 0 8px",
                      fontSize: "11px",
                      color: "#f59e0b",
                      fontWeight: 500,
                    }}>
                      ⚠ Not all questions loaded — answering what we have
                    </div>
                  )}
                  <button
                    type="submit"
                    className="captcha-resume-btn"
                    style={{
                      background: "#6366f1",
                      width: "100%",
                      marginTop: "4px",
                      padding: "10px 0",
                      fontWeight: 600,
                    }}
                  >
                    Start Task ▶
                  </button>
                </>
              )}
            </form>
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

        {/* ── Ask User banner ─────────────────────────────────────── */}
        {askPending && (
          <div className="captcha-banner">
            <span className="captcha-banner-icon">❓</span>
            <span className="captcha-banner-text">
              {askQuestion}
            </span>

            {/* Check if there are clickable options — render chips */}
            {(askOptions.length > 0) ? (
              <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", marginTop: "8px", width: "100%" }}>
                {askOptions.map((opt, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={async () => {
                      setAskAnswer(opt);
                      setAskPending(false);
                      if (activeSessionId) {
                        try {
                          await fetch("http://localhost:8000/resolve-ask", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ session_id: activeSessionId, answer: opt }),
                          });
                        } catch (err) {
                          console.error("Failed to submit choice:", err);
                        }
                      }
                    }}
                    style={{
                      background: "rgba(99,102,241,0.15)",
                      border: "1px solid #6366f1",
                      borderRadius: "8px",
                      padding: "8px 14px",
                      color: "#c7d2fe",
                      fontSize: "13px",
                      fontWeight: 600,
                      cursor: "pointer",
                      transition: "background 0.15s",
                      textAlign: "left",
                    }}
                    onMouseEnter={e => e.target.style.background = "rgba(99,102,241,0.3)"}
                    onMouseLeave={e => e.target.style.background = "rgba(99,102,241,0.15)"}
                  >
                    {opt}
                  </button>
                ))}
              </div>
            ) : (
              <form onSubmit={handleSubmitAsk} style={{ display: "flex", gap: "8px", marginTop: "8px", width: "100%" }}>
                <input
                  type="text"
                  value={askAnswer}
                  onChange={e => setAskAnswer(e.target.value)}
                  style={{ flex: 1, padding: "6px", borderRadius: "4px", border: "1px solid #ccc", background: "rgba(255, 255, 255, 0.1)", color: "white" }}
                  placeholder="Type your answer here..."
                  autoFocus
                />
                <button
                  type="submit"
                  className="captcha-resume-btn"
                >
                  Submit Answer
                </button>
              </form>
            )}
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
