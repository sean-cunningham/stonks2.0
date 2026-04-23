import { humanizeLimitation } from "../../utils/dashboardHumanize";

type Props = {
  limitations: string[];
};

export default function LimitationsPanel({ limitations }: Props) {
  return (
    <section className="panel">
      <h2>Data caveats</h2>
      {limitations.length === 0 ? (
        <div className="empty">No extra data caveats from the server.</div>
      ) : (
        <ul className="limitations-list">
          {limitations.map((item) => (
            <li key={item}>
              {humanizeLimitation(item)}
              <details className="technical-inline nested">
                <summary>Raw</summary>
                <code>{item}</code>
              </details>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
