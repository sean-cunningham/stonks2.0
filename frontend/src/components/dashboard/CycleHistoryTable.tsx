import { useMemo, useState } from "react";
import type { DashboardResponse } from "../../types/dashboard";
import {
  humanizeCycleAction,
  humanizeCycleBadgeCategory,
  humanizeCycleDetails,
  humanizeCycleResult,
} from "../../utils/dashboardHumanize";
import { easternDateBucket, formatEasternDateTime, parseApiDate } from "../../utils/formatEasternTime";

type Row = DashboardResponse["recent_cycle_history"][number];

type Props = {
  rows: Row[];
};

type TimeWindow = "15m" | "30m" | "60m" | "today" | "all";
type StatusFilter = "all" | "no_action" | "opened" | "closed" | "blocked" | "error";
type ActionFilter = "all" | "open" | "close" | "none";

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
  const [timeWindow, setTimeWindow] = useState<TimeWindow>("30m");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [actionFilter, setActionFilter] = useState<ActionFilter>("all");

  const filteredRows = useMemo(() => {
    const now = new Date();
    const nowMs = now.getTime();
    const todayKey = easternDateBucket(now);
    return rows.filter((r) => {
      const started = parseApiDate(r.started_at);
      if (Number.isNaN(started.getTime())) return false;
      const startedMs = started.getTime();

      if (timeWindow === "15m" && nowMs - startedMs > 15 * 60 * 1000) return false;
      if (timeWindow === "30m" && nowMs - startedMs > 30 * 60 * 1000) return false;
      if (timeWindow === "60m" && nowMs - startedMs > 60 * 60 * 1000) return false;
      if (timeWindow === "today" && easternDateBucket(started) !== todayKey) return false;

      const category = cycleDisplayCategory(r) as StatusFilter;
      if (statusFilter !== "all" && category !== statusFilter) return false;

      const actionCategory: ActionFilter =
        r.cycle_action === "opened" ? "open" : r.cycle_action === "closed" ? "close" : "none";
      if (actionFilter !== "all" && actionCategory !== actionFilter) return false;

      return true;
    });
  }, [actionFilter, rows, statusFilter, timeWindow]);

  return (
    <section className="panel">
      <h2>Recent cycle history (ET)</h2>
      {rows.length === 0 ? (
        <div className="empty empty-prose">
          <p>No scheduler cycles in the recent window.</p>
          <p className="muted small-print">When the scheduler runs, each cycle appears here with Eastern times.</p>
        </div>
      ) : (
        <>
          <div className="cycle-filters">
            <label>
              Time window
              <select value={timeWindow} onChange={(e) => setTimeWindow(e.target.value as TimeWindow)}>
                <option value="15m">Last 15 min</option>
                <option value="30m">Last 30 min</option>
                <option value="60m">Last 60 min</option>
                <option value="today">Today</option>
                <option value="all">All</option>
              </select>
            </label>
            <label>
              System result
              <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}>
                <option value="all">All</option>
                <option value="no_action">No action</option>
                <option value="opened">Opened</option>
                <option value="closed">Closed</option>
                <option value="blocked">Blocked</option>
                <option value="error">Error</option>
              </select>
            </label>
            <label>
              Action taken
              <select value={actionFilter} onChange={(e) => setActionFilter(e.target.value as ActionFilter)}>
                <option value="all">All</option>
                <option value="open">Open</option>
                <option value="close">Close</option>
                <option value="none">None</option>
              </select>
            </label>
          </div>
          <div className="cycle-filter-summary muted">
            Showing {filteredRows.length} of {rows.length} rows
          </div>
          <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Started (ET)</th>
                <th>Finished (ET)</th>
                <th>What happened</th>
                <th>System result</th>
                <th>Action taken</th>
                <th>Error code</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.map((r, i) => {
                const category = cycleDisplayCategory(r);
                const humanDetails = humanizeCycleDetails(r.notes_summary);
                return (
                  <tr key={`${r.started_at}-${i}`}>
                    <td>{formatEasternDateTime(r.started_at)}</td>
                    <td>{r.finished_at ? formatEasternDateTime(r.finished_at) : "—"}</td>
                    <td>
                      <span className={`status-badge ${badgeClass(category)}`} title={`Machine result: ${r.result}`}>
                        {humanizeCycleBadgeCategory(category)}
                      </span>
                    </td>
                    <td>{humanizeCycleResult(r.result)}</td>
                    <td>{humanizeCycleAction(r.cycle_action)}</td>
                    <td className="mono">{r.error_code ?? "—"}</td>
                    <td className="notes-cell">
                      <div>{humanDetails}</div>
                      <details className="notes-raw">
                        <summary>Technical details</summary>
                        <pre>
                          {JSON.stringify(
                            {
                              result: r.result,
                              cycle_action: r.cycle_action,
                              notes_summary: r.notes_summary,
                            },
                            null,
                            2
                          )}
                        </pre>
                      </details>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        </>
      )}
    </section>
  );
}
