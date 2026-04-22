type Props = {
  details: Record<string, unknown>;
};

export default function StrategyDetailsPanel({ details }: Props) {
  const keys = Object.keys(details);
  return (
    <section className="panel">
      <h2>Strategy Details</h2>
      {keys.length === 0 ? (
        <div className="empty">No strategy-specific details.</div>
      ) : (
        <pre className="details-json">{JSON.stringify(details, null, 2)}</pre>
      )}
    </section>
  );
}
