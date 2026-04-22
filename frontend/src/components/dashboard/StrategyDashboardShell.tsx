import type { StrategyDashboardViewModel } from "../../types/dashboard";
import RuntimeHealthBanner from "./RuntimeHealthBanner";
import RuntimeControlsPanel from "./RuntimeControlsPanel";
import HeadlineMetricsCards from "./HeadlineMetricsCards";
import EquityChartPanel from "./EquityChartPanel";
import OpenPositionsTable from "./OpenPositionsTable";
import ClosedTradesTable from "./ClosedTradesTable";
import CycleHistoryTable from "./CycleHistoryTable";
import LimitationsPanel from "./LimitationsPanel";
import StrategyDetailsPanel from "./StrategyDetailsPanel";
import SignalBlockerPanel from "./SignalBlockerPanel";

type Props = {
  vm: StrategyDashboardViewModel;
  actionBusy: boolean;
  onPauseToggle: () => void;
  onEntryToggle: () => void;
  onExitToggle: () => void;
  onCloseNow: (paperTradeId: number) => void;
};

export default function StrategyDashboardShell({
  vm,
  actionBusy,
  onPauseToggle,
  onEntryToggle,
  onExitToggle,
  onCloseNow,
}: Props) {
  return (
    <main className="page">
      <header className="page-header">
        <h1>{vm.title}</h1>
        <div className="muted">Last updated: {new Date(vm.asOf).toLocaleString()}</div>
      </header>

      <RuntimeHealthBanner runtime={vm.runtime} limitations={vm.limitations} />
      <RuntimeControlsPanel
        runtime={vm.runtime}
        disableActions={actionBusy}
        onPauseToggle={onPauseToggle}
        onEntryToggle={onEntryToggle}
        onExitToggle={onExitToggle}
      />
      <SignalBlockerPanel signal={vm.currentSignal} cycleSummary={vm.cycleSummary} />

      <HeadlineMetricsCards metrics={vm.metrics} />
      <EquityChartPanel points={vm.equitySeries} />
      <OpenPositionsTable rows={vm.openPositions} disableActions={actionBusy} onCloseNow={onCloseNow} />
      <ClosedTradesTable rows={vm.closedTrades} />
      <CycleHistoryTable rows={vm.cycleHistory} />
      <LimitationsPanel limitations={vm.limitations} />
      <StrategyDetailsPanel details={vm.strategyDetails} />
    </main>
  );
}
