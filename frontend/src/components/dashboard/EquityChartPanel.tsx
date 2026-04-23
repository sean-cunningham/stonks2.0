import { useMemo, useState } from "react";
import { Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DashboardPoint } from "../../types/dashboard";
import { formatEasternDateTime, formatEasternTimeOnly } from "../../utils/formatEasternTime";

type Props = {
  equityPoints: DashboardPoint[];
  returnPctPoints: DashboardPoint[];
  isMinimalViable: boolean;
};

type Mode = "usd" | "pct";

type ChartRow = {
  timestamp: string;
  value: number;
};

export default function EquityChartPanel({ equityPoints, returnPctPoints, isMinimalViable }: Props) {
  const [mode, setMode] = useState<Mode>("pct");
  const points = mode === "pct" && returnPctPoints.length > 0 ? returnPctPoints : equityPoints;
  const sparse = points.length > 0 && points.length <= 2;
  const rows: ChartRow[] = useMemo(
    () => points.map((p) => ({ timestamp: p.timestamp, value: Number(p.value) })),
    [points]
  );
  const yLabel = mode === "pct" ? "Return %" : "Equity $";

  return (
    <section className="panel">
      <div className="panel-row-header">
        <h2>Equity performance over time (ET)</h2>
        <div className="segment-toggle" role="group" aria-label="Equity chart mode">
          <button
            type="button"
            className={mode === "pct" ? "seg-btn active" : "seg-btn"}
            onClick={() => setMode("pct")}
          >
            Percent
          </button>
          <button
            type="button"
            className={mode === "usd" ? "seg-btn active" : "seg-btn"}
            onClick={() => setMode("usd")}
          >
            Dollar value
          </button>
        </div>
      </div>
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
              Early / sparse series — MVP estimate, not full mark-to-market history. Times are US Eastern (ET).
            </div>
          )}
          <div className="chart-wrap">
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={rows}>
                <XAxis
                  dataKey="timestamp"
                  tickFormatter={(v) => formatEasternTimeOnly(v as string)}
                  minTickGap={32}
                />
                <YAxis
                  tickFormatter={(v: number) => (mode === "pct" ? `${v.toFixed(2)}%` : `$${v.toFixed(0)}`)}
                  label={{ value: yLabel, angle: -90, position: "insideLeft" }}
                />
                <Tooltip
                  labelFormatter={(v) => formatEasternDateTime(v as string)}
                  formatter={(v: number) =>
                    mode === "pct" ? [`${v.toFixed(3)}%`, "Return vs starting capital"] : [`$${v.toFixed(2)}`, "Equity value"]
                  }
                />
                <ReferenceLine y={0} stroke="#64748b" strokeDasharray="4 4" />
                <Line type="monotone" dataKey="value" stroke="#60a5fa" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </section>
  );
}
