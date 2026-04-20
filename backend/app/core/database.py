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
