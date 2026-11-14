"""Demo engine (repo-split step 2) + production boot guard (step 3, plan §5.3).

The engine backend is resolved once per process, so every scenario that needs a
different selection runs in a fresh interpreter (subprocess) with its own env.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _run(code: str, **env_overrides: str) -> subprocess.CompletedProcess:
    tmp = tempfile.mkdtemp()
    env = {k: v for k, v in os.environ.items()
           if k not in ("JBHNTR_ENGINE", "DATABASE_URL", "DEBUG")}
    env.update({
        "DATABASE_URL": f"sqlite:///{tmp}/demo.sqlite",
        "SECRET_KEY": "s" * 48,
        "BASE_URL": "https://jbhntr.test",
        "PYTHONPATH": str(ROOT),
    })
    if "FILE_ENCRYPTION_KEY" not in env:
        from cryptography.fernet import Fernet
        env["FILE_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    env.update(env_overrides)
    return subprocess.run([sys.executable, "-c", textwrap.dedent(code)], cwd=ROOT,
                          env=env, capture_output=True, text=True, timeout=180)


# --------------------------------------------------------------------------- #
# Demo engine — unit level (in-process: the demo module is plain code).
def test_demo_engine_is_deterministic_and_offline():
    import jbhntr_engine_demo as demo
    from jbhntr_engine import Materials, Profile

    prof = Profile(raw={"objective": "Run operations at a scale-up",
                        "locations": ["United Kingdom", "Remote"],
                        "sources": {"search_terms": ["chief of staff"]}})
    jobs = [j for j in demo.collect_all_sources(prof, None) if demo.prefilter(j, prof)]
    assert jobs and all(j.url.startswith("https://example.com/") for j in jobs)
    first = demo.Matcher(None).score(jobs, prof, Materials())
    again = demo.Matcher(None).score(jobs, prof, Materials())
    assert [(j.title, m.score, m.tier) for j, m in first] == \
           [(j.title, m.score, m.tier) for j, m in again]
    best = max(first, key=lambda p: p[1].score)
    assert best[0].title == "Chief of Staff" and best[1].tier == 1
    # No LLM, no private helpers: the fail-soft paths take over.
    assert demo.llm.is_configured(None) is False
    assert demo.llm.get_client(None).json(
        system="", user="", schema={"type": "object", "properties": {
            "results": {"type": "array"}, "ok": {"type": "boolean"}}}) == \
        {"results": [], "ok": False}
    assert demo.recover_apply_url("Acme", "CoS") is None
    assert demo.panel_deliberate("cv", Materials(), jobs[0], None, None) is None
    assert demo.resolve_countries(["Milan", "Remote"], None) == ["it", ""]


def test_demo_engine_accepts_and_honours_the_progress_callback():
    """R3-29: the demo engine takes the façade's `progress` callback too (the shell
    passes it unconditionally) and reports (done, total) like the real engine."""
    import jbhntr_engine_demo as demo
    from jbhntr_engine import Materials, Profile

    prof = Profile(raw={"sources": {"search_terms": ["chief of staff"]}})
    fetched, scored = [], []
    jobs = demo.collect_all_sources(prof, None, progress=lambda d, t: fetched.append((d, t)))
    out = demo.Matcher(None).score(jobs, prof, Materials(),
                                   progress=lambda d, t: scored.append((d, t)))
    assert len(out) == len(jobs)
    assert fetched and fetched[-1][0] == fetched[-1][1]
    assert scored[-1] == (len(jobs), len(jobs))
    # A failing observer never breaks the demo stage either.
    def boom(d, t):
        raise RuntimeError("x")
    assert demo.collect_all_sources(prof, None, progress=boom)
    assert len(demo.Matcher(None).score(jobs, prof, Materials(), progress=boom)) == len(jobs)


def test_demo_engine_honours_should_stop():
    """R3-30: the demo engine takes `should_stop` too and stops early when asked;
    a failing `should_stop` never stops it."""
    import jbhntr_engine_demo as demo
    from jbhntr_engine import Materials, Profile

    prof = Profile(raw={"sources": {"search_terms": ["chief of staff"]}})
    jobs = demo.collect_all_sources(prof, None)
    assert len(jobs) > 1
    assert demo.collect_all_sources(prof, None, should_stop=lambda: True) == []
    out = demo.Matcher(None).score(jobs, prof, Materials(), should_stop=lambda: True)
    assert len(out) == 1                      # stops after the job in hand
    def boom():
        raise RuntimeError("x")
    assert len(demo.Matcher(None).score(jobs, prof, Materials(), should_stop=boom)) == len(jobs)
    assert demo.collect_all_sources(prof, None, should_stop=boom) == jobs


def test_demo_generator_returns_real_shapes():
    import jbhntr_engine_demo as demo
    from jbhntr_engine import JobPosting, Materials, MatchResult, RankedJob

    job = JobPosting(source="demo", title="Chief of Staff", company="Northwind Labs")
    gen = demo.Generator(None, drive=None)
    assert set(gen.cover_letter(None, Materials(), job)) == {"cover_letter", "tone_note"}
    assert set(gen.refine("cl", "x", "y", None, Materials(), job)) == {"content", "change_note"}
    ranked = [RankedJob(job=job, match=MatchResult(tier=1, score=90, reasons="r"))]
    gen.tailor_top(ranked, None, Materials(base_cv="My CV"), limit=1)
    assert ranked[0].documents["cv"] == "My CV"


# --------------------------------------------------------------------------- #
# Demo engine — end to end through the real shell (fresh process, demo selected).
E2E = """
    from fastapi.testclient import TestClient

    import jbhntr_engine
    assert jbhntr_engine.ENGINE_KIND == "demo", jbhntr_engine.ENGINE_KIND
    import jobhunter  # noqa: F401  (present in-repo, but the demo must not need it)

    from web.app.db import SessionLocal
    from web.app.main import app
    from web.app.models import JobResult, Profile, Search, User
    from web.app.services import reaper, search_service

    reaper.check_url = lambda url, client: "active"      # no network in tests

    with TestClient(app) as c:
        r = c.post("/signup", data={"email": "demo@example.com",
                                     "password": "Sup3rSecret!x", "accept_tos": "1"},
                   follow_redirects=False)
        assert r.status_code in (302, 303), r.status_code
        db = SessionLocal()
        u = db.query(User).filter_by(email="demo@example.com").one()
        if u.profile is None:
            db.add(Profile(user_id=u.id))
            db.commit(); db.refresh(u)
        u.profile.objective = "Chief of staff / operations leadership at a scale-up"
        u.profile.locations = ["United Kingdom", "Remote-Anywhere"]
        u.profile.search_terms = ["chief of staff", "head of operations"]
        s = Search(user_id=u.id, status="queued", stage="")
        db.add(s); db.commit()
        sid, uid = s.id, u.id
        db.close()

        search_service._run_search(sid, uid, "first")      # synchronous worker

        db = SessionLocal()
        s = db.get(Search, sid)
        assert s.status == "done", (s.status, s.error)
        rows = db.query(JobResult).filter_by(search_id=sid).order_by(JobResult.position).all()
        assert rows, "demo scan stored no results"
        assert all(r.apply_url.startswith("https://example.com/demo-jobs/") for r in rows)
        assert rows[0].title == "Chief of Staff"
        db.close()

        page = c.get("/matches")
        assert page.status_code == 200
        assert "Northwind Labs" in page.text
    print("E2E-OK", len(rows))
