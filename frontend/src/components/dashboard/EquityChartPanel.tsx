import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DashboardPoint } from "../../types/dashboard";

type Props = {
  points: DashboardPoint[];
};

export default function EquityChartPanel({ points }: Props) {
  return (
    <section className="panel">
      <h2>Equity / Value Over Time (MVP)</h2>
      {points.length === 0 ? (
        <div className="empty">No time-series points yet.</div>
      ) : (
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
      )}
    </section>
  );
}
