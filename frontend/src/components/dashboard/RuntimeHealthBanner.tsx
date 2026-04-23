import type { RuntimeView } from "../../types/dashboard";
import { humanizeCycleResult, humanizeLimitation } from "../../utils/dashboardHumanize";
import { formatEasternDateTime } from "../../utils/formatEasternTime";

type Props = {
  runtime: RuntimeView;
  limitations: string[];
};

function formatCycleTime(iso: string | null | undefined): string | null {
  if (!iso) return null;
  return formatEasternDateTime(iso);
}

export default function RuntimeHealthBanner({ runtime, limitations }: Props) {
  const hasError = Boolean(runtime.last_error);
  const schedulerOn = runtime.scheduler_enabled;
  const paused = runtime.paused;
  const lastStart = formatCycleTime(runtime.last_cycle_started_at);
  const lastFinish = formatCycleTime(runtime.last_cycle_finished_at);

  return (
    <section className={`banner ${hasError ? "banner-error" : ""}`}>
      <div>
        <strong>Bot:</strong> scheduler is <strong>{schedulerOn ? "on" : "off"}</strong>, bot is{" "}
        <strong>{paused ? "paused" : "running"}</strong>. Last cycle:{" "}
        <strong>{humanizeCycleResult(runtime.last_cycle_result)}</strong>
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
