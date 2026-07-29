/**
 * agent-active-indicator.js
 *
 * Standalone module that injects a visible "agent is active on this tab"
 * banner into the current page. Called by content.js (via SET_AGENT_ACTIVE
 * message) and also importable directly.
 *
 * Why this is a separate file
 * ---------------------------
 * The indicator is also used by the side panel itself (it can call
 * chrome.scripting.executeScript({ files: ["agent-active-indicator.js"] })
 * to force the banner on without going through the full content.js message
 * flow. Keeping it separate means it stays testable and swappable.
 *
 * Public API (exposed on window for chrome.scripting.executeScript use)
 * ----------------------------------------------------------------------
 *   window.__frontierIndicator.show()
 *   window.__frontierIndicator.hide()
 */

(function () {
  const BANNER_ID = "__frontier-agent-indicator";
  const YELLOW    = "#ffb703";
  const TEXT      = "#3a2900";

  function show() {
    if (document.getElementById(BANNER_ID)) return; // idempotent

    const banner = document.createElement("div");
    banner.id = BANNER_ID;
    banner.setAttribute("role", "status");
    banner.setAttribute("aria-live", "polite");

    // Inline styles — no external CSS dependency
    Object.assign(banner.style, {
      position:      "fixed",
      top:           "0",
      left:          "0",
      right:         "0",
      zIndex:        "2147483647",
      background:    YELLOW,
      color:         TEXT,
      padding:       "8px 16px",
      display:       "flex",
      alignItems:    "center",
      gap:           "10px",
      fontFamily:    "system-ui, -apple-system, sans-serif",
      fontSize:      "13px",
      fontWeight:    "600",
      boxShadow:     "0 2px 8px rgba(0,0,0,0.18)",
      boxSizing:     "border-box",
    });

    banner.innerHTML = `
      <span aria-hidden="true" style="font-size:16px;flex-shrink:0;">🤖</span>
      <span style="flex:1;">Frontier Agent is active on this tab</span>
      <span style="
        font-size:11px;
        background:rgba(0,0,0,0.10);
        border-radius:999px;
        padding:2px 10px;
        font-weight:800;
        letter-spacing:0.04em;
      ">AGENT ACTIVE</span>
      <button
        id="__frontier-indicator-dismiss"
        aria-label="Dismiss agent indicator"
        style="
          background:none;
          border:1px solid rgba(58,41,0,0.35);
          border-radius:6px;
          color:${TEXT};
          font-size:11px;
          font-weight:700;
          padding:3px 10px;
          cursor:pointer;
          white-space:nowrap;
        "
      >Dismiss</button>
    `;

    document.body.appendChild(banner);

    document
      .getElementById("__frontier-indicator-dismiss")
      ?.addEventListener("click", hide);
  }

  function hide() {
    document.getElementById(BANNER_ID)?.remove();
  }

  // Expose for chrome.scripting.executeScript calls
  window.__frontierIndicator = { show, hide };
})();
