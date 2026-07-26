"""Database engine and session handling."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import ROOT, config
from .models import Base

url = config.database_url
# Railway hands out postgres:// but SQLAlchemy 2 wants postgresql+psycopg2://
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql+psycopg2://", 1)

if url.startswith("sqlite"):
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False})
else:
    engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create tables. Fine for the beta; swap to Alembic before schema churn."""
    Base.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """Add new nullable columns to existing tables without dropping data.

    create_all() never ALTERs an existing table, so a new model field would be
    invisible on a database created before it. Until Alembic lands, this makes
    additive schema changes safe for the running beta. Additive only — it never
    drops or retypes.
    """
    from sqlalchemy import inspect, text

    # (column type, default SQL clause or "" for nullable-no-default)
    wanted = {
        "profiles": {"work_modes": ("TEXT", "DEFAULT '[]'"),
                     "countries": ("TEXT", "DEFAULT '[]'")},
        "jobs": {"last_checked_at": ("TIMESTAMP", ""),
                 "embedding": ("TEXT", ""),
                 "embedding_model": ("TEXT", "DEFAULT ''")},
        "users": {"premium_requested_at": ("TIMESTAMP", "")},
        "job_results": {"fit_role": ("INTEGER", "DEFAULT 0"),
                        "fit_candidate": ("INTEGER", "DEFAULT 0")},
        "score_cache": {"fit_role": ("INTEGER", "DEFAULT 0"),
                        "fit_candidate": ("INTEGER", "DEFAULT 0")},
    }
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, cols in wanted.items():
            if table not in tables:
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, (sqltype, default) in cols.items():
                if name not in existing:
                    conn.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN {name} {sqltype} {default}".strip()
                    ))


def get_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
