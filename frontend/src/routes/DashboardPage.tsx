import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import StrategyDashboardShell from "../components/dashboard/StrategyDashboardShell";
import {
  closeNow,
  fetchDashboard,
  setEntryEnabled,
  setExitEnabled,
  setPause,
} from "../api/strategyDashboard";
import { buildStrategy1ViewModel } from "../strategies/strategy1/buildViewModel";
import type { DashboardResponse } from "../types/dashboard";

const POLL_MS = 5000;

function useVisibilityPoll(callback: () => void, intervalMs: number): void {
  useEffect(() => {
    callback();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") callback();
    }, intervalMs);
    const onVisibility = () => {
      if (document.visibilityState === "visible") callback();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [callback, intervalMs]);
}

export default function DashboardPage() {
  const { symbol = "spy", strategyId = "strategy-1" } = useParams();
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const out = await fetchDashboard(symbol, strategyId);
      setData(out);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [symbol, strategyId]);

  useVisibilityPoll(load, POLL_MS);

  const vm = useMemo(() => {
    if (!data) return null;
    if (symbol.toLowerCase() === "spy" && strategyId === "strategy-1") {
      return buildStrategy1ViewModel(data);
    }
    return null;
  }, [data, strategyId, symbol]);

  const runAction = useCallback(
    async (fn: () => Promise<unknown>) => {
      setBusy(true);
      try {
        await fn();
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [load]
  );

  if (error && !data) return <main className="page">Error loading dashboard: {error}</main>;
  if (!vm) return <main className="page">Loading dashboard...</main>;

  return (
    <>
      {error && <div className="error-strip">Action error: {error}</div>}
      <StrategyDashboardShell
        vm={vm}
        actionBusy={busy}
        onPauseToggle={() => runAction(() => setPause(symbol, strategyId, !vm.runtime.paused))}
        onEntryToggle={() => runAction(() => setEntryEnabled(symbol, strategyId, !vm.runtime.entry_enabled))}
        onExitToggle={() => runAction(() => setExitEnabled(symbol, strategyId, !vm.runtime.exit_enabled))}
        onCloseNow={(paperTradeId) => {
          const ok = window.confirm(
            `Emergency Close Now for paper trade ${paperTradeId}? This is an immediate manual override.`
          );
          if (!ok) return;
          void runAction(() => closeNow(symbol, strategyId, paperTradeId));
        }}
      />
    </>
  );
}
