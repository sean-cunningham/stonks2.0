import type { DashboardResponse } from "../../types/dashboard";

type Row = DashboardResponse["recent_cycle_history"][number];

type Props = {
  rows: Row[];
};

function isAutoOpenFailed(notes: string | null | undefined): boolean {
  return Boolean(notes?.includes("auto_open_failed:"));
}

/** Badge label aligned with operational categories (may differ from raw `result`). */
function cycleDisplayLabel(row: Row): string {
  if (row.result === "opened") return "opened";
  if (row.result === "closed") return "closed";
  if (row.result === "error") return "error";
  if (row.result === "no_action" && isAutoOpenFailed(row.notes_summary)) return "blocked";
  if (row.result === "no_action") return "no_action";
  return row.result;
}

function badgeClass(row: Row): string {
  const label = cycleDisplayLabel(row);
  if (label === "opened") return "status-opened";
  if (label === "closed") return "status-closed";
  if (label === "error") return "status-error";
  if (label === "blocked") return "status-blocked";
  if (label === "no_action") return "status-noaction";
  return "status-default";
}

export default function CycleHistoryTable({ rows }: Props) {
  return (
    <section className="panel">
      <h2>Recent cycle history</h2>
      {rows.length === 0 ? (
        <div className="empty empty-prose">
          <p>No scheduler cycles in the recent window.</p>
          <p className="muted small-print">When the runtime scheduler runs, each cycle will appear here with status and notes.</p>
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Started</th>
                <th>Status</th>
                <th>Raw result</th>
                <th>Cycle action</th>
                <th>Error</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const label = cycleDisplayLabel(r);
                return (
                  <tr key={`${r.started_at}-${i}`}>
                    <td>{new Date(r.started_at).toLocaleString()}</td>
                    <td>
                      <span className={`status-badge ${badgeClass(r)}`} title={`Raw result: ${r.result}`}>
                        {label}
                      </span>
                    </td>
                    <td className="muted mono">{r.result}</td>
                    <td>{r.cycle_action ?? "n/a"}</td>
                    <td>{r.error_code ?? "n/a"}</td>
                    <td className="notes-cell">{r.notes_summary ?? "n/a"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
