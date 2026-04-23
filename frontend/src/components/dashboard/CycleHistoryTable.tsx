import type { DashboardResponse } from "../../types/dashboard";
import { humanizeAutoOpenNotes, humanizeCycleBadgeCategory } from "../../utils/dashboardHumanize";
import { formatEasternDateTime } from "../../utils/formatEasternTime";

type Row = DashboardResponse["recent_cycle_history"][number];

type Props = {
  rows: Row[];
};

function isAutoOpenFailed(notes: string | null | undefined): boolean {
  return Boolean(notes?.includes("auto_open_failed:"));
}

function cycleDisplayCategory(row: Row): string {
  if (row.result === "opened") return "opened";
  if (row.result === "closed") return "closed";
  if (row.result === "error") return "error";
  if (row.result === "no_action" && isAutoOpenFailed(row.notes_summary)) return "blocked";
  if (row.result === "no_action") return "no_action";
  return row.result;
}

function badgeClass(category: string): string {
  if (category === "opened") return "status-opened";
  if (category === "closed") return "status-closed";
  if (category === "error") return "status-error";
  if (category === "blocked") return "status-blocked";
  if (category === "no_action") return "status-noaction";
  return "status-default";
}

export default function CycleHistoryTable({ rows }: Props) {
  return (
    <section className="panel">
      <h2>Recent cycle history (ET)</h2>
      {rows.length === 0 ? (
        <div className="empty empty-prose">
          <p>No scheduler cycles in the recent window.</p>
          <p className="muted small-print">When the scheduler runs, each cycle appears here with Eastern times.</p>
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Started (ET)</th>
                <th>Finished (ET)</th>
                <th>What happened</th>
                <th>Machine result</th>
                <th>Cycle action</th>
                <th>Error code</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const category = cycleDisplayCategory(r);
                const humanNotes = humanizeAutoOpenNotes(r.notes_summary);
                return (
                  <tr key={`${r.started_at}-${i}`}>
                    <td>{formatEasternDateTime(r.started_at)}</td>
                    <td>{r.finished_at ? formatEasternDateTime(r.finished_at) : "—"}</td>
                    <td>
                      <span className={`status-badge ${badgeClass(category)}`} title={`Machine result: ${r.result}`}>
                        {humanizeCycleBadgeCategory(category)}
                      </span>
                    </td>
                    <td className="muted mono">{r.result}</td>
                    <td className="mono">{r.cycle_action ?? "—"}</td>
                    <td className="mono">{r.error_code ?? "—"}</td>
                    <td className="notes-cell">
                      {humanNotes ? (
                        <>
                          <div>{humanNotes}</div>
                          <details className="notes-raw">
                            <summary>Raw notes</summary>
                            <pre>{r.notes_summary ?? "—"}</pre>
                          </details>
                        </>
                      ) : (
                        r.notes_summary ?? "—"
                      )}
                    </td>
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
