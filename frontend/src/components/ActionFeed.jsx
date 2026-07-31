import { useState } from "react";
import { AlertTriangle, Check, EyeOff, Shield, ShieldCheck, X } from "lucide-react";

const DECISION_CLASS = {
  ALLOW: "decision-allow",
  DENY: "decision-deny",
  ESCALATE: "decision-escalate",
};

export default function ActionFeed({ actions, selectedId, onSelect }) {
  const [resolved, setResolved] = useState({});
  const [autoApproveLow, setAutoApproveLow] = useState(false);

  const toggleAutoApprove = async () => {
    const nextState = !autoApproveLow;
    setAutoApproveLow(nextState);
    try {
      await fetch("http://localhost:8000/toggle-auto-approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: nextState })
      });

      // If turning ON, immediately approve any queued LOW/UNKNOWN escalations
      if (nextState) {
          const pending = actions.filter(({ action, policy, execution_requires_approval }) =>
            (policy.decision === "ESCALATE" || execution_requires_approval) &&
            !resolved[action.action_id] &&
            (policy.risk_level === "LOW" || policy.risk_level === "UNKNOWN")
        );

        if (pending.length > 0) {
          const newResolved = { ...resolved };
          await Promise.all(pending.map(async ({ action }) => {
            newResolved[action.action_id] = "approved";
            await fetch("http://localhost:8000/resolve-escalation", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ action_id: action.action_id, decision: "approved" })
            });
          }));
          setResolved(newResolved);
        }
      }
    } catch (err) {
      console.error("Failed to toggle auto-approve:", err);
    }
  };

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
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px'}}>
        <h2 style={{margin: 0}}>Action Feed</h2>
        <button 
          onClick={toggleAutoApprove}
          style={{
            background: autoApproveLow ? '#16a34a' : '#4b5563', 
            color: 'white', 
            padding: '6px 12px', 
            border: 'none', 
            borderRadius: '4px', 
            cursor: 'pointer',
            fontSize: '12px',
            fontWeight: '600'
          }}
          title="Automatically approve LOW and UNKNOWN risk escalations"
        >
          {autoApproveLow
            ? <><ShieldCheck size={13} /> Auto-Approving Low Risks</>
            : <><Shield size={13} /> Auto-Approve Low Risks</>}
        </button>
      </div>

      {actions.length === 0 && (
        <p className="empty-state">No actions yet — waiting for agent…</p>
      )}

      <ul className="action-list">
        {actions.map((record) => {
          const { action, policy } = record;
          const isSelected = action.action_id === selectedId;
          const decisionClass =
            DECISION_CLASS[policy.decision] || "decision-unknown";
          
          const isPending =
            (policy.decision === "ESCALATE" || record.execution_requires_approval) &&
            !resolved[action.action_id];
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
                  <span className="hidden-flag"><EyeOff size={11} /> hidden content</span>
                )}
                {policy.topic_drift_detected && (
                  <span className="hidden-flag"><AlertTriangle size={11} /> topic drift</span>
                )}
              </div>
              
              {isPending && (
                <div className="approval-controls" style={{marginTop: '10px', display: 'flex', gap: '10px'}}>
                  <button 
                    onClick={(e) => handleResolve(e, action.action_id, 'approved')}
                    style={{background: '#16a34a', color: 'white', padding: '6px 12px', border: 'none', borderRadius: '4px', cursor: 'pointer'}}
                  >
                    <Check size={13} /> Approve
                  </button>
                  <button 
                    onClick={(e) => handleResolve(e, action.action_id, 'denied')}
                    style={{background: '#dc2626', color: 'white', padding: '6px 12px', border: 'none', borderRadius: '4px', cursor: 'pointer'}}
                  >
                    <X size={13} /> Deny
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
