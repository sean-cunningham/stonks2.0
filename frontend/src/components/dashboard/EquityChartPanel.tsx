import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DashboardPoint } from "../../types/dashboard";

type Props = {
  points: DashboardPoint[];
  isMinimalViable: boolean;
};

export default function EquityChartPanel({ points, isMinimalViable }: Props) {
  const sparse = points.length > 0 && points.length <= 2;

  return (
    <section className="panel">
      <h2>Equity / value over time (MVP)</h2>
      {points.length === 0 ? (
        <div className="empty empty-prose">
          <p>No time-series points yet.</p>
          <p className="muted small-print">
            The chart fills as closed trades (and snapshots of open MTM) accumulate. Early sessions may stay empty until
            the first exits.
          </p>
        </div>
      ) : (
        <>
          {sparse && isMinimalViable && (
            <div className="chart-banner muted">
              Early / sparse series — MVP estimate, not full mark-to-market history.
            </div>
          )}
          <div className="chart-wrap">
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={points}>
                <XAxis dataKey="timestamp" tickFormatter={(v) => new Date(v).toLocaleTimeString()} minTickGap={32} />
                <YAxis />
                <Tooltip
                  labelFormatter={(v) => new Date(v).toLocaleString()}
                  formatter={(v: number) => [`$${v.toFixed(2)}`, "Equity/Value"]}
                />
                <Line type="monotone" dataKey="value" stroke="#60a5fa" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </section>
  );
}
