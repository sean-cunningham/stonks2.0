import type { DashboardResponse } from "../../types/dashboard";

type Row = DashboardResponse["recent_cycle_history"][number];

type Props = {
  rows: Row[];
};

function badgeClass(row: Row): string {
  if (row.result === "opened") return "status-opened";
  if (row.result === "closed") return "status-closed";
  if (row.result === "error") return "status-error";
  if ((row.notes_summary ?? "").includes("auto_open_failed:")) return "status-blocked";
  if (row.result === "no_action") return "status-noaction";
  return "status-default";
}

export default function CycleHistoryTable({ rows }: Props) {
  return (
    <section className="panel">
      <h2>Recent Cycle History</h2>
      {rows.length === 0 ? (
        <div className="empty">No cycle history yet.</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Started</th>
                <th>Result</th>
                <th>Cycle Action</th>
                <th>Error</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={`${r.started_at}-${r.result}`}>
                  <td>{new Date(r.started_at).toLocaleString()}</td>
                  <td>
                    <span className={`status-badge ${badgeClass(r)}`}>{r.result}</span>
                  </td>
                  <td>{r.cycle_action ?? "n/a"}</td>
                  <td>{r.error_code ?? "n/a"}</td>
                  <td>{r.notes_summary ?? "n/a"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
