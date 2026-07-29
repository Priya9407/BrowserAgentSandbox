/**
 * sidepanel.js — Frontier Agent Side Panel Logic
 *
 * No build step. Runs as a plain script inside sidepanel.html.
 *
 * Flow
 * ----
 * 1. On load: GET_TAB_CONTEXT from background → store tab url/title/visibleText.
 * 2. User types a goal and hits Send.
 * 3. POST /extension/chat with { goal, tab_url, tab_title, visible_text }.
 * 4. Backend returns { session_id }.
 * 5. WebSocket /extension/ws receives chat_status messages for that session_id.
 * 6. Each message is rendered as a status line in the thread.
 * 7. For action events, background.js is asked to EXECUTE_ACTION in the tab.
 * 8. SET_AGENT_ACTIVE toggled on start/done/error.
 *
 * WebSocket message types consumed
 * ----------------------------------
 *   { type: "chat_status", session_id, status, text }
 *     status: "planning" | "step" | "done" | "error"
 *   { type: "action", session_id, action, policy }
 *     → forwarded to background for execution in the current tab
 */

const BACKEND_HTTP = "http://localhost:8000";
const BACKEND_WS   = "ws://localhost:8000";

// ── DOM refs ────────────────────────────────────────────────────────────────
const messagesEl     = document.getElementById("messages");
const goalInput      = document.getElementById("goal-input");
const sendBtn        = document.getElementById("send-btn");
const wsDot          = document.getElementById("ws-dot");
const wsLabel        = document.getElementById("ws-label");
const tabUrlLabel    = document.getElementById("tab-url-label");
const refreshCtxBtn  = document.getElementById("refresh-context-btn");
const captchaBanner  = document.getElementById("captcha-banner");
const captchaResumeBtn = document.getElementById("captcha-resume-btn");

// ── State ────────────────────────────────────────────────────────────────────
let ws              = null;
let sessionId       = null;
let running         = false;
let tabContext      = { url: "", title: "", visibleText: "" };

// ── Boot ─────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  _connectWS();
  _refreshTabContext();
  _wireUI();
});

// ── WebSocket ────────────────────────────────────────────────────────────────
function _connectWS() {
  _setWsStatus("connecting");

  ws = new WebSocket(`${BACKEND_WS}/extension/ws`);

  ws.onopen = () => {
    _setWsStatus("open");
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      _handleWsMessage(msg);
    } catch (_) { /* non-JSON ping */ }
  };

  ws.onclose = () => {
    _setWsStatus("closed");
    // Reconnect after 2 s
    setTimeout(_connectWS, 2000);
  };

  ws.onerror = () => {
    _setWsStatus("error");
  };
}

function _setWsStatus(status) {
  const map = {
    connecting: { dot: "dot-yellow", label: "Connecting…" },
    open:       { dot: "dot-green",  label: "Connected"   },
    closed:     { dot: "dot-red",    label: "Disconnected" },
    error:      { dot: "dot-red",    label: "Error"        },
  };
  const s = map[status] ?? map.error;
  wsDot.className   = `dot ${s.dot}`;
  wsLabel.textContent = s.label;
}

// ── Handle incoming WS messages ───────────────────────────────────────────────
function _handleWsMessage(msg) {
  // Only process messages for the active session
  if (msg.session_id && msg.session_id !== sessionId) return;

  if (msg.type === "chat_status") {
    const { status, text } = msg;
    _appendStatus(status, text);

    if (status === "done") {
      _setRunning(false);
      _setAgentActive(false);
      _hideCaptcha();
    } else if (status === "error") {
      _setRunning(false);
      _setAgentActive(false);
      _hideCaptcha();
    } else if (text?.includes("CAPTCHA")) {
      _showCaptcha();
    }
  }

  if (msg.type === "action" && msg.action && msg.policy) {
    // Forward the action to the content script via background
    const { action, policy } = msg;

    // Only execute if ALLOW
    if (policy?.decision === "ALLOW") {
      chrome.runtime.sendMessage(
        { type: "EXECUTE_ACTION", action },
        (result) => {
          if (!result?.ok) {
            _appendStatus("error", `Action failed: ${result?.error ?? "unknown"}`);
          }
        }
      );
    } else if (policy?.decision === "ESCALATE") {
      _appendStatus("step", `⚠️ Escalated: ${policy.reason ?? "requires approval"}`);
    } else if (policy?.decision === "DENY") {
      _appendStatus("error", `🚫 Blocked: ${policy.reason ?? "policy denied"}`);
    }
  }
}

