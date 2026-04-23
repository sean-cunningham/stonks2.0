import type { StrategyDashboardViewModel } from "../../types/dashboard";

type Props = {
  signal: StrategyDashboardViewModel["currentSignal"];
  cycleSummary: StrategyDashboardViewModel["cycleSummary"];
};

function decisionBadgeClass(decision: string): string {
  if (decision === "candidate_call") return "decision-badge decision-candidate-call";
  if (decision === "candidate_put") return "decision-badge decision-candidate-put";
  if (decision === "no_trade") return "decision-badge decision-no-trade";
  return "decision-badge decision-default";
}

export default function SignalBlockerPanel({ signal, cycleSummary }: Props) {
  const failures = cycleSummary?.recent_auto_open_failure_count ?? 0;
  const primaryAutoOpen = cycleSummary?.primary_recent_blocker ?? null;
  const evalBlockers = signal?.current_blockers?.length ? signal.current_blockers : [];
  const showWhyCard =
    failures > 0 || (signal?.current_decision === "no_trade" && evalBlockers.length > 0);

  return (
    <section id="panel-signal-blockers" className="panel panel-signal-priority">
      <h2>Current signal / blockers</h2>
      {!signal ? (
        <div className="empty empty-prose">
          <p>No <code>current_signal</code> object in this dashboard response.</p>
          <p className="muted small-print">
            The live API normally includes decision, reasons, and blockers. If this persists after refresh, the backend
            payload may be older than the dashboard contract.
          </p>
        </div>
      ) : (
        <>
          <div className="signal-top-row">
            <span className={decisionBadgeClass(signal.current_decision)}>{signal.current_decision}</span>
            <span className="signal-meta">
              Candidate blocked (auto-open failures in recent cycles):{" "}
              <strong>{signal.candidate_blocked ? "yes" : "no"}</strong>
            </span>
          </div>

          {signal.candidate_blocked && signal.candidate_block_reason && (
            <div className="signal-highlight">
              <strong>Auto-open blocked — most common failure code:</strong> {signal.candidate_block_reason}
            </div>
          )}

          {primaryAutoOpen && !signal.candidate_blocked && (
            <div className="muted signal-subtle">
              Recent cycles: most common <code>auto_open_failed</code> code was{" "}
              <strong>{primaryAutoOpen}</strong> ({failures} failure{failures === 1 ? "" : "s"} in window).
            </div>
          )}

          <div className="signal-grid">
            <div>
              <strong>Current blockers (evaluator)</strong>
              <div className="signal-body">
                {signal.current_blockers.length ? signal.current_blockers.join(" · ") : "none"}
              </div>
            </div>
            <div>
              <strong>Current reasons</strong>
              <div className="signal-body">
                {signal.current_reasons.length ? signal.current_reasons.join(" · ") : "none"}
              </div>
            </div>
          </div>
        </>
      )}

      {showWhyCard && (
        <article className="why-card">
          <h3>Why not trading?</h3>
          {failures > 0 && (
            <div className="why-line">
              <strong>Recent auto-open failures (last 50 cycles):</strong> {failures}
              {primaryAutoOpen && (
                <>
                  {" "}
                  — primary code: <code>{primaryAutoOpen}</code>
                </>
              )}
            </div>
          )}
          {signal && signal.current_decision === "no_trade" && evalBlockers.length > 0 && (
            <div className="why-line">
              <strong>Evaluator is in no_trade</strong> with blockers: {evalBlockers.join(" · ")}
            </div>
          )}
        </article>
      )}
    </section>
  );
}
