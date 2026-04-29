import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  fetchDashboard,
  fetchStrategyCatalog,
  setPause,
  type StrategyCatalogItem,
} from "../api/strategyDashboard";
import type { DashboardResponse } from "../types/dashboard";

const POLL_MS = 5000;

type StrategyRow = {
  catalogId: string;
  routeStrategyId: string;
  name: string;
  symbol: string;
  description: string;
  health: "healthy" | "unhealthy";
  traffic: "green" | "yellow" | "red";
  statusText: string;
  reasonLines: string[];
  paused: boolean;
  tradeCount: number;
  winRate: number | null;
  totalPnl: number;
};

const SIMPLE_EXPLANATIONS: Record<string, string> = {
  "strategy-1":
    "Looks for clean SPY continuation moves and trades with strict risk and exit rules.",
  "strategy-2":
    "Looks for fast SPY volatility impulse setups with tighter timing and quality checks.",
};

const STRATEGY_NAME_OVERRIDES: Record<string, string> = {
  strategy_1_spy_continuation: "SPY Trend Continuation",
  strategy_2_spy_0dte_vol_sniper: "SPY Fast Move Sniper (0DTE)",
};

function mapCatalogIdToRouteId(id: string): string {
  const n = id.match(/^strategy_(\d+)_/);
  return n ? `strategy-${n[1]}` : id;
}

function hasStrategyBlocker(blockers: string[], code: string): boolean {
  return blockers.some((b) => b === code || b.startsWith(`${code}:`));
}

function toHealth(d: DashboardResponse): { health: "healthy" | "unhealthy"; reasons: string[] } {
  const rt = d.runtime;
  const reasons: string[] = [];
  const marketReady = Boolean(d.strategy_details?.market_ready ?? false);
  const marketBlock = String(d.strategy_details?.market_block_reason ?? "none");
  const blockers = d.current_signal?.current_blockers ?? [];

  if (rt.last_error) reasons.push(`Runtime error: ${rt.last_error}`);
  if (!marketReady) reasons.push(`Market feed not ready: ${marketBlock === "none" ? "unknown reason" : marketBlock}`);
  if (hasStrategyBlocker(blockers, "context_not_live_ready:stale_1m_bars")) {
    reasons.push("Context data is stale: 1-minute bars are behind expected time.");
  }
  if (hasStrategyBlocker(blockers, "context_not_live_ready:stale_5m_bars")) {
    reasons.push("Context data is stale: 5-minute bars are behind expected time.");
  }
  if (hasStrategyBlocker(blockers, "market_not_ready:stale_quote")) {
    reasons.push("Quote data is stale (threshold 15 seconds).");
  }
  if (hasStrategyBlocker(blockers, "market_not_ready:stale_chain")) {
    reasons.push("Option chain data is stale (threshold 60 seconds).");
  }

  if (reasons.length > 0) return { health: "unhealthy", reasons };
  return { health: "healthy", reasons: [] };
}

function toTrafficAndReasons(
  d: DashboardResponse,
  health: "healthy" | "unhealthy"
): { traffic: "green" | "yellow" | "red"; statusText: string; reasonLines: string[] } {
  const rt = d.runtime;
  const blockers = d.current_signal?.current_blockers ?? [];
  const reasonLines: string[] = [];

  const isRunning = rt.scheduler_enabled && !rt.paused;
  const strategyWindowClosed =
    d.strategy.strategy_id === "strategy_2_spy_0dte_vol_sniper" && hasStrategyBlocker(blockers, "outside_strategy_2_entry_window");
  const marketClosed = rt.runtime_sleep_reason === "outside_rth" || !rt.market_window_open;
  const entriesBlocked = !rt.entry_enabled;
  const tradingEligible = isRunning && !marketClosed && !strategyWindowClosed && !entriesBlocked;

  if (!rt.scheduler_enabled) reasonLines.push("Scheduler is disabled.");
  if (rt.paused) reasonLines.push("Strategy is paused.");
  if (marketClosed) reasonLines.push("Market is closed (US/Eastern regular hours: 9:30 AM to 4:00 PM).");
  if (strategyWindowClosed) {
    reasonLines.push(
      "Strategy 2 entry window is closed. Allowed windows: 9:45 AM to 11:30 AM ET and 1:45 PM to 3:45 PM ET."
    );
  }
  if (entriesBlocked) reasonLines.push("New entries are currently blocked.");
  if (!rt.exit_enabled) reasonLines.push("Automatic exits are currently blocked.");

  if (health === "unhealthy") {
    return {
      traffic: "red",
      statusText: "Needs attention",
      reasonLines: [...reasonLines],
    };
  }
  if (!isRunning) {
    return {
      traffic: "red",
      statusText: "Not running",
      reasonLines: reasonLines.length ? reasonLines : ["Scheduler is off or strategy is paused."],
    };
  }
  if (!tradingEligible) {
    return {
      traffic: "yellow",
      statusText: "Running, not trading",
      reasonLines: reasonLines.length ? reasonLines : ["Running normally, waiting for eligible market/setup window."],
    };
  }
  return {
    traffic: "green",
    statusText: "Running, trading, healthy",
    reasonLines: ["Running and healthy. Strategy is currently eligible to trade."],
  };
}

