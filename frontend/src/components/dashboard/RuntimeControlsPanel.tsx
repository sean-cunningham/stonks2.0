import type { RuntimeView } from "../../types/dashboard";

type Props = {
  runtime: RuntimeView;
  disableActions: boolean;
  onPauseToggle: () => void;
  onEntryToggle: () => void;
  onExitToggle: () => void;
};

export default function RuntimeControlsPanel({
  runtime,
  disableActions,
  onPauseToggle,
  onEntryToggle,
  onExitToggle,
}: Props) {
  return (
    <section className="panel">
      <h2>Runtime Controls</h2>
      <div className="runtime-grid">
        <div>Scheduler: {runtime.scheduler_enabled ? "Enabled" : "Disabled"}</div>
        <div>Paused: {runtime.paused ? "Yes" : "No"}</div>
        <div>Entry enabled: {runtime.entry_enabled ? "Yes" : "No"}</div>
        <div>Exit enabled: {runtime.exit_enabled ? "Yes" : "No"}</div>
        <div>In progress: {runtime.running ? "Yes" : "No"}</div>
        <div>Last cycle result: {runtime.last_cycle_result ?? "n/a"}</div>
      </div>
      <div className="actions">
        <button disabled={disableActions} onClick={onPauseToggle}>
          {runtime.paused ? "Resume" : "Pause"}
        </button>
        <button disabled={disableActions} onClick={onEntryToggle}>
          {runtime.entry_enabled ? "Disable Entry" : "Enable Entry"}
        </button>
        <button disabled={disableActions} onClick={onExitToggle}>
          {runtime.exit_enabled ? "Disable Exit" : "Enable Exit"}
        </button>
      </div>
    </section>
  );
}
