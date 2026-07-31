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
const panelEl        = document.querySelector(".panel");

// ── State ────────────────────────────────────────────────────────────────────
let ws              = null;
let sessionId       = null;
let sessionToken    = null;
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
      _hideApproval();
      _hideAsk();
      _hideManual();
    } else if (status === "error") {
      _setRunning(false);
      _setAgentActive(false);
      _hideCaptcha();
      _hideApproval();
      _hideAsk();
      _hideManual();
    } else if (text?.includes("CAPTCHA")) {
      _showCaptcha();
    }
  }

  if (msg.type === "action" && msg.action && msg.policy) {
    const { action, policy } = msg;

    if (policy?.decision === "ALLOW") {
      // Execute action in tab, then send result via WebSocket
      chrome.runtime.sendMessage(
        { type: "EXECUTE_ACTION", action },
        (result) => {
          if (!result) {
            _sendActionResult(action.action_id, false, { error: "No response from background" });
            return;
          }
          if (result.ok) {
            const pageState = result.page_state || {};
            _sendActionResult(action.action_id, true, pageState);
          } else {
            _sendActionResult(action.action_id, false, { error: result.error || "Action failed" });
          }
        }
      );
    } else if (policy?.decision === "ESCALATE") {
      // Show approval banner — backend is waiting
      _showApproval(action, policy);
      _appendStatus("step", `Escalated: ${policy.reason ?? "requires approval"}`);
    } else if (policy?.decision === "DENY") {
      // Report denial back so backend doesn't hang
      _sendActionResult(action.action_id, false, { error: `Policy denied: ${policy.reason}` });
      _appendStatus("error", `Blocked: ${policy.reason ?? "policy denied"}`);
    }
  }

  // If the action has an "ask" question embedded in step_event or action
  if (msg.type === "chat_status" && msg.status === "step" && msg.step_event) {
    const evt = msg.step_event;
    if (evt.outcome === "paused" && evt.ask_question) {
      _showAsk(evt);
    }
    if (evt.outcome === "paused" && evt.manual_input) {
      _showManual(evt.manual_reason || "Manual input required");
    }
  }
}

// ── Send action result via WebSocket ───────────────────────────────────────────
function _sendActionResult(actionId, ok, pageState) {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    console.warn("WS not open, cannot send action_result");
    return;
  }
  const msg = {
    type: "action_result",
    action_id: actionId,
    session_token: sessionToken,
    ok,
    page_state: {
      visible_text: pageState.visible_text || "",
      accessibility_tree: pageState.accessibility_tree || null,
      url: pageState.url || tabContext.url || "",
      tabId: pageState.tabId || tabContext.tabId,
    },
  };
  ws.send(JSON.stringify(msg));
}

// ── Approval UI ────────────────────────────────────────────────────────────────
let _pendingApprovalAction = null;
let _pendingApprovalActionId = null;

function _showApproval(action, policy) {
  _pendingApprovalAction = action;
  _pendingApprovalActionId = action.action_id;
  document.getElementById("approval-text").textContent =
    `Action requires approval: ${action.action_type} on ${action.semantic_target?.label || action.target}`;
  document.getElementById("approval-reason").textContent = policy.reason || "";
  document.getElementById("approval-banner").classList.remove("hidden");
}

function _hideApproval() {
  document.getElementById("approval-banner").classList.add("hidden");
  _pendingApprovalAction = null;
  _pendingApprovalActionId = null;
}

async function _resolveApproval(decision) {
  const actionId = _pendingApprovalActionId;
  const action = _pendingApprovalAction;
  if (!actionId) {
    _hideApproval();
    return;
  }
  _hideApproval();

  try {
    // Always notify the backend of the resolution first
    await fetch(`${BACKEND_HTTP}/resolve-escalation`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action_id: actionId, decision }),
    });

    if (decision === "approved") {
      _appendStatus("step", "Approved — executing action…");
      // Execute the approved action in the tab
      const result = await new Promise((resolve) => {
        chrome.runtime.sendMessage(
          { type: "EXECUTE_ACTION", action },
          (r) => resolve(r || { ok: false, error: "No response" })
        );
      });
      // Send action_result so the backend verification loop can proceed
      const pageState = result.page_state || {};
      _sendActionResult(actionId, result.ok === true, pageState);
      _appendStatus("step", result.ok ? "Action executed" : `Action failed: ${result.error || "unknown"}`);
    } else {
      _appendStatus("step", "Denied by user");
      // Send action_result with ok=false so the backend doesn't hang
      _sendActionResult(actionId, false, { error: "User denied the action" });
    }
  } catch (err) {
    _appendStatus("error", `Approval flow failed: ${err.message}`);
    // Try to at least unblock the backend
    _sendActionResult(actionId, false, { error: `Approval error: ${err.message}` });
  }

  _pendingApprovalAction = null;
  _pendingApprovalActionId = null;
}

