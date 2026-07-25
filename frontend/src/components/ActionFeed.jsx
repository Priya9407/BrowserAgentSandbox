const DECISION_CLASS = {
  ALLOW: "decision-allow",
  DENY: "decision-deny",
  ESCALATE: "decision-escalate",
};

export default function ActionFeed({ actions, selectedId, onSelect }) {
  return (
    <div className="panel">
      <h2>Action Feed</h2>

      {actions.length === 0 && (
        <p className="empty-state">No actions yet — waiting for agent…</p>
      )}

      <ul className="action-list">
        {actions.map(({ action, policy }) => {
          const isSelected = action.action_id === selectedId;
          const decisionClass =
            DECISION_CLASS[policy.decision] || "decision-unknown";

          return (
            <li
              key={`${action.action_id}-${action.timestamp}`}
              className={`action-item ${decisionClass} ${
                isSelected ? "selected" : ""
              }`}
              onClick={() => onSelect(action.action_id)}
            >
              <div className="action-item-row">
                <span className="action-type">{action.action_type}</span>
                <span className={`badge ${decisionClass}`}>
                  {policy.decision}
                </span>
              </div>
              <div className="action-target">{action.target}</div>
              <div className="action-meta">
                <span className={`risk-pill risk-${policy.risk_level?.toLowerCase()}`}>
                  {policy.risk_level}
                </span>
                {policy.hidden_content_detected && (
                  <span className="hidden-flag">⚠ hidden content</span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}