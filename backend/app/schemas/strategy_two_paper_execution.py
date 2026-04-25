"""Strategy 2 paper automation execution reports."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.paper_trade import PaperTradeResponse
from app.schemas.strategy import StrategyOneEvaluationResponse
from app.schemas.strategy_one_exit_evaluation import StrategyOneExitEvaluationResponse

ExecuteOnceCycleAction = Literal["no_action", "opened", "closed"]


class StrategyTwoExecuteOnceResponse(BaseModel):
    cycle_action: ExecuteOnceCycleAction
    had_open_position_at_start: bool
    notes: list[str] = Field(default_factory=list)
    evaluation_timestamp: datetime
    entry_evaluation: StrategyOneEvaluationResponse | None = None
    exit_evaluation: StrategyOneExitEvaluationResponse | None = None
    opened_paper_trade: PaperTradeResponse | None = None
    closed_paper_trade: PaperTradeResponse | None = None
