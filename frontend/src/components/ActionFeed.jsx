import { useState } from "react";

const DECISION_CLASS = {
  ALLOW: "decision-allow",
  DENY: "decision-deny",
  ESCALATE: "decision-escalate",
};

export default function ActionFeed({ actions, selectedId, onSelect }) {
  const [resolved, setResolved] = useState({});

  const handleResolve = async (e, action_id, decision) => {
    e.stopPropagation();
    setResolved({ ...resolved, [action_id]: decision });
    await fetch("http://localhost:8000/resolve-escalation", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action_id, decision })
    });
  };

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
          
          const isPending = policy.decision === "ESCALATE" && !resolved[action.action_id];
          const resolution = resolved[action.action_id];

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
                  {resolution ? resolution.toUpperCase() : policy.decision}
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
                {policy.topic_drift_detected && (
                  <span className="hidden-flag">⚠ topic drift</span>
                )}
              </div>
              
              {isPending && (
                <div className="approval-controls" style={{marginTop: '10px', display: 'flex', gap: '10px'}}>
                  <button 
                    onClick={(e) => handleResolve(e, action.action_id, 'approved')}
                    style={{background: '#16a34a', color: 'white', padding: '6px 12px', border: 'none', borderRadius: '4px', cursor: 'pointer'}}
                  >
                    Approve
                  </button>
                  <button 
                    onClick={(e) => handleResolve(e, action.action_id, 'denied')}
                    style={{background: '#dc2626', color: 'white', padding: '6px 12px', border: 'none', borderRadius: '4px', cursor: 'pointer'}}
                  >
                    Deny
                  </button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}