/**
 * StepTimeline.jsx 
 *
 * Renders the full history of planned steps with per-step outcome indicators.
 * Sits inside the chat thread, rendered once the agent starts emitting
 * step_event payloads.
 *
 * Props
 * -----
 * steps : array of step records, one per unique (step_number, run_id):
 *   {
 *     key         : string  — unique React key
 *     stepNumber  : number
 *     totalSteps  : number
 *     goal        : string
 *     outcome     : "running" | "success" | "failed" | "skipped"
 *     retry       : number  — 0 = first attempt; >0 = retried
 *     isReplan    : bool    — true when this entry follows a re-plan
 *   }
 */

const OUTCOME_META = {
  running: { icon: "⏳", label: "Running",  cls: "tl-running"  },
  success: { icon: "✓",  label: "Done",     cls: "tl-success"  },
  failed:  { icon: "✗",  label: "Failed",   cls: "tl-failed"   },
  skipped: { icon: "⤳",  label: "Skipped",  cls: "tl-skipped"  },
  paused:  { icon: "⏸",  label: "Paused",   cls: "tl-paused"   },
};

export default function StepTimeline({ steps }) {
  if (!steps || steps.length === 0) return null;

  return (
    <div className="step-timeline" role="list" aria-label="Step timeline">
      {steps.map((s, idx) => {
        const meta = OUTCOME_META[s.outcome] ?? OUTCOME_META.running;
        const isLast = idx === steps.length - 1;

        return (
          <div key={s.key} className="tl-entry" role="listitem">
            {/* Vertical connector line — omit on last item */}
            <div className="tl-track">
              <div className={`tl-dot ${meta.cls}`} aria-label={meta.label}>
                {meta.icon}
              </div>
              {!isLast && <div className="tl-line" />}
            </div>

            <div className="tl-body">
              {/* Re-plan marker */}
              {s.isReplan && (
                <div className="tl-replan-badge" title="Plan was revised at this point">
                  ↻ re-planned
                </div>
              )}

              {/* Step label */}
              <div className={`tl-goal ${meta.cls}`}>
                <span className="tl-step-num">
                  {s.stepNumber}/{s.totalSteps}
                </span>
                <span className="tl-goal-text">{s.goal}</span>
              </div>

              {/* Badges row */}
              <div className="tl-badges">
                <span className={`tl-outcome-badge ${meta.cls}`}>
                  {meta.label}
                </span>
                {s.retry > 0 && (
                  <span className="tl-retry-badge" title={`Retried ${s.retry} time(s)`}>
                    retry {s.retry}
                  </span>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
