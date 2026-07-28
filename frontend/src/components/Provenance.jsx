export default function Provenance({ item }) {
  if (!item) {
    return (
      <div className="panel">
        <h2>Provenance</h2>
        <p className="empty-state">
          Select an action to see where its instruction came from.
        </p>
      </div>
    );
  }

  const { action, policy } = item;

  return (
    <div className="panel">
      <h2>Provenance</h2>

      <section className="prov-section">
        <h3>Instruction source</h3>
        <p className="prov-location">{action.cited_source_location}</p>
        <blockquote className="prov-quote">
          "{action.cited_source_text}"
        </blockquote>
      </section>

      <section className="prov-section">
        <h3>Agent reasoning</h3>
        <p>{action.reasoning}</p>
      </section>

      <section className="prov-section">
        <h3>Policy decision</h3>
        <p>
          <span className={`badge decision-${policy.decision?.toLowerCase()}`}>
            {policy.decision}
          </span>{" "}
          — {policy.reason}
        </p>
        <p className="prov-meta">
          Category: {policy.risk_category} · Level: {policy.risk_level}
        </p>
        {policy.hidden_content_detected && (
          <p className="hidden-flag">
            ⚠ This instruction originated from hidden page content, not the
            user's request.
          </p>
        )}
      </section>
    </div>
  );
}