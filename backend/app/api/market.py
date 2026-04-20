from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.schemas.market import (
    ChainLatestResponse,
    MarketStatusResponse,
    NearAtmContract,
    QuoteLatestResponse,
    RefreshResponse,
)
from app.services.market.market_store import MarketStoreService

router = APIRouter(prefix="/market/spy", tags=["market"])


def get_market_service(db: Session = Depends(get_db)) -> MarketStoreService:
    """Provide market store service dependency."""
    return MarketStoreService(db=db, settings=get_settings())


@router.get("/status", response_model=MarketStatusResponse)
def get_spy_market_status(service: MarketStoreService = Depends(get_market_service)) -> MarketStatusResponse:
    """Return computed SPY market readiness status."""
    return service.get_spy_status()


@router.get("/quote/latest", response_model=QuoteLatestResponse)
def get_spy_quote_latest(service: MarketStoreService = Depends(get_market_service)) -> QuoteLatestResponse:
    """Return latest normalized SPY quote."""
    return service.get_latest_quote()


@router.get("/chain/latest", response_model=ChainLatestResponse)
def get_spy_chain_latest(service: MarketStoreService = Depends(get_market_service)) -> ChainLatestResponse:
    """Return latest normalized SPY chain summary."""
    return service.get_latest_chain()


@router.get("/contracts/atm", response_model=list[NearAtmContract])
def get_spy_near_atm_contracts(
    service: MarketStoreService = Depends(get_market_service),
) -> list[NearAtmContract]:
    """Return current near-ATM contract list for quick debugging."""
    chain = service.get_latest_chain()
    return chain.near_atm_contracts


@router.post("/refresh", response_model=RefreshResponse)
def refresh_spy_market(service: MarketStoreService = Depends(get_market_service)) -> RefreshResponse:
    """Trigger manual SPY quote+chain refresh and return resulting status."""
    return service.refresh_spy()

