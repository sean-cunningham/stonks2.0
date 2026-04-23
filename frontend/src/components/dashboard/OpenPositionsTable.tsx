import type { DashboardResponse } from "../../types/dashboard";
import { humanizeMonitorState } from "../../utils/dashboardHumanize";
import { formatEasternDateTime } from "../../utils/formatEasternTime";

type Position = DashboardResponse["open_positions"][number];

type Props = {
  rows: Position[];
  emergencyCloseSupported: boolean;
  disableActions: boolean;
  onCloseNow: (paperTradeId: number, optionSymbol: string) => void;
};

function money(v: number | null): string {
  if (v === null || Number.isNaN(v)) return "n/a";
  return `$${v.toFixed(2)}`;
}

export default function OpenPositionsTable({
  rows,
  emergencyCloseSupported,
  disableActions,
  onCloseNow,
}: Props) {
  return (
    <section className="panel">
      <h2>Open positions</h2>
      {rows.length === 0 ? (
        <div className="empty empty-prose">
          <p>Flat book — no open paper positions.</p>
          <p className="muted small-print">
            New entries need the bot allowed to trade, a live call or put setup, and passing paper checks. See{" "}
            <a href="#panel-signal-blockers">current trading status</a> above when the scheduler is running.
          </p>
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Trade ID</th>
                <th>Contract</th>
                <th>Entered (ET)</th>
                <th>Qty</th>
                <th>Mark</th>
                <th>Unrealized P&amp;L</th>
                <th>Position state</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.paper_trade_id}>
                  <td>{r.paper_trade_id}</td>
                  <td className="mono">{r.option_symbol}</td>
                  <td>{formatEasternDateTime(r.entry_time)}</td>
                  <td>{r.quantity}</td>
                  <td>{money(r.mark_price)}</td>
                  <td>{money(r.unrealized_pnl)}</td>
                  <td>
                    <span title={r.monitor_state ?? ""}>{humanizeMonitorState(r.monitor_state)}</span>
                    {r.monitor_state && (
                      <details className="technical-inline nested">
                        <summary>Raw</summary>
                        <code>{r.monitor_state}</code>
                      </details>
                    )}
                  </td>
                  <td>
                    <button
                      disabled={disableActions || !emergencyCloseSupported}
                      title={!emergencyCloseSupported ? "Emergency close not supported for this strategy view" : undefined}
                      onClick={() => onCloseNow(r.paper_trade_id, r.option_symbol)}
                    >
                      Close now
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
