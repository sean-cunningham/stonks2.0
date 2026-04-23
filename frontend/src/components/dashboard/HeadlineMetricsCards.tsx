import type { DashboardResponse } from "../../types/dashboard";

type Props = {
  metrics: DashboardResponse["headline_metrics"];
};

function fmt(value: number | null, percent = false): string {
  if (value === null || Number.isNaN(value)) return "n/a";
  if (percent) return `${(value * 100).toFixed(1)}%`;
  return `$${value.toFixed(2)}`;
}

export default function HeadlineMetricsCards({ metrics }: Props) {
  const cards = [
    ["Realized P&L", fmt(metrics.realized_pnl)],
    ["Unrealized P&L", fmt(metrics.unrealized_pnl)],
    ["Total P&L", fmt(metrics.total_pnl)],
    ["Trade count", String(metrics.trade_count)],
    ["Win rate", fmt(metrics.win_rate, true)],
    ["Open positions", String(metrics.open_position_count)],
  ] as const;

  return (
    <section className="panel">
      <h2>At a glance</h2>
      <div className="cards-grid">
        {cards.map(([label, value]) => (
          <article key={label} className="metric-card">
            <div className="metric-label">{label}</div>
            <div className="metric-value">{value}</div>
          </article>
        ))}
      </div>
    </section>
  );
}
