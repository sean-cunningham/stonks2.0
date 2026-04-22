type Props = {
  details: Record<string, unknown>;
};

export default function StrategyDetailsPanel({ details }: Props) {
  const stateCounts = (details.open_monitor_state_counts as Record<string, number> | undefined) ?? {};
  const stateRows = Object.entries(stateCounts);
  const marketReady = details.market_ready as boolean | undefined;
  const marketBlock = details.market_block_reason as string | undefined;
  const rootCause = details.root_cause_note as string | undefined;
  return (
    <section className="panel">
      <h2>Strategy Details</h2>
      {!marketReady && !marketBlock && stateRows.length === 0 && !rootCause ? (
        <div className="empty">No strategy-specific details.</div>
      ) : (
        <div className="details-grid">
          <div>
            <strong>Market ready:</strong> {marketReady === undefined ? "n/a" : marketReady ? "Yes" : "No"}
          </div>
          <div>
            <strong>Market block reason:</strong> {marketBlock ?? "none"}
          </div>
          {stateRows.length > 0 && (
            <div>
              <strong>Open monitor state counts:</strong>{" "}
              {stateRows.map(([k, v]) => `${k}:${v}`).join(" | ")}
            </div>
          )}
          {rootCause && (
            <div>
              <strong>Root-cause visibility note:</strong> {rootCause}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
