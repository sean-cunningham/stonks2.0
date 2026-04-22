type Props = {
  limitations: string[];
};

export default function LimitationsPanel({ limitations }: Props) {
  return (
    <section className="panel">
      <h2>Limitations / Errors</h2>
      {limitations.length === 0 ? (
        <div className="empty">No backend limitations reported.</div>
      ) : (
        <ul>
          {limitations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
