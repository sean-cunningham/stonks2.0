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
  strategyOptions: Array<{ label: string; value: string }>;
  selectedStrategyId: string;
  actionBusy: boolean;
  onStrategyChange: (strategyId: string) => void;
  onPauseToggle: () => void;
  onPauseAllToggle: () => void;
  onEntryToggle: () => void;
  onExitToggle: () => void;
  onResetStats: () => void;
  onCloseNow: (paperTradeId: number, optionSymbol: string) => void;
  showPaperEmergencyUnquoted?: boolean;
  onEmergencyCloseUnquoted?: (paperTradeId: number, optionSymbol: string) => void;
};

export default function StrategyDashboardShell({
  vm,
  strategyOptions,
  selectedStrategyId,
  actionBusy,
  onStrategyChange,
  onPauseToggle,
  onPauseAllToggle,
  onEntryToggle,
  onExitToggle,
  onResetStats,
  onCloseNow,
  showPaperEmergencyUnquoted = false,
  onEmergencyCloseUnquoted,
}: Props) {
  return (
    <main className="page">
      <header className="page-header">
        <div>
          <h1>{vm.title}</h1>
          <div className="muted">Last updated: {formatEasternDateTime(vm.asOf)}</div>
        </div>
        <div className="header-controls">
          <label className="muted">
            Strategy
            <select
              className="strategy-select"
              value={selectedStrategyId}
              onChange={(e) => onStrategyChange(e.target.value)}
              disabled={actionBusy || strategyOptions.length === 0}
            >
              {strategyOptions.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>

      <SignalBlockerPanel signal={vm.currentSignal} cycleSummary={vm.cycleSummary} />

      <RuntimeHealthBanner runtime={vm.runtime} limitations={vm.limitations} />
      <RuntimeControlsPanel
        runtime={vm.runtime}
        controls={vm.controls}
        disableActions={actionBusy}
        onPauseToggle={onPauseToggle}
        onPauseAllToggle={onPauseAllToggle}
        onEntryToggle={onEntryToggle}
        onExitToggle={onExitToggle}
        onResetStats={onResetStats}
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
        showPaperEmergencyUnquoted={showPaperEmergencyUnquoted}
        disableActions={actionBusy}
        onCloseNow={onCloseNow}
        onEmergencyCloseUnquoted={onEmergencyCloseUnquoted}
      />
      <ClosedTradesTable rows={vm.closedTrades} />
      <CycleHistoryTable rows={vm.cycleHistory} />
      <LimitationsPanel limitations={vm.limitations} />
      <StrategyDetailsPanel details={vm.strategyDetails} />
    </main>
  );
}