// ── Ask UI ─────────────────────────────────────────────────────────────────────
let _pendingAskSessionId = null;

function _showAsk(evt) {
  _pendingAskSessionId = evt.session_id || sessionId;
  document.getElementById("ask-question").textContent = evt.ask_question;
  
  // Show options if available
  const optionsContainer = document.getElementById("ask-options");
  optionsContainer.innerHTML = "";
  if (evt.ask_options && evt.ask_options.length > 0) {
    optionsContainer.classList.remove("hidden");
    evt.ask_options.forEach((opt) => {
      const btn = document.createElement("button");
      btn.className = "ask-option-btn";
      btn.textContent = opt;
      btn.addEventListener("click", () => {
        // Select this option, fill input
        document.getElementById("ask-input").value = opt;
        document.querySelectorAll(".ask-option-btn").forEach(b => b.classList.remove("selected"));
        btn.classList.add("selected");
      });
      optionsContainer.appendChild(btn);
    });
  } else {
    optionsContainer.classList.add("hidden");
  }
  
  document.getElementById("ask-input").value = "";
  document.getElementById("ask-banner").classList.remove("hidden");
  document.getElementById("ask-input").focus();
}

function _hideAsk() {
  document.getElementById("ask-banner").classList.add("hidden");
  _pendingAskSessionId = null;
}

async function _submitAsk() {
  const answer = document.getElementById("ask-input").value.trim();
  if (!answer) return;
  _hideAsk();
  try {
    await fetch(`${BACKEND_HTTP}/resolve-ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: _pendingAskSessionId || sessionId, answer }),
    });
    _appendStatus("step", `Answered: ${answer}`);
  } catch (err) {
    _appendStatus("error", `Ask submit failed: ${err.message}`);
  }
}

// ── Manual interaction UI (login/password/OTP/payment) ──────────────────────────
function _showManual(reason) {
  document.getElementById("manual-text").textContent =
    reason || "Manual input required. Type credentials directly in the browser tab, then click Resume.";
  document.getElementById("manual-banner").classList.remove("hidden");
}

function _hideManual() {
  document.getElementById("manual-banner").classList.add("hidden");
}

async function _resumeManual() {
  _hideManual();
  // Refresh page context, then the backend will re-observe the page
  _refreshTabContext();
  if (!sessionId) return;
  try {
    await fetch(`${BACKEND_HTTP}/resolve-captcha`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
  } catch (err) {
    _appendStatus("error", `Resume failed: ${err.message}`);
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

  // Approval buttons
  document.getElementById("approval-approve-btn").addEventListener("click", () => _resolveApproval("approved"));
  document.getElementById("approval-deny-btn").addEventListener("click", () => _resolveApproval("denied"));

  // Ask submit
  document.getElementById("ask-submit-btn").addEventListener("click", _submitAsk);
  document.getElementById("ask-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      _submitAsk();
    }
  });

  // Manual resume
  document.getElementById("manual-resume-btn").addEventListener("click", _resumeManual);
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
    sessionToken = data.session_token || "";
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
  sendBtn.textContent = value ? "Running…" : "Run Agent";
  goalInput.placeholder = value ? "Agent is working..." : "Describe what you want the agent to do...";
  panelEl?.classList.toggle("is-running", value);

  // Typing indicator
  const existingTyping = document.getElementById("__typing-indicator");
  if (value && !existingTyping) {
    const row = document.createElement("div");
    row.id = "__typing-indicator";
    row.className = "status-line status-step typing-row";
    row.innerHTML = `
      <span class="status-icon spin">${STATUS_ICON.step}</span>
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
// Inline SVG strings (no build step in the extension). stroke="currentColor" lets
// the CSS color the icons via the parent .status-line color rules.
const _svg = (body, size = 14) =>
  `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" ` +
  `stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;

const STATUS_ICON = {
  planning: _svg('<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>', 14),
  step:     _svg('<circle cx="12" cy="12" r="3"/><path d="M12 2a10 10 0 0 1 10 10"/><path d="M19.07 4.93 17 7"/><path d="M2 12h4"/><path d="M20 12h2"/>', 14),
  done:     _svg('<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>', 14),
  error:    _svg('<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>', 14),
};

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
