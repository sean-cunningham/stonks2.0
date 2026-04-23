import type { DashboardResponse, RuntimeView } from "../../types/dashboard";

type Props = {
  runtime: RuntimeView;
  controls: DashboardResponse["controls"];
  disableActions: boolean;
  onPauseToggle: () => void;
  onEntryToggle: () => void;
  onExitToggle: () => void;
};

export default function RuntimeControlsPanel({
  runtime,
  controls,
  disableActions,
  onPauseToggle,
  onEntryToggle,
  onExitToggle,
}: Props) {
  const pauseDisabled = disableActions || !controls.can_pause_resume;
  const entryDisabled = disableActions || !controls.can_toggle_entry;
  const exitDisabled = disableActions || !controls.can_toggle_exit;

  return (
    <section className="panel">
      <h2>Bot controls</h2>
      <div className="runtime-grid">
        <div>Scheduler: {runtime.scheduler_enabled ? "On" : "Off"}</div>
        <div>Paused: {runtime.paused ? "Yes" : "No"}</div>
        <div>New entries: {runtime.entry_enabled ? "Allowed" : "Blocked"}</div>
        <div>Automatic exits: {runtime.exit_enabled ? "Allowed" : "Blocked"}</div>
        <div>Cycle running: {runtime.running ? "Yes" : "No"}</div>
      </div>
      <div className="actions">
        <button disabled={pauseDisabled} onClick={onPauseToggle} title={!controls.can_pause_resume ? "Not allowed by server" : undefined}>
          {runtime.paused ? "Resume" : "Pause"}
        </button>
        <button
          disabled={entryDisabled}
          onClick={onEntryToggle}
          title={!controls.can_toggle_entry ? "Not allowed by server" : undefined}
        >
          {runtime.entry_enabled ? "Block new entries" : "Allow new entries"}
        </button>
        <button disabled={exitDisabled} onClick={onExitToggle} title={!controls.can_toggle_exit ? "Not allowed by server" : undefined}>
          {runtime.exit_enabled ? "Block automatic exits" : "Allow automatic exits"}
        </button>
      </div>
    </section>
  );
}
