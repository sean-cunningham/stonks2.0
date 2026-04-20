from typing import Literal

from pydantic import BaseModel


class ConfigResponse(BaseModel):
    """Safe system configuration view."""

    app_name: str
    app_env: str
    app_mode: Literal["paper", "mock"]
    api_host: str
    api_port: int
    database_url: str
    log_level: str
    database_connected: bool


class StrategyMeta(BaseModel):
    """Strategy metadata exposed by system endpoint."""

    id: str
    name: str
    paper_only: bool
    live_order_routing: bool
    ai_enabled: bool
    options_scope: str
    universe: list[str]
    status: str


class SystemStatusResponse(BaseModel):
    """High-level backend runtime status response."""

    app_name: str
    environment: str
    mode: Literal["paper", "mock"]
    database_connected: bool
    current_utc_time: str
    supported_strategies: list[str]
    note: str


class StrategiesResponse(BaseModel):
    """Known strategy catalog response."""

    strategies: list[StrategyMeta]
