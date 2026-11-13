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