"""


def test_public_shell_runs_end_to_end_on_the_demo_engine():
    r = _run(E2E, JBHNTR_ENGINE="demo", DEBUG="true")
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-6000:]
    assert "E2E-OK" in r.stdout


# --------------------------------------------------------------------------- #
# Boot guard.
BOOT = """
    from fastapi.testclient import TestClient
    from web.app.main import app
    try:
        with TestClient(app) as c:
            print("BOOTED", c.get("/health").status_code)
    except RuntimeError as exc:
        print("REFUSED", exc)
"""


def test_production_refuses_to_boot_on_explicit_demo_engine():
    r = _run(BOOT, JBHNTR_ENGINE="demo", DEBUG="false")
    assert "REFUSED" in r.stdout and "'demo'" in r.stdout, r.stdout + r.stderr[-3000:]
    assert "BOOTED" not in r.stdout


def test_production_refuses_silent_demo_fallback_when_real_engine_missing():
    # Simulate the private engine failing to install: block its import, leave
    # JBHNTR_ENGINE unset (auto). Auto falls back to demo, and prod refuses.
    code = textwrap.dedent("""
        import sys
        sys.modules["jbhntr_engine_real"] = None   # import -> ImportError
    """) + textwrap.dedent(BOOT)
    r = _run(code, DEBUG="false")
    assert "REFUSED" in r.stdout and "silent fallback" in r.stdout, \
        r.stdout + r.stderr[-3000:]
    assert "BOOTED" not in r.stdout


def test_production_boots_on_the_real_engine_with_no_new_env():
    r = _run(BOOT, DEBUG="false")
    assert "BOOTED 200" in r.stdout, r.stdout + r.stderr[-3000:]


def test_dev_may_run_the_demo_engine_explicitly():
    r = _run(BOOT, JBHNTR_ENGINE="demo", DEBUG="true")
    assert "BOOTED 200" in r.stdout, r.stdout + r.stderr[-3000:]


def test_explicit_real_engine_that_cannot_import_fails_loudly():
    code = """
        import sys
        sys.modules["jbhntr_engine_real"] = None
        import jbhntr_engine
        try:
            jbhntr_engine.Matcher
        except ImportError:
            print("LOUD")
        print(jbhntr_engine.engine_problems())
    """
    r = _run(code, JBHNTR_ENGINE="real", DEBUG="true")
    assert "LOUD" in r.stdout and "failed to load" in r.stdout, r.stdout + r.stderr[-3000:]


def test_cron_entrypoint_refuses_demo_engine_in_production():
    code = """
        from web.app.services import cron
        cron.nightly = lambda: "ran"
        try:
            cron.main()
        except RuntimeError as exc:
            print("REFUSED", exc)
    """
    r = _run(code, JBHNTR_ENGINE="demo", DEBUG="false")
    assert "REFUSED" in r.stdout and "ran" not in r.stdout, r.stdout + r.stderr[-3000:]


@pytest.mark.parametrize("mode", ["demo", "real"])
def test_engine_kind_comes_from_the_loaded_backend_not_env(mode):
    r = _run("import jbhntr_engine; print('KIND', jbhntr_engine.ENGINE_KIND)",
             JBHNTR_ENGINE=mode)
    assert f"KIND {mode}" in r.stdout, r.stdout + r.stderr[-2000:]


def test_demo_triage_takes_progress_and_should_stop():
    """R3-31: `Matcher.triage` joins the long stages on the contract; the demo
    engine accepts the same hooks, reports once, and stops when asked."""
    import jbhntr_engine_demo as demo
    from jbhntr_engine import Profile

    prof = Profile(raw={"sources": {"search_terms": ["chief of staff"]}})
    jobs = demo.collect_all_sources(prof, None) * 30
    seen = []
    out = demo.Matcher(None).triage(jobs, prof, progress=lambda d, t: seen.append((d, t)))
    assert len(out) == 40 and seen == [(len(jobs), len(jobs))]
    assert demo.Matcher(None).triage(jobs, prof, should_stop=lambda: True) == []
    def boom(*a):
        raise RuntimeError("x")
    assert len(demo.Matcher(None).triage(jobs, prof, progress=boom, should_stop=boom)) == 40
