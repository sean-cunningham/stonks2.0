"""Common dashboard math helpers reusable across paper strategies."""

from __future__ import annotations

from datetime import datetime

from app.models.trade import PaperTrade
from app.schemas.strategy_dashboard import StrategyHeadlineMetrics, StrategyTimeseries, TimeSeriesPoint


def compute_headline_metrics(*, closed: list[PaperTrade], unrealized_pnl: float, open_count: int) -> StrategyHeadlineMetrics:
    realized_values = [float(r.realized_pnl) for r in closed if r.realized_pnl is not None]
    realized = float(sum(realized_values))
    wins = [p for p in realized_values if p > 0]
    losses = [p for p in realized_values if p < 0]
    trade_count = len(realized_values)
    win_rate = (len(wins) / trade_count) if trade_count > 0 else None
    avg_win = (sum(wins) / len(wins)) if wins else None
    avg_loss = (sum(losses) / len(losses)) if losses else None
    expectancy = (realized / trade_count) if trade_count > 0 else None
    total = realized + float(unrealized_pnl)
    return StrategyHeadlineMetrics(
        realized_pnl=realized,
        unrealized_pnl=float(unrealized_pnl),
        total_pnl=total,
        trade_count=trade_count,
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        expectancy=expectancy,
        max_drawdown=None,
        open_position_count=open_count,
    )


def build_mvp_timeseries(
    *,
    closed_chronological: list[PaperTrade],
    current_unrealized_pnl: float,
    starting_cash: float,
    current_cash: float,
    as_of: datetime,
) -> StrategyTimeseries:
    realized_curve: list[TimeSeriesPoint] = []
    equity_curve: list[TimeSeriesPoint] = []
    return_pct_curve: list[TimeSeriesPoint] = []
    cash_curve: list[TimeSeriesPoint] = []
    limitations = [
        "equity_or_value is an MVP estimate from closed-trade realized steps plus current open snapshot; full historical MTM is not persisted",
    ]

    realized = 0.0
    for row in closed_chronological:
        if row.exit_time is None:
            continue
        realized += float(row.realized_pnl or 0.0)
        pt = TimeSeriesPoint(timestamp=row.exit_time, value=realized)
        realized_curve.append(pt)
        equity_curve.append(TimeSeriesPoint(timestamp=row.exit_time, value=float(starting_cash) + realized))
        cash_curve.append(TimeSeriesPoint(timestamp=row.exit_time, value=float(starting_cash) + realized))

    if not equity_curve:
        equity_curve.append(TimeSeriesPoint(timestamp=as_of, value=float(starting_cash) + float(current_unrealized_pnl)))
        cash_curve.append(TimeSeriesPoint(timestamp=as_of, value=float(current_cash)))
        realized_curve.append(TimeSeriesPoint(timestamp=as_of, value=0.0))
    else:
        equity_curve.append(
            TimeSeriesPoint(
                timestamp=as_of,
                value=float(starting_cash) + realized + float(current_unrealized_pnl),
            )
        )
        cash_curve.append(TimeSeriesPoint(timestamp=as_of, value=float(current_cash)))
        realized_curve.append(TimeSeriesPoint(timestamp=as_of, value=realized))

    for p in equity_curve:
        if starting_cash > 0:
            pct = ((p.value - float(starting_cash)) / float(starting_cash)) * 100.0
        else:
            pct = 0.0
        return_pct_curve.append(TimeSeriesPoint(timestamp=p.timestamp, value=pct))

    # Optional drawdown derived from same MVP series.
    peak = None
    drawdown_curve: list[TimeSeriesPoint] = []
    max_dd = 0.0
    for p in equity_curve:
        peak = p.value if peak is None else max(peak, p.value)
        dd = p.value - peak
        max_dd = min(max_dd, dd)
        drawdown_curve.append(TimeSeriesPoint(timestamp=p.timestamp, value=dd))

    ts = StrategyTimeseries(
        equity_or_value=equity_curve,
        equity_return_pct=return_pct_curve,
        cash_over_time=cash_curve,
        realized_pnl_cumulative=realized_curve,
        drawdown=drawdown_curve,
        is_minimal_viable=True,
        limitations=limitations,
    )
    _ = max_dd
    return ts


def compute_max_drawdown_from_curve(curve: list[TimeSeriesPoint]) -> float | None:
    if not curve:
        return None
    peak = None
    max_dd = 0.0
    for p in curve:
        peak = p.value if peak is None else max(peak, p.value)
        max_dd = min(max_dd, p.value - peak)
    return max_dd
