"""Regression: a duplicated table key in the additive migrator dict silently
drops the first entry's columns (Python keeps the last key). Found in cycle 13."""
import ast
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "web" / "app" / "db.py"


def test_migrator_dicts_have_no_duplicate_keys():
    tree = ast.parse(DB.read_text())
    dicts = [n for n in ast.walk(tree) if isinstance(n, ast.Dict)]
    checked = 0
    for d in dicts:
        keys = [k.value for k in d.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        if "job_states" in keys:
            checked += 1
        dupes = {k for k in keys if keys.count(k) > 1}
        assert not dupes, f"duplicate dict keys in db.py line {d.lineno}: {sorted(dupes)}"
    assert checked >= 1, "migrator dict not found — test would pass vacuously"


def test_job_states_migrates_all_late_columns():
    src = DB.read_text()
    for col in ("digest_sent_at", "next_step", "next_step_on", "closed_from_stage", "saved_at"):
        assert f'"{col}"' in src


def test_migrator_adds_last_progress_at_to_an_old_searches_table(monkeypatch, tmp_path):
    """R3-28: a DB created before the heartbeat column gets it on boot, and the
    existing rows survive with it NULL (the reapers then fall back to started_at)."""
    from sqlalchemy import create_engine, inspect, text

    from web.app import db as dbmod
    old = create_engine(f"sqlite:///{tmp_path}/old.sqlite")
    with old.begin() as conn:
        conn.execute(text("CREATE TABLE searches (id INTEGER PRIMARY KEY, user_id INTEGER, "
                          "status VARCHAR(16), started_at TIMESTAMP)"))
        conn.execute(text("INSERT INTO searches (id, user_id, status, started_at) "
                          "VALUES (1, 1, 'running', '2026-11-14 10:00:00')"))
    monkeypatch.setattr(dbmod, "engine", old)
    dbmod._add_missing_columns()
    dbmod._add_missing_columns()                      # idempotent on a second boot
    cols = {c["name"] for c in inspect(old).get_columns("searches")}
    assert "last_progress_at" in cols
    with old.connect() as conn:
        row = conn.execute(text("SELECT status, last_progress_at FROM searches")).one()
    assert row == ("running", None)
