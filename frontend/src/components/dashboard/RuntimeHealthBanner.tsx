import type { RuntimeView } from "../../types/dashboard";
import { humanizeCycleResult, humanizeLimitation, humanizeRuntimeSleepReason } from "../../utils/dashboardHumanize";
import { formatEasternDateTime } from "../../utils/formatEasternTime";

type Props = {
  runtime: RuntimeView;
  limitations: string[];
  strategyDetails: Record<string, unknown>;
};

function formatCycleTime(iso: string | null | undefined): string | null {
  if (!iso) return null;
  return formatEasternDateTime(iso);
}

export default function RuntimeHealthBanner({ runtime, limitations, strategyDetails }: Props) {
  const hasError = Boolean(runtime.last_error);
  const marketReady = strategyDetails.market_ready === undefined ? true : Boolean(strategyDetails.market_ready);
  const marketBlockReason =
    typeof strategyDetails.market_block_reason === "string" ? strategyDetails.market_block_reason : "none";
  const isHealthy = !hasError && marketReady;
  const schedulerOn = runtime.scheduler_enabled;
  const paused = runtime.paused;
  const running = schedulerOn && !paused;
  const tradingEligible = running && runtime.market_window_open && runtime.entry_enabled;
  const lastStart = formatCycleTime(runtime.last_cycle_started_at);
  const lastFinish = formatCycleTime(runtime.last_cycle_finished_at);
  const sleepHuman = humanizeRuntimeSleepReason(runtime.runtime_sleep_reason ?? null);
  const marketOpen = runtime.market_window_open ?? false;
  const topStatus = !isHealthy
    ? "Needs attention"
    : tradingEligible
      ? "Running, trading, healthy"
      : running
        ? "Running, not trading, healthy"
        : "Not running, healthy";
  const statusBadgeClass = !isHealthy ? "status-dot-red" : tradingEligible ? "status-dot-green" : running ? "status-dot-yellow" : "status-dot-red";
  const windowLine = marketOpen
    ? "Regular market window (US/Eastern) is open."
    : "Regular market window (US/Eastern) is closed — scheduler will not run strategy cycles until it opens.";

  return (
    <section className={`banner ${!isHealthy ? "banner-error" : ""}`}>
      <div className="runtime-health-top">
        <span className={`status-dot ${statusBadgeClass}`} />
        <strong>{topStatus}</strong>
      </div>
      <div>
        <strong>Bot:</strong> scheduler is <strong>{schedulerOn ? "on" : "off"}</strong>, bot is{" "}
        <strong>{paused ? "paused" : "running"}</strong>. {windowLine}{" "}
        {runtime.entry_enabled ? "" : "New entries are blocked. "}
        {runtime.exit_enabled ? "" : "Automatic exits are blocked. "}
        {sleepHuman && (
          <>
            {" "}
            <strong>Idle reason:</strong> {sleepHuman}
          </>
        )}
        {!marketReady && (
          <>
            {" "}
            <strong>Market readiness:</strong> {marketBlockReason === "none" ? "not ready" : marketBlockReason}
          </>
        )}
      </div>
      <div>
        <strong>Last cycle:</strong> <strong>{humanizeCycleResult(runtime.last_cycle_result)}</strong>
        {lastStart && (
          <span className="muted">
            {" "}
            (started {lastStart}
            {lastFinish ? `, finished ${lastFinish}` : ""})
          </span>
        )}
      </div>
      <details className="technical-inline">
        <summary>Technical: raw runtime fields</summary>
        <pre className="technical-pre compact">
          {JSON.stringify(
            {
              market_window_open: marketOpen,
              runtime_sleep_reason: runtime.runtime_sleep_reason ?? null,
              last_cycle_result: runtime.last_cycle_result,
              last_error: runtime.last_error,
              lock_scope: runtime.lock_scope,
            },
            null,
            2
          )}
        </pre>
      </details>
      {limitations.length > 0 && (
        <div>
          <strong>Data caveats:</strong> {limitations.map((item) => humanizeLimitation(item)).join(" · ")}
        </div>
      )}
    </section>
  );
}