// ── Tab context ───────────────────────────────────────────────────────────────
function _refreshTabContext() {
  tabUrlLabel.textContent = "Loading…";

  chrome.runtime.sendMessage({ type: "GET_TAB_CONTEXT" }, (ctx) => {
    if (chrome.runtime.lastError || !ctx || ctx.error) {
      tabUrlLabel.textContent = "Could not read tab";
      return;
    }
    tabContext = ctx;
    // Show just the hostname to keep the pill short
    try {
      tabUrlLabel.textContent = new URL(ctx.url).hostname || ctx.url;
    } catch {
      tabUrlLabel.textContent = ctx.url || "Unknown tab";
    }
    tabUrlLabel.title = ctx.url;
  });
}

// ── UI wiring ─────────────────────────────────────────────────────────────────
function _wireUI() {
  // Enable send only when there's text
  goalInput.addEventListener("input", () => {
    sendBtn.disabled = goalInput.value.trim() === "" || running;
  });

  // Enter submits (shift+enter = newline)
  goalInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!sendBtn.disabled) _submit();
    }
  });

  sendBtn.addEventListener("click", _submit);
  refreshCtxBtn.addEventListener("click", _refreshTabContext);
  captchaResumeBtn.addEventListener("click", _resumeCaptcha);
}

// ── Submit ────────────────────────────────────────────────────────────────────
async function _submit() {
  const goal = goalInput.value.trim();
  if (!goal || running) return;

  goalInput.value = "";
  sendBtn.disabled = true;

  _appendBubble(goal);
  _setRunning(true);
  _setAgentActive(true);
  _hideCaptcha();

  try {
    const res = await fetch(`${BACKEND_HTTP}/extension/chat`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        goal,
        tab_url:      tabContext.url,
        tab_title:    tabContext.title,
        visible_text: tabContext.visibleText,
      }),
    });

    if (!res.ok) {
      const txt = await res.text().catch(() => res.statusText);
      throw new Error(`Server ${res.status}: ${txt}`);
    }

    const data = await res.json();
    sessionId = data.session_id;
  } catch (err) {
    _appendStatus("error", `Failed to start: ${err.message}`);
    _setRunning(false);
    _setAgentActive(false);
  }
}

// ── Captcha ───────────────────────────────────────────────────────────────────
function _showCaptcha() {
  captchaBanner.classList.remove("hidden");
}

function _hideCaptcha() {
  captchaBanner.classList.add("hidden");
}

async function _resumeCaptcha() {
  if (!sessionId) return;
  _hideCaptcha();
  try {
    await fetch(`${BACKEND_HTTP}/resolve-captcha`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ session_id: sessionId }),
    });
  } catch (err) {
    _appendStatus("error", `Resume failed: ${err.message}`);
    _showCaptcha();
  }
}

// ── Agent active indicator ────────────────────────────────────────────────────
function _setAgentActive(active) {
  chrome.runtime.sendMessage({ type: "SET_AGENT_ACTIVE", active });
}

// ── Running state ─────────────────────────────────────────────────────────────
function _setRunning(value) {
  running = value;
  goalInput.disabled = value;
  sendBtn.disabled   = value || goalInput.value.trim() === "";

  // Typing indicator
  const existingTyping = document.getElementById("__typing-indicator");
  if (value && !existingTyping) {
    const row = document.createElement("div");
    row.id = "__typing-indicator";
    row.className = "status-line status-step typing-row";
    row.innerHTML = `
      <span class="status-icon">⚙️</span>
      <span class="typing-dots">
        <span></span><span></span><span></span>
      </span>`;
    messagesEl.appendChild(row);
    _scrollBottom();
  } else if (!value) {
    existingTyping?.remove();
  }
}

// ── Rendering helpers ──────────────────────────────────────────────────────────
const STATUS_ICON = { planning: "🧠", step: "⚙️", done: "✅", error: "❌" };

function _appendBubble(text) {
  const div = document.createElement("div");
  div.className = "bubble bubble-user";
  div.textContent = text;
  messagesEl.appendChild(div);
  _scrollBottom();
}

function _appendStatus(status, text) {
  // Remove typing indicator before appending final messages
  if (status === "done" || status === "error") {
    document.getElementById("__typing-indicator")?.remove();
  }

  const icon = STATUS_ICON[status] ?? "•";
  const div = document.createElement("div");
  div.className = `status-line status-${status}`;
  div.innerHTML = `
    <span class="status-icon">${icon}</span>
    <span class="status-text">${_escapeHtml(text)}</span>`;
  messagesEl.appendChild(div);
  _scrollBottom();
}

function _scrollBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function _escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
