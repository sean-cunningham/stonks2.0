import type { DashboardResponse } from "../../types/dashboard";

type Position = DashboardResponse["open_positions"][number];

type Props = {
  rows: Position[];
  disableActions: boolean;
  onCloseNow: (paperTradeId: number) => void;
};

function money(v: number | null): string {
  if (v === null || Number.isNaN(v)) return "n/a";
  return `$${v.toFixed(2)}`;
}

export default function OpenPositionsTable({ rows, disableActions, onCloseNow }: Props) {
  return (
    <section className="panel">
      <h2>Open Positions</h2>
      {rows.length === 0 ? (
        <div className="empty">No open positions.</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Trade ID</th>
                <th>Contract</th>
                <th>Qty</th>
                <th>Mark</th>
                <th>Unrealized P&L</th>
                <th>Monitor State</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.paper_trade_id}>
                  <td>{r.paper_trade_id}</td>
                  <td>{r.option_symbol}</td>
                  <td>{r.quantity}</td>
                  <td>{money(r.mark_price)}</td>
                  <td>{money(r.unrealized_pnl)}</td>
                  <td>{r.monitor_state ?? "n/a"}</td>
                  <td>
                    <button disabled={disableActions} onClick={() => onCloseNow(r.paper_trade_id)}>
                      Close Now
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
