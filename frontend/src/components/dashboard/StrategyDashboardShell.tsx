import type { StrategyDashboardViewModel } from "../../types/dashboard";
import { formatEasternDateTime } from "../../utils/formatEasternTime";
import RuntimeHealthBanner from "./RuntimeHealthBanner";
import RuntimeControlsPanel from "./RuntimeControlsPanel";
import HeadlineMetricsCards from "./HeadlineMetricsCards";
import EquityChartPanel from "./EquityChartPanel";
import CashChartPanel from "./CashChartPanel";
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
  onCloseNow: (paperTradeId: number, optionSymbol: string) => void;
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
        <div className="muted">Last updated: {formatEasternDateTime(vm.asOf)}</div>
      </header>

      <SignalBlockerPanel signal={vm.currentSignal} cycleSummary={vm.cycleSummary} />

      <RuntimeHealthBanner runtime={vm.runtime} limitations={vm.limitations} />
      <RuntimeControlsPanel
        runtime={vm.runtime}
        controls={vm.controls}
        disableActions={actionBusy}
        onPauseToggle={onPauseToggle}
        onEntryToggle={onEntryToggle}
        onExitToggle={onExitToggle}
      />

      <HeadlineMetricsCards metrics={vm.metrics} />
      <EquityChartPanel
        equityPoints={vm.equitySeries}
        returnPctPoints={vm.equityReturnSeries}
        isMinimalViable={vm.equitySeriesIsMinimalViable}
      />
      <CashChartPanel points={vm.cashSeries} />
      <OpenPositionsTable
        rows={vm.openPositions}
        emergencyCloseSupported={vm.controls.emergency_close_supported}
        disableActions={actionBusy}
        onCloseNow={onCloseNow}
      />
      <ClosedTradesTable rows={vm.closedTrades} />
      <CycleHistoryTable rows={vm.cycleHistory} />
      <LimitationsPanel limitations={vm.limitations} />
      <StrategyDetailsPanel details={vm.strategyDetails} />
    </main>
  );
}
