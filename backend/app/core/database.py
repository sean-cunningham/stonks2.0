from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Base declarative class for SQLAlchemy models."""


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    """Provide database session dependency for FastAPI endpoints."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database_connectivity() -> bool:
    """Run a simple query to verify database connectivity."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def delete_legacy_spy_intraday_bars() -> int:
    """
    Remove SPY 1m/5m rows that are not from the DXLink candle pipeline.

    Prevents Yahoo or REST snapshot bars from affecting context readiness.
    """
    prefix = "tastytrade_dxlink_candle"
    with engine.begin() as connection:
        result = connection.execute(
            text(
                "DELETE FROM intraday_bars WHERE symbol = 'SPY' "
                "AND timeframe IN ('1m', '5m') "
                "AND (source_status IS NULL OR source_status NOT LIKE :pfx)"
            ),
            {"pfx": f"{prefix}%"},
        )
        return int(result.rowcount or 0)


def ensure_market_snapshot_schema() -> None:
    """Backfill additive columns for local SQLite scaffold updates."""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return

    expected_columns: dict[str, str] = {
        "chain_snapshot_time": "DATETIME",
        "underlying_last": "FLOAT",
        "chain_contract_count": "INTEGER",
        "expiration_dates_json": "JSON",
        "nearest_expiration": "VARCHAR(16)",
        "atm_reference_price": "FLOAT",
        "near_atm_contracts_json": "JSON",
    }
    with engine.begin() as connection:
        existing_rows = connection.execute(text("PRAGMA table_info(market_snapshots)")).fetchall()
        existing = {row[1] for row in existing_rows}
        for column, ddl_type in expected_columns.items():
            if column not in existing:
                connection.execute(text(f"ALTER TABLE market_snapshots ADD COLUMN {column} {ddl_type}"))


def ensure_paper_trade_schema() -> None:
    """Additive SQLite columns for paper_trades (existing local DBs)."""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    with engine.begin() as connection:
        table = connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='paper_trades'")
        ).fetchone()
        if not table:
            return
        rows = connection.execute(text("PRAGMA table_info(paper_trades)")).fetchall()
        existing = {row[1] for row in rows}
        expected_columns: dict[str, str] = {
            "entry_decision": "VARCHAR(16) DEFAULT ''",
            "evaluation_snapshot_json": "JSON",
            "entry_reference_basis": "VARCHAR(32) DEFAULT 'option_ask'",
            "exit_reference_basis": "VARCHAR(32)",
            "exit_reason": "TEXT",
        }
        for column, ddl_type in expected_columns.items():
            if column not in existing:
                connection.execute(text(f"ALTER TABLE paper_trades ADD COLUMN {column} {ddl_type}"))
