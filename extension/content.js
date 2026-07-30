/**
 * content.js — Frontier Agent Content Script
 *
 * Runs in the context of every tab (injected by background.js on demand,
 * or automatically at document_idle via manifest content_scripts).
 *
 * Responsibilities
 * ----------------
 * A. Execute agent actions inside the current tab:
 *      click, fill/type, navigate, scroll, read (returns text).
 *    This is the "content script port" of the Playwright execution logic —
 *    same semantic element-finding approach, different execution surface.
 *
 * B. Return visible page text to the background on request (GET_VISIBLE_TEXT).
 *
 * C. Show / hide the "agent is active on this tab" indicator banner
 *    (SET_AGENT_ACTIVE).  The banner logic lives in agent-active-indicator.js
 *    but this script can also toggle it directly.
 *
 * Semantic element resolution (mirrors playwright_agent.py layering)
 * ------------------------------------------------------------------
 * 1. Try CSS selector from action.target
 * 2. If not found / hidden → try role + label (getByRoleAndLabel)
 * 3. If still not found → return { ok: false, error: "Element not found" }
 *    (no vision fallback in the content script — that's backend-side only)
 *
 * Message protocol
 * ----------------
 * Receives from background:
 *   { type: "EXECUTE_ACTION",   action: AgentAction }
 *   { type: "GET_VISIBLE_TEXT" }
 *   { type: "SET_AGENT_ACTIVE", active: bool }
 *
 * Replies with sendResponse:
 *   { ok: true,  result?: string }   — success (result = extracted text for "read")
 *   { ok: false, error: string  }   — failure
 */

// Guard against double-injection
if (typeof window.__frontierInjected === "undefined") {
  window.__frontierInjected = true;

  // -------------------------------------------------------------------------
  // Message listener
  // -------------------------------------------------------------------------
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    switch (msg.type) {

      case "EXECUTE_ACTION":
        _handleAction(msg.action)
          .then(r  => sendResponse(r))
          .catch(e => sendResponse({ ok: false, error: String(e) }));
        return true; // async

      case "GET_VISIBLE_TEXT":
        sendResponse({ text: document.body.innerText ?? "" });
        return false;

      case "SET_AGENT_ACTIVE":
        _setIndicator(msg.active);
        sendResponse({ ok: true });
        return false;

      default:
        return false;
    }
  });

  // -------------------------------------------------------------------------
  // Action executor
  // -------------------------------------------------------------------------
  async function _handleAction(action) {
    const { action_type, target, semantic_target, value } = action;

    switch (action_type) {

      case "click": {
        const el = _resolve(target, semantic_target);
        if (!el) return { ok: false, error: `click: element not found — ${target}` };
        el.focus();
        el.click();
        return { ok: true };
      }

      case "fill":
      case "type": {
        const el = _resolve(target, semantic_target);
        if (!el) return { ok: false, error: `fill: element not found — ${target}` };
        el.focus();
        // Clear + set natively so React / Vue onChange fires
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
          window.HTMLInputElement.prototype, "value"
        )?.set;
        if (nativeInputValueSetter) {
          nativeInputValueSetter.call(el, value ?? "");
          el.dispatchEvent(new Event("input",  { bubbles: true }));
          el.dispatchEvent(new Event("change", { bubbles: true }));
        } else {
          el.value = value ?? "";
        }
        return { ok: true };
      }

      case "navigate": {
        const url = target || value;
        if (!url) return { ok: false, error: "navigate: no URL provided" };
        window.location.href = url;
        return { ok: true };
      }

      case "scroll": {
        const el = _resolve(target, semantic_target);
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "center" });
        } else {
          window.scrollBy({ top: 400, behavior: "smooth" });
        }
        return { ok: true };
      }

      case "read": {
        const el = _resolve(target, semantic_target);
        if (!el) return { ok: false, error: `read: element not found — ${target}` };
        return { ok: true, result: el.innerText ?? el.textContent ?? "" };
      }

      case "done":
        return { ok: true, result: "done" };

      default:
        return { ok: false, error: `Unknown action_type: ${action_type}` };
    }
  }

  // -------------------------------------------------------------------------
  // Semantic element resolution
  // Tries CSS selector first, then role+label fallback.
  // -------------------------------------------------------------------------
  function _resolve(cssSelector, semanticTarget) {
    // 1. CSS selector
    if (cssSelector) {
      try {
        const el = document.querySelector(cssSelector);
        if (el && _isVisible(el)) return el;
      } catch (_) { /* bad selector — fall through */ }
    }

    // 2. Role + label
    if (semanticTarget?.label) {
      const label = semanticTarget.label.toLowerCase();
      const role  = semanticTarget.role ?? "";

      // Try aria-label / placeholder / value match
      const candidates = Array.from(
        document.querySelectorAll(
          'button, a, input, textarea, select, [role], [aria-label]'
        )
      );

      for (const el of candidates) {
        if (!_isVisible(el)) continue;
        const elLabel = (
          el.getAttribute("aria-label") ||
          el.getAttribute("placeholder") ||
          el.innerText ||
          el.textContent ||
          el.value ||
          ""
        ).toLowerCase();

        if (elLabel.includes(label)) {
          // If a role hint was given, prefer matching elements
          if (!role || role === "generic" || _matchesRole(el, role)) {
            return el;
          }
        }
      }
    }

    return null;
  }

  function _isVisible(el) {
    const style = window.getComputedStyle(el);
    if (style.display === "none")      return false;
    if (style.visibility === "hidden") return false;
    if (parseFloat(style.opacity) < 0.05) return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function _matchesRole(el, role) {
    const tag  = el.tagName.toLowerCase();
    const aria = (el.getAttribute("role") ?? "").toLowerCase();
    const map  = {
      button:   ["button", "input[type=submit]", "input[type=button]"],
      link:     ["a"],
      textbox:  ["input", "textarea"],
      searchbox:["input[type=search]"],
      combobox: ["select"],
      checkbox: ["input[type=checkbox]"],
      radio:    ["input[type=radio]"],
    };
    if (aria === role) return true;
    const selectors = map[role] ?? [];
    return selectors.some(sel => {
      try { return el.matches(sel); } catch { return false; }
    });
  }

  // -------------------------------------------------------------------------
  // Agent active indicator
  // -------------------------------------------------------------------------
  function _setIndicator(active) {
    const ID = "__frontier-agent-indicator";
    let banner = document.getElementById(ID);

    if (active) {
      if (banner) return; // already shown

      banner = document.createElement("div");
      banner.id = ID;
      banner.innerHTML = `
        <span style="font-size:14px;">🤖</span>
        <span style="flex:1;font-weight:700;">Aegis Vigilis is active on this tab</span>
        <button id="__frontier-dismiss" style="
          background:none;border:1px solid rgba(255,255,255,0.5);
          border-radius:6px;color:#fff;font-size:11px;padding:3px 10px;
          cursor:pointer;white-space:nowrap;">
          Dismiss
        </button>
      `;
      Object.assign(banner.style, {
        position:       "fixed",
        top:            "0",
        left:           "0",
        right:          "0",
        zIndex:         "2147483647",
        background:     "#ffb703",
        color:          "#3a2900",
        padding:        "8px 16px",
        display:        "flex",
        alignItems:     "center",
        gap:            "10px",
        fontFamily:     "system-ui, sans-serif",
        fontSize:       "13px",
        boxShadow:      "0 2px 8px rgba(0,0,0,0.18)",
      });

      document.body.appendChild(banner);

      document.getElementById("__frontier-dismiss")?.addEventListener("click", () => {
        banner?.remove();
      });
    } else {
      banner?.remove();
    }
  }
}
