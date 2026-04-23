import { humanizeMarketBlockReason } from "../../utils/dashboardHumanize";

type Props = {
  details: Record<string, unknown>;
};

export default function StrategyDetailsPanel({ details }: Props) {
  const stateCounts = (details.open_monitor_state_counts as Record<string, number> | undefined) ?? {};
  const stateRows = Object.entries(stateCounts);
  const marketReady = details.market_ready as boolean | undefined;
  const marketBlock = details.market_block_reason as string | undefined;
  const rootCause = details.root_cause_note as string | undefined;
  const hasAny =
    marketReady !== undefined || marketBlock !== undefined || stateRows.length > 0 || Boolean(rootCause);

  return (
    <section className="panel">
      <h2>Strategy health</h2>
      {!hasAny ? (
        <div className="empty">No strategy-specific details from the server.</div>
      ) : (
        <>
          <div className="details-cards">
            <div className="detail-card">
              <div className="detail-card-label">Market data ready</div>
              <div className="detail-card-value">
                {marketReady === undefined ? "Unknown" : marketReady ? "Yes" : "No"}
              </div>
            </div>
            <div className="detail-card">
              <div className="detail-card-label">Market status</div>
              <div className="detail-card-value">{humanizeMarketBlockReason(marketBlock)}</div>
            </div>
            {stateRows.length > 0 && (
              <div className="detail-card detail-card-wide">
                <div className="detail-card-label">Open position states</div>
                <div className="detail-card-value">
                  {stateRows.map(([k, v]) => (
                    <span key={k} className="detail-chip">
                      {k.replace(/_/g, " ")}: <strong>{v}</strong>
                    </span>
                  ))}
                </div>
              </div>
            )}
            {rootCause && (
              <div className="detail-card detail-card-wide">
                <div className="detail-card-label">Operational note</div>
                <div className="detail-card-value detail-prose">{rootCause}</div>
              </div>
            )}
          </div>

          <details className="technical-details strategy-technical">
            <summary>Technical details (raw fields)</summary>
            <pre className="technical-pre">
              {JSON.stringify(
                {
                  market_ready: marketReady,
                  market_block_reason: marketBlock,
                  open_monitor_state_counts: stateCounts,
                  root_cause_note: rootCause,
                },
                null,
                2
              )}
            </pre>
          </details>
        </>
      )}
    </section>
  );
}
