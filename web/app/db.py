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
    _backfill()
    _migrate_profiles()


def _remap(values, mapping: dict, allowed) -> list:
    """Map old slugs forward and drop anything unmapped and unknown (R5.3/R5.4)."""
    allowed = set(allowed)
    out: list = []
    for v in (values or []):
        v2 = mapping.get(v, v)
        if v2 in allowed and v2 not in out:
            out.append(v2)
    return out


def _migrate_profiles() -> None:
    """Move stored profiles onto the new seniority bands and sector/company
    lists. Idempotent: already-migrated values pass through unchanged."""
    import logging

    log = logging.getLogger("jbhntr.db")
    try:
        from .models import Profile
        from .routes.onboarding import (
            COMPANY_MIGRATE, COMPANY_TYPES, SENIORITY, SENIORITY_MIGRATE,
            VERTICAL_MIGRATE, VERTICALS,
        )
        db = SessionLocal()
        try:
            changed = 0
            for p in db.query(Profile):
                sen = _remap(p.seniority, SENIORITY_MIGRATE, SENIORITY)
                ver = _remap(p.verticals, VERTICAL_MIGRATE, VERTICALS)
                ct = _remap(p.company_type, COMPANY_MIGRATE, COMPANY_TYPES)
                if [sen, ver, ct] != [p.seniority or [], p.verticals or [], p.company_type or []]:
                    p.seniority, p.verticals, p.company_type = sen, ver, ct
                    changed += 1
            if changed:
                db.commit()
                log.info("migrated %d profiles to new seniority/sector lists", changed)
        finally:
            db.close()
    except Exception:
        log.exception("profile migration skipped")


def _backfill() -> None:
    """One-off data fixes after additive columns land. Idempotent."""
    import logging

    from sqlalchemy import text
    log = logging.getLogger("jbhntr.db")
    try:
        with engine.begin() as conn:
            # Old thumbs become a rating on the 1-5 scale (R9): up -> 5, down -> 1.
            conn.execute(text(
                "UPDATE feedback SET rating = CASE vote WHEN 'up' THEN 5 "
                "WHEN 'down' THEN 1 END WHERE rating IS NULL AND vote IN ('up','down')"))
    except Exception:
        log.exception("backfill skipped")


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
                     "countries": ("TEXT", "DEFAULT '[]'"),
                     "derived_roles": ("TEXT", "DEFAULT '[]'")},
        "jobs": {"last_checked_at": ("TIMESTAMP", ""),
                 "embedding": ("TEXT", ""),
                 "embedding_model": ("TEXT", "DEFAULT ''"),
                 "geo_checked": ("BOOLEAN", "DEFAULT false"),
                 "ats_checked": ("BOOLEAN", "DEFAULT false")},
        "users": {"premium_requested_at": ("TIMESTAMP", ""),
                  "digest": ("TEXT", "DEFAULT 'daily'"),
                  "last_discovery_at": ("TIMESTAMP", ""),
                  "discovery_seeds": ("TEXT", "DEFAULT '[]'"),
                  "discovery_verticals": ("TEXT", "DEFAULT '[]'")},
        "job_states": {"digest_sent_at": ("TIMESTAMP", "")},
        "searches": {"notify_email": ("BOOLEAN", "DEFAULT false"),
                     "located_count": ("INTEGER", "DEFAULT 0"),
                     "ranked_count": ("INTEGER", "DEFAULT 0")},
        "job_results": {"fit_role": ("INTEGER", "DEFAULT 0"),
                        "fit_candidate": ("INTEGER", "DEFAULT 0"),
                        "dedup_key": ("TEXT", "DEFAULT ''")},
        "score_cache": {"fit_role": ("INTEGER", "DEFAULT 0"),
                        "fit_candidate": ("INTEGER", "DEFAULT 0")},
        "documents": {"note": ("TEXT", "DEFAULT ''")},
        "feedback": {"rating": ("INTEGER", "")},
        "page_views": {"visitor": ("TEXT", "")},
    }
    import logging

    log = logging.getLogger("jbhntr.db")
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    for table, cols in wanted.items():
        if table not in tables:
            continue
        existing = {c["name"] for c in insp.get_columns(table)}
        for name, (sqltype, default) in cols.items():
            if name in existing:
                continue
            # One transaction per column: a single bad ALTER (e.g. a dialect
            # quirk) must never abort the others or crash app startup — a
            # crash here fails the Railway healthcheck with no results page.
            try:
                with engine.begin() as conn:
                    conn.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN {name} {sqltype} {default}".strip()
                    ))
            except Exception:
                log.exception("skipping migration: ADD COLUMN %s.%s", table, name)


def get_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
