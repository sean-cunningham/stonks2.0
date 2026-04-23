import { Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DashboardPoint } from "../../types/dashboard";
import { formatEasternDateTime, formatEasternTimeOnly } from "../../utils/formatEasternTime";

type Props = {
  points: DashboardPoint[];
};

export default function CashChartPanel({ points }: Props) {
  return (
    <section className="panel">
      <h2>Cash over time (ET)</h2>
      {points.length === 0 ? (
        <div className="empty">No cash timeline points yet.</div>
      ) : (
        <div className="chart-wrap">
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={points}>
              <XAxis dataKey="timestamp" tickFormatter={(v) => formatEasternTimeOnly(v as string)} minTickGap={28} />
              <YAxis tickFormatter={(v: number) => `$${v.toFixed(0)}`} />
              <Tooltip
                labelFormatter={(v) => formatEasternDateTime(v as string)}
                formatter={(v: number) => [`$${v.toFixed(2)}`, "Cash"]}
              />
              <ReferenceLine y={0} stroke="#64748b" strokeDasharray="4 4" />
              <Line type="monotone" dataKey="value" stroke="#34d399" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
