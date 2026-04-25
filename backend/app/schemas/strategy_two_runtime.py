"""Strategy 2 paper runtime control/status schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class StrategyTwoRuntimeStatusResponse(BaseModel):
    strategy_id: str
    mode: str
    scheduler_enabled: bool
    paused: bool
    entry_enabled: bool
    exit_enabled: bool
    running: bool
    lock_scope: str
    last_cycle_started_at: datetime | None = None
    last_cycle_finished_at: datetime | None = None
    last_cycle_result: str | None = None
    last_error: str | None = None
    market_window_open: bool = False
    runtime_sleep_reason: str | None = None
