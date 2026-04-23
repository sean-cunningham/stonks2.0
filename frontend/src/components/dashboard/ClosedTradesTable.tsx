import type { DashboardResponse } from "../../types/dashboard";

type Row = DashboardResponse["recent_closed_trades"][number];

type Props = {
  rows: Row[];
};

function money(v: number | null): string {
  if (v === null || Number.isNaN(v)) return "n/a";
  return `$${v.toFixed(2)}`;
}

export default function ClosedTradesTable({ rows }: Props) {
  return (
    <section className="panel">
      <h2>Recent closed trades</h2>
      {rows.length === 0 ? (
        <div className="empty empty-prose">
          <p>No closed trades in the recent window.</p>
          <p className="muted small-print">
            Paper session history builds as positions exit. Closed rows here are the latest slice from the server, not an
            all-time ledger.
          </p>
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Trade ID</th>
                <th>Contract</th>
                <th>Exit time</th>
                <th>Realized P&amp;L</th>
                <th>Exit reason</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={`${r.paper_trade_id}-${r.exit_time ?? "open"}`}>
                  <td>{r.paper_trade_id}</td>
                  <td className="mono">{r.option_symbol}</td>
                  <td>{r.exit_time ? new Date(r.exit_time).toLocaleString() : "n/a"}</td>
                  <td>{money(r.realized_pnl)}</td>
                  <td>{r.exit_reason ?? "n/a"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
