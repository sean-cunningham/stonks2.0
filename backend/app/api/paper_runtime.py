"""Shared paper runtime controls across strategies."""

from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.services.paper.strategy_one_runtime_service import get_strategy_one_runtime_coordinator
from app.services.paper.strategy_three_runtime_service import get_strategy_three_runtime_coordinator
from app.services.paper.strategy_two_runtime_service import get_strategy_two_runtime_coordinator

router = APIRouter(prefix="/paper/runtime", tags=["paper"])


class StrategyRuntimeToggleResult(BaseModel):
    strategy_id: str
    paused: bool
    entry_enabled: bool
    exit_enabled: bool
    scheduler_enabled: bool


class PauseAllResponse(BaseModel):
    action: str
    strategies: list[StrategyRuntimeToggleResult] = Field(default_factory=list)


def _require_paper_app_mode(settings: Settings) -> None:
    if settings.APP_MODE != "paper":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="paper_runtime_controls_require_app_mode_paper",
        )


def _collect_statuses(db: Session, settings: Settings) -> list[StrategyRuntimeToggleResult]:
    s1 = get_strategy_one_runtime_coordinator().get_status(db, settings=settings)
    s2 = get_strategy_two_runtime_coordinator().get_status(db, settings=settings)
    s3 = get_strategy_three_runtime_coordinator().get_status(db, settings=settings)
    return [
        StrategyRuntimeToggleResult(
            strategy_id=s1.strategy_id,
            paused=s1.paused,
            entry_enabled=s1.entry_enabled,
            exit_enabled=s1.exit_enabled,
            scheduler_enabled=s1.scheduler_enabled,
        ),
        StrategyRuntimeToggleResult(
            strategy_id=s2.strategy_id,
            paused=s2.paused,
            entry_enabled=s2.entry_enabled,
            exit_enabled=s2.exit_enabled,
            scheduler_enabled=s2.scheduler_enabled,
        ),
        StrategyRuntimeToggleResult(
            strategy_id=s3.strategy_id,
            paused=s3.paused,
            entry_enabled=s3.entry_enabled,
            exit_enabled=s3.exit_enabled,
            scheduler_enabled=s3.scheduler_enabled,
        ),
    ]


@router.post("/pause-all", response_model=PauseAllResponse)
def pause_all_runtimes(db: Session = Depends(get_db)) -> PauseAllResponse:
    settings = get_settings()
    _require_paper_app_mode(settings)
    get_strategy_one_runtime_coordinator().set_paused(db, settings=settings, paused=True)
    get_strategy_two_runtime_coordinator().set_paused(db, settings=settings, paused=True)
    get_strategy_three_runtime_coordinator().set_paused(db, settings=settings, paused=True)
    return PauseAllResponse(action="pause_all", strategies=_collect_statuses(db, settings))


@router.post("/resume-all", response_model=PauseAllResponse)
def resume_all_runtimes(db: Session = Depends(get_db)) -> PauseAllResponse:
    settings = get_settings()
    _require_paper_app_mode(settings)
    get_strategy_one_runtime_coordinator().set_paused(db, settings=settings, paused=False)
    get_strategy_two_runtime_coordinator().set_paused(db, settings=settings, paused=False)
    get_strategy_three_runtime_coordinator().set_paused(db, settings=settings, paused=False)
    return PauseAllResponse(action="resume_all", strategies=_collect_statuses(db, settings))

