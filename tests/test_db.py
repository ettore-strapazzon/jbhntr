from web.app.db import _normalize_db_url


def test_normalize_db_url_pins_psycopg2():
    # Both bare Postgres prefixes must land on the installed psycopg2 driver;
    # a bare postgresql:// otherwise crashes at boot on psycopg (v3), taking the
    # Railway healthcheck down.
    assert _normalize_db_url("postgres://u:p@h:5432/db") == "postgresql+psycopg2://u:p@h:5432/db"
    assert _normalize_db_url("postgresql://u:p@h:5432/db") == "postgresql+psycopg2://u:p@h:5432/db"
    # Explicit drivers and sqlite are left untouched.
    assert _normalize_db_url("postgresql+psycopg2://u@h/db") == "postgresql+psycopg2://u@h/db"
    assert _normalize_db_url("postgresql+asyncpg://u@h/db") == "postgresql+asyncpg://u@h/db"
    assert _normalize_db_url("sqlite:///data/app.db") == "sqlite:///data/app.db"