function formatPct(v: number | null): string {
  if (v === null || Number.isNaN(v)) return "--";
  return `${(v * 100).toFixed(1)}%`;
}

function formatUsd(v: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(v);
}

export default function StrategiesPage() {
  const [rows, setRows] = useState<StrategyRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyById, setBusyById] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    try {
      const catalog = await fetchStrategyCatalog();
      const relevant = catalog.strategies.filter((s) => s.universe.some((u) => u.toUpperCase() === "SPY"));
      const dashboards = await Promise.all(
        relevant.map(async (item: StrategyCatalogItem) => {
          const routeStrategyId = mapCatalogIdToRouteId(item.id);
          const symbol = (item.universe[0] ?? "SPY").toLowerCase();
          const d = await fetchDashboard(symbol, routeStrategyId);
          const { health, reasons: healthReasons } = toHealth(d);
          const { traffic, statusText, reasonLines } = toTrafficAndReasons(d, health);
          const row: StrategyRow = {
            catalogId: item.id,
            routeStrategyId,
            name: STRATEGY_NAME_OVERRIDES[item.id] ?? item.name,
            symbol,
            description: SIMPLE_EXPLANATIONS[routeStrategyId] ?? "Automated strategy with independent runtime controls.",
            health,
            traffic,
            statusText,
            reasonLines: [...healthReasons, ...reasonLines],
            paused: d.runtime.paused,
            tradeCount: d.headline_metrics.trade_count,
            winRate: d.headline_metrics.win_rate,
            totalPnl: d.headline_metrics.total_pnl,
          };
          return row;
        })
      );
      setRows(dashboards);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") {
        void load();
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  const onPauseToggle = useCallback(
    async (row: StrategyRow) => {
      try {
        setBusyById((prev) => ({ ...prev, [row.catalogId]: true }));
        await setPause(row.symbol, row.routeStrategyId, !row.paused);
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusyById((prev) => ({ ...prev, [row.catalogId]: false }));
      }
    },
    [load]
  );

  return (
    <main className="page">
      <header className="page-header">
        <div>
          <h1>Strategies</h1>
          <div className="muted">Overview of active paper strategies and runtime controls.</div>
        </div>
      </header>

      {error && <div className="error-strip">Action failed: {error}</div>}

      <section className="panel table-wrap">
        <table>
          <thead>
            <tr>
              <th></th>
              <th>Strategy</th>
              <th>Status</th>
              <th>Trades</th>
              <th>Win Rate</th>
              <th>Gain (Loss)</th>
              <th>What It Does</th>
              <th>Why</th>
              <th>Control</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.catalogId} className={row.health === "unhealthy" ? "strategy-row-unhealthy" : undefined}>
                <td>
                  <span
                    className={`status-dot status-dot-${row.traffic}`}
                    aria-label={`Status ${row.traffic}`}
                    title={row.statusText}
                  />
                </td>
                <td>
                  <Link to={`/paper/strategy/${row.symbol}/${row.routeStrategyId}`}>{row.name}</Link>
                </td>
                <td>{row.statusText}</td>
                <td>{row.tradeCount}</td>
                <td>{formatPct(row.winRate)}</td>
                <td>{formatUsd(row.totalPnl)}</td>
                <td>{row.description}</td>
                <td>
                  {row.reasonLines.length ? (
                    <ul className="strategy-reasons">
                      {row.reasonLines.map((line) => (
                        <li key={`${row.catalogId}-${line}`}>{line}</li>
                      ))}
                    </ul>
                  ) : (
                    <span className="muted">None</span>
                  )}
                </td>
                <td>
                  <button
                    onClick={() => void onPauseToggle(row)}
                    disabled={Boolean(busyById[row.catalogId])}
                  >
                    {row.paused ? "Resume" : "Pause"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && !loading && <div className="empty">No strategies available.</div>}
        {loading && <div className="empty">Loading strategies...</div>}
      </section>
    </main>
  );
}

