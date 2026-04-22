import type { StrategyDashboardViewModel } from "../../types/dashboard";

type Props = {
  signal: StrategyDashboardViewModel["currentSignal"];
  cycleSummary: StrategyDashboardViewModel["cycleSummary"];
};

export default function SignalBlockerPanel({ signal, cycleSummary }: Props) {
  return (
    <section className="panel">
      <h2>Current Signal / Current Blocker</h2>
      {!signal ? (
        <div className="empty">Signal not available.</div>
      ) : (
        <div className="signal-grid">
          <div>
            <strong>Decision:</strong> {signal.current_decision}
          </div>
          <div>
            <strong>Candidate blocked:</strong> {signal.candidate_blocked ? "Yes" : "No"}
          </div>
          <div>
            <strong>Candidate block reason:</strong> {signal.candidate_block_reason ?? "n/a"}
          </div>
          <div>
            <strong>Current blockers:</strong>{" "}
            {signal.current_blockers.length ? signal.current_blockers.join(", ") : "none"}
          </div>
          <div>
            <strong>Current reasons:</strong> {signal.current_reasons.length ? signal.current_reasons.join(", ") : "none"}
          </div>
        </div>
      )}

      {(cycleSummary?.recent_auto_open_failure_count ?? 0) > 0 && (
        <article className="why-card">
          <h3>Why not trading?</h3>
          <div>Recent auto-open failures: {cycleSummary?.recent_auto_open_failure_count ?? 0}</div>
          <div>Primary blocker: {cycleSummary?.primary_recent_blocker ?? "n/a"}</div>
        </article>
      )}
    </section>
  );
}
