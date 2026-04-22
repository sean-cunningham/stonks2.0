"""Read-only Strategy 1 exit decision support (paper; no execution)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ExitActionLiteral = Literal[
    "hold",
    "close_now",
    "tighten_stop",
    "trail_active",
    "promote_to_swing_candidate",
]


class StrategyOneExitEvaluationResponse(BaseModel):
    """Single open-position exit recommendation (evaluation only).

    Semantics: ``action == "hold"`` with ``blockers`` set means **non-actionable**
    (cannot evaluate honestly or position not eligible)—not a green-light “keep holding”
    trade-management signal. A true discretionary hold is ``hold`` with empty ``blockers``
    and reason ``no_exit_rules_triggered``.
    """

    action: ExitActionLiteral
    reasons: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    current_policy_snapshot: dict[str, Any] = Field(default_factory=dict)
    current_position_snapshot: dict[str, Any] = Field(default_factory=dict)
    current_market_snapshot: dict[str, Any] = Field(default_factory=dict)
    exit_levels_snapshot: dict[str, Any] = Field(default_factory=dict)
    evaluation_timestamp: datetime
