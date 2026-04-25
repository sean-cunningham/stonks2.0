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
import { buildStrategy2ViewModel } from "../strategies/strategy2/buildViewModel";
import type { DashboardResponse } from "../types/dashboard";

const POLL_MS = 5000;

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
  const { symbol = "spy", strategyId = "strategy-1" } = useParams();
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
        actionBusy={busy}
        onPauseToggle={() => runAction(() => setPause(symbol, strategyId, !vm.runtime.paused))}
        onEntryToggle={() => runAction(() => setEntryEnabled(symbol, strategyId, !vm.runtime.entry_enabled))}
        onExitToggle={() => runAction(() => setExitEnabled(symbol, strategyId, !vm.runtime.exit_enabled))}
        onCloseNow={(paperTradeId, optionSymbol) => {
          const ok = window.confirm(
            `Emergency Close Now?\n\nTrade #${paperTradeId}\n${optionSymbol}\n\nThis is an immediate manual override.`
          );
          if (!ok) return;
          void runAction(() => closeNow(symbol, strategyId, paperTradeId));
        }}
      />
    </>
  );
}
