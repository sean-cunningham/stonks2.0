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
      <h2>Strategy details</h2>
      {!hasAny ? (
        <div className="empty">No strategy-specific details.</div>
      ) : (
        <div className="details-cards">
          <div className="detail-card">
            <div className="detail-card-label">Market ready</div>
            <div className="detail-card-value">
              {marketReady === undefined ? "n/a" : marketReady ? "Yes" : "No"}
            </div>
          </div>
          <div className="detail-card">
            <div className="detail-card-label">Market block reason</div>
            <div className="detail-card-value mono">{marketBlock ?? "none"}</div>
          </div>
          {stateRows.length > 0 && (
            <div className="detail-card detail-card-wide">
              <div className="detail-card-label">Open monitor state counts</div>
              <div className="detail-card-value">
                {stateRows.map(([k, v]) => (
                  <span key={k} className="detail-chip">
                    {k}: <strong>{v}</strong>
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
      )}
    </section>
  );
}
