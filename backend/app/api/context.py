"""SPY intraday context endpoints (Strategy 1-lite prep; no strategy decisions)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.schemas.bars import BarListResponse
from app.schemas.context import ContextRefreshResponse, ContextStatusResponse, ContextSummaryResponse
from app.services.market.context_service import ContextService

router = APIRouter(prefix="/context/spy", tags=["context"])


def get_context_service(db: Session = Depends(get_db)) -> ContextService:
    return ContextService(db=db, settings=get_settings())


@router.get("/status", response_model=ContextStatusResponse)
def get_context_status(service: ContextService = Depends(get_context_service)) -> ContextStatusResponse:
    return service.get_status()


@router.get("/bars/1m", response_model=BarListResponse)
def get_bars_1m(service: ContextService = Depends(get_context_service)) -> BarListResponse:
    return service.get_bars_1m()


@router.get("/bars/5m", response_model=BarListResponse)
def get_bars_5m(service: ContextService = Depends(get_context_service)) -> BarListResponse:
    return service.get_bars_5m()


@router.get("/summary", response_model=ContextSummaryResponse)
def get_context_summary(service: ContextService = Depends(get_context_service)) -> ContextSummaryResponse:
    return service.get_summary()


@router.post("/refresh", response_model=ContextRefreshResponse)
def refresh_context(service: ContextService = Depends(get_context_service)) -> ContextRefreshResponse:
    return service.refresh()
