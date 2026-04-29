import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import StrategyDashboardShell from "../components/dashboard/StrategyDashboardShell";
import {
  closeNow,
  emergencyCloseUnquoted,
  fetchDashboard,
  fetchStrategyCatalog,
  resetDashboardStats,
  setEntryEnabled,
  setExitEnabled,
  setPause,
  type StrategyCatalogItem,
} from "../api/strategyDashboard";
import { buildStrategy1ViewModel } from "../strategies/strategy1/buildViewModel";
import { buildStrategy2ViewModel } from "../strategies/strategy2/buildViewModel";
import type { DashboardResponse } from "../types/dashboard";

const POLL_MS = 5000;
const STRATEGY_NAME_OVERRIDES: Record<string, string> = {
  strategy_1_spy_continuation: "SPY Trend Continuation",
  strategy_2_spy_0dte_vol_sniper: "SPY Fast Move Sniper (0DTE)",
};

/**
 * Poll every `intervalMs` only while the document is visible; clear the interval while hidden.
 */
function useVisibilityPoll(callback: () => void, intervalMs: number): void {
  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | undefined;

    const tick = () => {
      if (document.visibilityState === "visible") {
        void callback();
      }
    };

    const arm = () => {
      if (timer !== undefined) {
        clearInterval(timer);
        timer = undefined;
      }
      if (document.visibilityState !== "visible") {
        return;
      }
      tick();
      timer = setInterval(tick, intervalMs);
    };

    arm();

    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        tick();
        arm();
      } else if (timer !== undefined) {
        clearInterval(timer);
        timer = undefined;
      }
    };

    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      if (timer !== undefined) clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [callback, intervalMs]);
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const { symbol = "spy", strategyId = "strategy-1" } = useParams();
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [catalog, setCatalog] = useState<StrategyCatalogItem[]>([]);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    const loadCatalog = async () => {
      try {
        const out = await fetchStrategyCatalog();
        if (active) setCatalog(out.strategies);
      } catch {
        // Keep dashboard usable even if catalog endpoint temporarily fails.
      }
    };
    void loadCatalog();
    return () => {
      active = false;
    };
  }, []);

  const load = useCallback(async () => {
    try {
      const out = await fetchDashboard(symbol, strategyId);
      setData(out);
      setFetchError(null);
      setActionError(null);
    } catch (err) {
      setFetchError(err instanceof Error ? err.message : String(err));
    }
  }, [symbol, strategyId]);

  useVisibilityPoll(load, POLL_MS);

  const vm = useMemo(() => {
    if (!data) return null;
    if (symbol.toLowerCase() === "spy" && strategyId === "strategy-1") {
      return buildStrategy1ViewModel(data);
    }
    if (symbol.toLowerCase() === "spy" && strategyId === "strategy-2") {
      return buildStrategy2ViewModel(data);
    }
    return null;
  }, [data, strategyId, symbol]);

  const runAction = useCallback(
    async (fn: () => Promise<unknown>) => {
      setBusy(true);
      setActionError(null);
      try {
        await fn();
        await load();
      } catch (err) {
        setActionError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [load]
  );

  const strategyOptions = useMemo(() => {
    const symbolUpper = symbol.toUpperCase();
    const mapCatalogIdToRouteId = (id: string): string => {
      const n = id.match(/^strategy_(\d+)_/);
      return n ? `strategy-${n[1]}` : id;
    };
    return catalog
      .filter((s) => s.universe.some((u) => u.toUpperCase() === symbolUpper))
      .map((s) => ({ label: STRATEGY_NAME_OVERRIDES[s.id] ?? s.name, value: mapCatalogIdToRouteId(s.id) }));
  }, [catalog, symbol]);

  if (fetchError && !data) {
    return <main className="page">Error loading dashboard: {fetchError}</main>;
  }
  if (!vm) {
    return <main className="page">Loading dashboard...</main>;
  }

  return (
    <>
      {fetchError && <div className="error-strip">Refresh failed: {fetchError}</div>}
      {actionError && <div className="error-strip">Action failed: {actionError}</div>}
      <StrategyDashboardShell
        vm={vm}
        strategyOptions={strategyOptions}
        selectedStrategyId={strategyId}
        actionBusy={busy}
        onStrategyChange={(nextStrategyId) => navigate(`/paper/strategy/${symbol}/${nextStrategyId}`)}
        onBackToStrategies={() => navigate("/paper/strategies")}
        onPauseToggle={() => runAction(() => setPause(symbol, strategyId, !vm.runtime.paused))}
        onEntryToggle={() => runAction(() => setEntryEnabled(symbol, strategyId, !vm.runtime.entry_enabled))}
        onExitToggle={() => runAction(() => setExitEnabled(symbol, strategyId, !vm.runtime.exit_enabled))}
        onResetStats={() => {
          const ok = window.confirm(
            "Reset dashboard stats baseline?\n\nThis keeps historical trades but restarts metrics/charts from the current account state."
          );
          if (!ok) return;
          void runAction(() => resetDashboardStats(symbol, strategyId));
        }}
        onCloseNow={(paperTradeId, optionSymbol) => {
          const ok = window.confirm(
            `Emergency Close Now?\n\nTrade #${paperTradeId}\n${optionSymbol}\n\nThis is an immediate manual override.`
          );
          if (!ok) return;
          void runAction(() => closeNow(symbol, strategyId, paperTradeId));
        }}
        showPaperEmergencyUnquoted={symbol.toLowerCase() === "spy" && strategyId === "strategy-1"}
        onEmergencyCloseUnquoted={
          symbol.toLowerCase() === "spy" && strategyId === "strategy-1"
            ? (paperTradeId, optionSymbol) => {
                const ok = window.confirm(
                  `Paper emergency close?\n\nTrade #${paperTradeId}\n${optionSymbol}\n\nUses the live option bid when available; only uses a $0 synthetic exit if no quote can be fetched.`
                );
                if (!ok) return;
                void runAction(() => emergencyCloseUnquoted(symbol, strategyId, paperTradeId));
              }
            : undefined
        }
      />
    </>
  );
}
