/**
 * background.js — Frontier Agent Service Worker (MV3)
 *
 * Responsibilities
 * ----------------
 * 1. Open the side panel when the user clicks the toolbar icon.
 * 2. Relay action commands from the side panel → content script in the
 *    active tab → result back to the side panel.
 * 3. Query the active tab for its URL / title / visible text and return
 *    that context to the side panel on request (used by /extension/chat).
 * 4. Manage the "agent is active" flag so content.js knows when to show
 *    the indicator banner.
 *
 * Message protocol (chrome.runtime.sendMessage / onMessage)
 * ----------------------------------------------------------
 * Side panel → background:
 *   { type: "GET_TAB_CONTEXT" }
 *     → returns { url, title, visibleText }
 *
 *   { type: "EXECUTE_ACTION", action: AgentAction }
 *     → injects content.js if needed, sends action to content script
 *     → returns { ok: true } | { ok: false, error: "..." }
 *
 *   { type: "SET_AGENT_ACTIVE", active: bool }
 *     → broadcasts to content script so the indicator banner toggles
 *
 * Content script → background:
 *   { type: "ACTION_RESULT", actionId, success, error? }
 *     → forwarded to side panel
 */

const BACKEND = "http://localhost:8000";

// ---------------------------------------------------------------------------
// 1. Open side panel on toolbar click
// ---------------------------------------------------------------------------
chrome.action.onClicked.addListener((tab) => {
  chrome.sidePanel.open({ tabId: tab.id });
});

// ---------------------------------------------------------------------------
// 2. Message router
// ---------------------------------------------------------------------------
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  switch (msg.type) {

    // ── GET_TAB_CONTEXT ────────────────────────────────────────────────────
    case "GET_TAB_CONTEXT": {
      _getActiveTab().then(tab => {
        if (!tab) return sendResponse({ error: "No active tab" });

        // Ask the content script for visible body text
        chrome.tabs.sendMessage(
          tab.id,
          { type: "GET_VISIBLE_TEXT" },
          (result) => {
            const visibleText = result?.text ?? "";
            sendResponse({
              url:         tab.url   ?? "",
              title:       tab.title ?? "",
              visibleText,
            });
          }
        );
      });
      return true; // keep channel open for async response
    }

    // ── EXECUTE_ACTION ─────────────────────────────────────────────────────
    case "EXECUTE_ACTION": {
      const { action } = msg;

      _getActiveTab().then(async (tab) => {
        if (!tab) return sendResponse({ ok: false, error: "No active tab" });

        // Ensure content script is injected (idempotent)
        try {
          await chrome.scripting.executeScript({
            target: { tabId: tab.id },
            files:  ["content.js"],
          });
        } catch (_) {
          // Already injected — ignore
        }

        // Relay the action
        chrome.tabs.sendMessage(
          tab.id,
          { type: "EXECUTE_ACTION", action },
          (result) => {
            sendResponse(result ?? { ok: false, error: "No response from content script" });
          }
        );
      });
      return true;
    }

    // ── SET_AGENT_ACTIVE ───────────────────────────────────────────────────
    case "SET_AGENT_ACTIVE": {
      const { active } = msg;

      _getActiveTab().then(async (tab) => {
        if (!tab) return;

        try {
          await chrome.scripting.executeScript({
            target: { tabId: tab.id },
            files:  ["content.js"],
          });
        } catch (_) {}

        chrome.tabs.sendMessage(
          tab.id,
          { type: "SET_AGENT_ACTIVE", active },
        );
      });

      sendResponse({ ok: true });
      return false;
    }

    // ── ACTION_RESULT (from content script, forward to side panel) ─────────
    case "ACTION_RESULT": {
      // Side panel listens via its own onMessage — just echo it back.
      chrome.runtime.sendMessage({ ...msg });
      return false;
    }

    default:
      return false;
  }
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
async function _getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab ?? null;
}
