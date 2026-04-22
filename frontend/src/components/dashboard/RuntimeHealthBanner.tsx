import type { RuntimeView } from "../../types/dashboard";

type Props = {
  runtime: RuntimeView;
  limitations: string[];
};

export default function RuntimeHealthBanner({ runtime, limitations }: Props) {
  const hasError = Boolean(runtime.last_error);
  const scheduler = runtime.scheduler_enabled ? "enabled" : "disabled";
  const paused = runtime.paused ? "paused" : "active";

  return (
    <section className={`banner ${hasError ? "banner-error" : ""}`}>
      <div>
        <strong>Runtime:</strong> scheduler {scheduler}, {paused}, last cycle {runtime.last_cycle_result ?? "n/a"}
      </div>
      {runtime.last_error && (
        <div>
          <strong>Last error:</strong> {runtime.last_error}
        </div>
      )}
      {limitations.length > 0 && (
        <div>
          <strong>Limitations:</strong> {limitations.join(" | ")}
        </div>
      )}
    </section>
  );
}
