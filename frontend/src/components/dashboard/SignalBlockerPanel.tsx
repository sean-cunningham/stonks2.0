import type { StrategyDashboardViewModel } from "../../types/dashboard";
import {
  affordabilityDiagnosticRows,
  buildNoTradeBecauseLine,
  humanizeDecision,
  humanizeFailedGate,
  humanizePaperTradeCode,
  humanizeReason,
  summarizeAffordabilityDiagnostics,
  humanizeBlocker,
} from "../../utils/dashboardHumanize";

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
  const primaryFailedGate = cycleSummary?.most_common_recent_failed_gate ?? null;
  const nearMissExplanation = cycleSummary?.current_near_miss_explanation ?? null;
  const affordabilityDiag = cycleSummary?.latest_affordability_diagnostics ?? null;
  const affordabilitySummary = summarizeAffordabilityDiagnostics(affordabilityDiag);
  const affordabilityRows = affordabilityDiagnosticRows(affordabilityDiag);
  const evalBlockers = signal?.current_blockers?.length ? signal.current_blockers : [];
  const showWhyCard =
    failures > 0 || (signal?.current_decision === "no_trade" && evalBlockers.length > 0);

  return (
    <section id="panel-signal-blockers" className="panel panel-signal-priority">
      <h2>Current trading status</h2>
      {!signal ? (
        <div className="empty empty-prose">
          <p>Trading status is not included in this dashboard response.</p>
          <p className="muted small-print">
            After a refresh you should see the bot decision, plain-English reasons, and why it is not trading. If this
            stays empty, the API may be older than the dashboard.
          </p>
        </div>
      ) : (
        <>
          <div className="signal-top-row">
            <span className={decisionBadgeClass(signal.current_decision)} title={signal.current_decision}>
              {humanizeDecision(signal.current_decision)}
            </span>
            <span className="signal-meta">
              A setup is showing, but recent automatic opens failed:{" "}
              <strong>{signal.candidate_blocked ? "Yes" : "No"}</strong>
            </span>
          </div>

          {signal.candidate_blocked && signal.candidate_block_reason && (
            <div className="signal-highlight">
              <strong>Most common automatic-open issue:</strong>{" "}
              {humanizePaperTradeCode(signal.candidate_block_reason)}
            </div>
          )}

          {primaryAutoOpen && !signal.candidate_blocked && failures > 0 && (
            <div className="muted signal-subtle">
              In the last 50 cycles, automatic opens failed {failures} time{failures === 1 ? "" : "s"}. Most common
              issue: {humanizePaperTradeCode(primaryAutoOpen)}
            </div>
          )}

          <div className="signal-grid">
            <div>
              <strong>Why the bot is not trading</strong>
              <div className="signal-body">
                {signal.current_blockers.length
                  ? signal.current_blockers.map((b) => humanizeBlocker(b)).join(" · ")
                  : signal.current_decision === "no_trade"
                    ? "No hard blockers — the strategy simply does not see a tradeable setup right now."
                    : "No evaluator blockers for this snapshot."}
              </div>
            </div>
            <div>
              <strong>What supports the current view</strong>
              <div className="signal-body">
                {signal.current_reasons.length
                  ? signal.current_reasons.map((r) => humanizeReason(r)).join(" · ")
                  : "No supporting detail lines for this snapshot."}
              </div>
            </div>
          </div>

          <details className="technical-details">
            <summary>Technical details (debug)</summary>
            <pre className="technical-pre">
              {JSON.stringify(
                {
                  current_decision: signal.current_decision,
                  current_blockers: signal.current_blockers,
                  current_reasons: signal.current_reasons,
                  candidate_blocked: signal.candidate_blocked,
                  candidate_block_reason: signal.candidate_block_reason,
                },
                null,
                2
              )}
            </pre>
          </details>
        </>
      )}

      {showWhyCard && (
        <article className="why-card">
          <h3>Why nothing traded</h3>
          {failures > 0 && (
            <div className="why-line">
              <strong>Recent automatic-open failures (last 50 cycles):</strong> {failures}
              {primaryAutoOpen && (
                <>
                  {" "}
                  — <span className="human-em">{humanizePaperTradeCode(primaryAutoOpen)}</span>{" "}
                  <span className="muted mono">({primaryAutoOpen})</span>
                </>
              )}
            </div>
          )}
          {signal && signal.current_decision === "no_trade" && evalBlockers.length > 0 && (
            <div className="why-line human-em">{buildNoTradeBecauseLine(evalBlockers)}</div>
          )}
          {(cycleSummary?.recent_affordability_failure_count ?? 0) > 0 && (
            <div className="why-line">
              <strong>Affordability diagnostics:</strong>{" "}
              {affordabilitySummary ?? "Premium exceeded the risk budget on recent attempts."}
              {affordabilityRows.length > 0 && (
                <dl className="affordability-grid">
                  {affordabilityRows.map((r) => (
                    <div key={r.label}>
                      <dt>{r.label}</dt>
                      <dd>{r.value}</dd>
                    </div>
                  ))}
                </dl>
              )}
              {affordabilityDiag && (
                <details className="notes-raw">
                  <summary>Raw affordability math</summary>
                  <pre>{JSON.stringify(affordabilityDiag, null, 2)}</pre>
                </details>
              )}
            </div>
          )}
          {(primaryFailedGate ||
            nearMissExplanation ||
            Object.keys(cycleSummary?.recent_failed_gate_counts ?? {}).length !== 0) && (
            <div className="why-line">
              <strong>Near-miss diagnostics:</strong>
              {primaryFailedGate && (
                <div>
                  Most common recent failed gate: <span className="mono">{humanizeFailedGate(primaryFailedGate)}</span>
                </div>
              )}
              {nearMissExplanation && <div>Current near-miss: {nearMissExplanation}</div>}
              {cycleSummary && Object.keys(cycleSummary.recent_failed_gate_counts ?? {}).length > 0 && (
                <div>
                  Recent failed gate counts:{" "}
                  {Object.entries(cycleSummary.recent_failed_gate_counts)
                    .map(([k, v]) => `${humanizeFailedGate(k)}=${v}`)
                    .join(" · ")}
                </div>
              )}
            </div>
          )}
        </article>
      )}
    </section>
  );
}
