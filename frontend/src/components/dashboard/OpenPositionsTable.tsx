import type { DashboardResponse } from "../../types/dashboard";
import { humanizeMonitorState, humanizeQuoteBlockerCode } from "../../utils/dashboardHumanize";
import { formatEasternDateTime } from "../../utils/formatEasternTime";

type Position = DashboardResponse["open_positions"][number];

type Props = {
  rows: Position[];
  emergencyCloseSupported: boolean;
  /** Strategy 1 paper: show unquoted emergency close (paper-only). */
  showPaperEmergencyUnquoted?: boolean;
  disableActions: boolean;
  onCloseNow: (paperTradeId: number, optionSymbol: string) => void;
  onEmergencyCloseUnquoted?: (paperTradeId: number, optionSymbol: string) => void;
};

function money(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
  return `$${v.toFixed(2)}`;
}

function pct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
  const p = v * 100;
  const sign = p > 0 ? "+" : "";
  return `${sign}${p.toFixed(2)}%`;
}

function parseOccOption(optionSymbol: string): { expiry: string | null; strike: string | null } {
  const s = optionSymbol.trim();
  const m = s.match(/(\d{6})([CP])(\d{8})$/);
  if (!m) return { expiry: null, strike: null };
  const y = Number(m[1].slice(0, 2));
  const month = Number(m[1].slice(2, 4));
  const day = Number(m[1].slice(4, 6));
  const year = 2000 + y;
  const strikeRaw = Number(m[3]);
  const strike = (strikeRaw / 1000).toFixed(2);
  const expiry = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  return { expiry, strike };
}

export default function OpenPositionsTable({
  rows,
  emergencyCloseSupported,
  showPaperEmergencyUnquoted = false,
  disableActions,
  onCloseNow,
  onEmergencyCloseUnquoted,
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
                <th>Expiry</th>
                <th>Strike</th>
                <th>Entered (ET)</th>
                <th>Qty</th>
                <th>Mark</th>
                <th>P&amp;L %</th>
                <th>Unrealized P&amp;L</th>
                <th>Stop / Target</th>
                <th>Quotes &amp; context</th>
                <th>Position state</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const parsed = parseOccOption(r.option_symbol);
                const exitReasons = (r.exit_blocked_reasons ?? []).filter(Boolean);
                return (
                  <tr key={r.paper_trade_id}>
                    <td>{r.paper_trade_id}</td>
                    <td className="mono">{r.option_symbol}</td>
                    <td>{parsed.expiry ?? "n/a"}</td>
                    <td>{parsed.strike ?? "n/a"}</td>
                    <td>{formatEasternDateTime(r.entry_time)}</td>
                    <td>{r.quantity}</td>
                    <td>{money(r.mark_price)}</td>
                    <td>{pct(r.unrealized_pnl_pct)}</td>
                    <td>{money(r.unrealized_pnl)}</td>
                    <td>
                      <div className="small-print">
                        <div>SL: {money(r.stop_price ?? null)}</div>
                        <div>TP: {money(r.take_profit_price ?? null)}</div>
                      </div>
                    </td>
                    <td className="small-print">
                      <div>Entry SPY: {money(r.entry_underlying_price ?? null)}</div>
                      <div>
                        Bid / Ask: {money(r.current_bid ?? null)} / {money(r.current_ask ?? null)}
                      </div>
                      <div>
                        Quote: {r.quote_resolution_source ?? "—"}{" "}
                        {r.quote_timestamp ? formatEasternDateTime(r.quote_timestamp) : ""}
                      </div>
                      <div title={r.quote_blocker_code ?? ""}>
                        Quote block: {humanizeQuoteBlockerCode(r.quote_blocker_code ?? null)}
                      </div>
                      {exitReasons.length > 0 && (
                        <details className="technical-inline nested">
                          <summary>Exit eval blockers</summary>
                          <code>{exitReasons.join(", ")}</code>
                        </details>
                      )}
                    </td>
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
                      <div style={{ display: "flex", flexDirection: "column", gap: "0.45rem" }}>
                        <button
                          type="button"
                          disabled={disableActions || !emergencyCloseSupported}
                          title={
                            !emergencyCloseSupported
                              ? "Emergency close not supported for this strategy view"
                              : "Close at bid using a fresh quote (requires quotable leg)"
                          }
                          onClick={() => onCloseNow(r.paper_trade_id, r.option_symbol)}
                        >
                          Close now
                        </button>
                        {showPaperEmergencyUnquoted && onEmergencyCloseUnquoted && (
                          <button
                            type="button"
                            disabled={disableActions}
                            title="Paper only: tries live option bid first; $0 only if no quote"
                            onClick={() => onEmergencyCloseUnquoted(r.paper_trade_id, r.option_symbol)}
                          >
                            Emergency (unquoted)
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
