"""R3-06 BI dashboard — web/app/services/metrics.py.

Every metric is computed on a private, empty in-memory SQLite DB per test, so
"empty DB" really is empty and nothing leaks into (or from) the shared suite DB.
The rule under test throughout: a metric that cannot be computed is None with a
reason (rendered "—"), never a guessed number.
"""

import os
import tempfile
from datetime import timedelta

os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/test_metrics.sqlite")
os.environ.setdefault("SECRET_KEY", "x" * 48)
if not os.environ.get("FILE_ENCRYPTION_KEY"):
    from cryptography.fernet import Fernet
    os.environ["FILE_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ.setdefault("DEBUG", "true")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from web.app.models import (  # noqa: E402
    Base, JobState, Material, ProductEvent, Profile, ReferralReward, Search,
    SeedCompany, User, utcnow,
)
from web.app.services import metrics  # noqa: E402
from web.app.services.profile_service import completeness  # noqa: E402

LONG = "x" * 40   # clears MIN_TEXT
REQ = ["cv", "about_me", "objective", "seniority", "company_type",
       "verticals", "locations", "job_type"]
OPT = ["cover_letter", "linkedin", "seeds", "search_terms", "salary_floor"]


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


@pytest.fixture
def no_ledger(tmp_path):
    return tmp_path / "missing.csv"


_n = [0]


def _user(db, *, fill=(), scanned=False, referred_by=None, created=None):
    _n[0] += 1
    u = User(email=f"m{_n[0]}@example.com", referred_by_user_id=referred_by)
    if created:
        u.created_at = created
    db.add(u)
    db.flush()
    p = Profile(user_id=u.id)
    db.add(p)
    for key in fill:
        if key in ("cv", "cover_letter", "linkedin"):
            db.add(Material(user_id=u.id, kind=key, filename="f", mime="text/plain",
                            size_bytes=1, ciphertext=b"x"))
        elif key in ("about_me", "objective"):
            setattr(p, key, LONG)
        elif key == "seeds":
            db.add(SeedCompany(user_id=u.id, value="Acme"))
        elif key == "salary_floor":
            p.salary_floor_eur = 60000
        elif key in ("search_terms", "locations"):
            setattr(p, key, ["x"])
        else:
            setattr(p, key, ["x"])
    if scanned:
        db.add(Search(user_id=u.id, status="done", stage="Done"))
    db.commit()
    return u


def _ev(db, name, uid, when=None, **props):
    e = ProductEvent(name=name, user_id=uid, properties=props)
    if when:
        e.created_at = when
    db.add(e)
    db.commit()


def _m(db, ledger, key, **kw):
    return metrics.compute(db, ledger_path=ledger, **kw)["metrics"][key]


# ------------------------------------------------------------------ empty DB --
def test_empty_db_counts_are_zero_and_ratios_are_dash(db, no_ledger):
    out = metrics.compute(db, ledger_path=no_ledger)["metrics"]
    assert out["signups"]["value"] == 0
    assert out["activated"]["value"] == 0
    for key in ("activation_rate", "k_factor", "outcome_events_per_active_user_week",
                "gate_better", "gate_much_better"):
        assert out[key]["value"] is None, key
        assert out[key]["display"] == "—"
        assert out[key]["reason"], key
    assert [s["count"] for s in out["funnel"]["steps"]] == [0, 0, 0, 0]
    assert out["referral_rewards"]["by_status"] == {
        "pending": {"count": 0, "credits": 0}, "held": {"count": 0, "credits": 0},
        "paid": {"count": 0, "credits": 0}}
    arms = out["first_scan_rate_by_variant"]["arms"]
    assert arms["meter"]["rate"] is None and arms["control"]["rate"] is None


def test_every_metric_documents_its_formula(db, no_ledger):
    for key, m in metrics.compute(db, ledger_path=no_ledger)["metrics"].items():
        assert m.get("formula"), key
        assert m.get("label"), key
        if m["value"] is None:
            assert m["display"] == "—" and m["reason"], key


# --------------------------------------------------- activation definition --
def test_activation_reuses_completeness_logic_exactly(db, no_ledger):
    """The bulk computation must agree with profile_service.completeness() for
    every shape of profile — it reuses it, never re-implements the rule."""
    shapes = [(), REQ, REQ[:-1], REQ[:-1] + OPT, OPT, REQ + OPT, ["cv"]]
    users = [_user(db, fill=s) for s in shapes]
    states = metrics.profile_states(db)
    for u in users:
        assert states[u.id].can_search == completeness(db, u).can_search
        assert states[u.id].score == completeness(db, u).score


def test_boundary_70_percent_with_scan_is_activated(db, no_ledger):
    u = _user(db, fill=REQ, scanned=True)            # all required, no optional
    assert completeness(db, u).score == 70
    assert _m(db, no_ledger, "activated")["value"] == 1


def test_boundary_below_70_percent_with_scan_is_not_activated(db, no_ledger):
    u = _user(db, fill=REQ[:-1], scanned=True)       # one required missing
    assert completeness(db, u).score < 70
    assert _m(db, no_ledger, "activated")["value"] == 0


def test_high_score_but_required_field_missing_is_not_activated(db, no_ledger):
    """~91% (all optional, one required missing) is still locked: the bar is
    can_search, not a raw score >= 70 (the CPO's R3-04 catch)."""
    u = _user(db, fill=REQ[:-1] + OPT, scanned=True)
    assert completeness(db, u).score >= 70 and not completeness(db, u).can_search
    assert _m(db, no_ledger, "activated")["value"] == 0


def test_complete_profile_without_scan_is_not_activated(db, no_ledger):
    _user(db, fill=REQ, scanned=False)
    assert _m(db, no_ledger, "activated")["value"] == 0


def test_imported_job_is_not_a_scan(db, no_ledger):
    u = _user(db, fill=REQ)
    db.add(Search(user_id=u.id, status="done", stage="Imported job"))
    db.commit()
    assert _m(db, no_ledger, "activated")["value"] == 0


def test_free_first_scan_flag_counts_as_scan(db, no_ledger):
    u = _user(db, fill=REQ)
    u.first_scan_used_at = utcnow()
    db.commit()
    assert _m(db, no_ledger, "activated")["value"] == 1


def test_activation_rate(db, no_ledger):
    _user(db, fill=REQ, scanned=True)
    _user(db, fill=REQ)
    _user(db)
    _user(db)
    m = _m(db, no_ledger, "activation_rate")
    assert m["value"] == 0.25 and m["display"] == "25.0%"


def test_signups_total_and_last_7_days(db, no_ledger):
    _user(db, created=utcnow() - timedelta(days=30))
    _user(db)
    m = _m(db, no_ledger, "signups")
    assert m["value"] == 2 and m["last_7d"] == 1


# ------------------------------------------------------------------ funnel --
def test_funnel_is_nested_and_counts_triage_or_share(db, no_ledger):
    _user(db)                                         # signup only
    _user(db, fill=REQ)                               # profile ready
    _user(db, fill=REQ, scanned=True)                 # scanned, no triage
    t = _user(db, fill=REQ, scanned=True)             # triaged via event
    _ev(db, "job_saved", t.id)
    s = _user(db, fill=REQ, scanned=True)             # shared
    _ev(db, "market_read_shared", s.id)
    j = _user(db, fill=REQ, scanned=True)             # triaged via JobState only
    db.add(JobState(user_id=j.id, dedup_key="k", dismissed=True))
    db.commit()
    stray = _user(db)                                 # event without a scan: not nested in
    _ev(db, "match_rated", stray.id)
    steps = _m(db, no_ledger, "funnel")["steps"]
    assert [s["count"] for s in steps] == [7, 5, 4, 3]
    assert steps[1]["pct_of_prev"] == round(5 / 7, 3)
    assert steps[0]["pct_of_prev"] is None


# ---------------------------------------------------------------- K-factor --
def test_k_factor_and_per_inviter(db, no_ledger):
    a = _user(db, fill=REQ, scanned=True)             # activated inviter
    _user(db, fill=REQ, scanned=True)                 # activated, invited nobody
    _user(db, fill=REQ, scanned=True, referred_by=a.id)   # referred + activated
    _user(db, referred_by=a.id)                       # referred, not activated
    k = _m(db, no_ledger, "k_factor")
    # 3 activated users; 1 of them came in on a referral.
    assert k["value"] == round(1 / 3, 3)
    assert k["referred_activated"] == 1 and k["activated"] == 3
    assert k["activated_inviters"] == 1
    assert k["per_activated_inviter"] == 1.0


def test_k_factor_dash_when_nobody_activated(db, no_ledger):
    a = _user(db)
    _user(db, referred_by=a.id)
    k = _m(db, no_ledger, "k_factor")
    assert k["value"] is None and "no activated" in k["reason"].lower()


# ----------------------------------------------- outcome events / user / wk --
def test_outcome_events_per_active_user_last_7_days(db, no_ledger):
    a, b = _user(db), _user(db)
    for n in ("job_saved", "match_rated", "document_generated"):
        _ev(db, n, a.id)
    _ev(db, "scan_started", b.id)                     # active, not an outcome
    _ev(db, "job_saved", b.id, when=utcnow() - timedelta(days=9))  # too old
    m = _m(db, no_ledger, "outcome_events_per_active_user_week")
    assert m["outcome_events"] == 3 and m["active_users"] == 2
    assert m["value"] == 1.5


# ----------------------------------------------------- variant first scan --
def test_first_scan_rate_by_variant_reads_activation_kpi(db, no_ledger):
    a, b, c = _user(db), _user(db), _user(db)
    _ev(db, "signup_completed", a.id, variant="meter")
    _ev(db, "signup_completed", b.id, variant="meter")
    _ev(db, "signup_completed", c.id, variant="control")
    _ev(db, "scan_started", a.id, variant="meter")
    arms = _m(db, no_ledger, "first_scan_rate_by_variant")["arms"]
    assert arms["meter"] == {"signups": 2, "scanned": 1, "rate": 0.5}
    assert arms["control"] == {"signups": 1, "scanned": 0, "rate": 0.0}


# ------------------------------------------------------------- gate prompt --
def _gate(db, answer=None, dismiss_count=0):
    from web.app.models import GateAnswer
    u = _user(db)
    db.add(GateAnswer(user_id=u.id, answer=answer, dismiss_count=dismiss_count,
                      answered_at=utcnow() if answer else None))
    db.commit()
    return u


def test_gate_empty_is_dash_with_reason(db, no_ledger):
    out = metrics.compute(db, ledger_path=no_ledger)["metrics"]
    for key in ("gate_better", "gate_much_better"):
        assert out[key]["value"] is None and out[key]["display"] == "—"
        assert "no gate answers yet" in out[key]["reason"]
    assert out["gate_better"]["n"] == 0


def test_gate_below_minimum_n_is_dash_but_reports_n(db, no_ledger):
    for _ in range(metrics.GATE_MIN_N - 1):
        _gate(db, "much_better")
    m = _m(db, no_ledger, "gate_better")
    assert m["value"] is None and m["n"] == metrics.GATE_MIN_N - 1
    assert f"n={metrics.GATE_MIN_N - 1}" in m["reason"]
    assert str(metrics.GATE_MIN_N) in m["reason"]
    assert _m(db, no_ledger, "gate_much_better")["value"] is None


def test_gate_math_from_real_rows(db, no_ledger):
    # 4 much_better, 3 better, 2 same, 1 worse = 10 answers
    for ans, k in (("much_better", 4), ("better", 3), ("same", 2), ("worse", 1)):
        for _ in range(k):
            _gate(db, ans)
    # Unanswered / dismissed prompts are not answers and never enter n.
    _gate(db, None)
    _gate(db, None, dismiss_count=2)
    out = metrics.compute(db, ledger_path=no_ledger)["metrics"]
    g, mb = out["gate_better"], out["gate_much_better"]
    assert g["n"] == 10 and mb["n"] == 10
    assert g["value"] == 0.7 and g["display"] == "70.0%"
    assert mb["value"] == 0.4 and mb["display"] == "40.0%"
    assert g["by_answer"] == {"much_better": 4, "better": 3, "same": 2, "worse": 1}
    assert g["much_better"] == 0.4
    assert "n=10" in g["label"] and "40.0%" in g["label"]
    assert g["asked"] == 12 and g["dismissed_for_good"] == 1


# -------------------------------------------------------- referral rewards --
def test_referral_rewards_by_status(db, no_ledger):
    inviter = _user(db)
    for status in ("pending", "pending", "held", "paid"):
        f = _user(db, referred_by=inviter.id)
        db.add(ReferralReward(inviter_id=inviter.id, friend_id=f.id, amount=5,
                              status=status))
    db.commit()
    rr = _m(db, no_ledger, "referral_rewards")["by_status"]
    assert rr["pending"] == {"count": 2, "credits": 10}
    assert rr["held"] == {"count": 1, "credits": 5}
    assert rr["paid"] == {"count": 1, "credits": 5}


# ------------------------------------------------------------------ ledger --
def test_ledger_missing_shows_dash_with_reason(db, no_ledger):
    out = metrics.compute(db, ledger_path=no_ledger)["metrics"]
    for key in ("spend_usd", "revenue_usd"):
        assert out[key]["value"] is None and "not readable" in out[key]["reason"]


def test_ledger_sums_actual_committed_and_revenue(db, tmp_path):
    p = tmp_path / "LEDGER.csv"
    p.write_text(
        "date,agent,item,vendor,type,usd,approved_by,notes\n"
        "# a comment line\n"
        "2026-11-01,CFO,domain,x,actual,12.50,Founder (R-1),\n"
        "2026-11-02,CFO,hosting,y,committed,5,Founder (R-2),\n"
        "2026-11-03,CFO,pack,z,revenue,30,,\n"
        "2026-11-04,CFO,llm,w,actual,7.5,Founder (R-3),\n")
    out = metrics.compute(db, ledger_path=p)["metrics"]
    assert out["spend_usd"]["value"] == 20.0
    assert out["spend_usd"]["committed"] == 5.0
    assert out["spend_usd"]["remaining_of_cap"] == 1000 - 20.0 - 5.0
    assert out["revenue_usd"]["value"] == 30.0


def test_ledger_with_header_only_is_a_real_zero(db, tmp_path):
    p = tmp_path / "LEDGER.csv"
    p.write_text("date,agent,item,vendor,type,usd,approved_by,notes\n# none yet\n")
    out = metrics.compute(db, ledger_path=p)["metrics"]
    assert out["spend_usd"]["value"] == 0.0 and out["spend_usd"]["rows"] == 0


def test_ledger_bad_amount_is_dash_not_a_guess(db, tmp_path):
    p = tmp_path / "LEDGER.csv"
    p.write_text("date,agent,item,vendor,type,usd,approved_by,notes\n"
                 "2026-11-01,CFO,x,y,actual,about ten,,\n")
    m = metrics.compute(db, ledger_path=p)["metrics"]["spend_usd"]
    assert m["value"] is None and "usd" in m["reason"].lower()


# --------------------------------------------------------- query efficiency --
def test_query_count_does_not_grow_with_users(db, no_ledger):
    """No N+1: the number of SQL statements is constant in the user count."""
    from sqlalchemy import event

    def count_queries():
        n = [0]

        def _cb(*a, **k):
            n[0] += 1
        event.listen(db.get_bind(), "before_cursor_execute", _cb)
        try:
            metrics.compute(db, ledger_path=no_ledger)
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", _cb)
        return n[0]

    _user(db, fill=REQ, scanned=True)
    small = count_queries()
    for _ in range(15):
        _user(db, fill=REQ + OPT, scanned=True)
    assert count_queries() == small


# --------------------------------------------------------------- no PII --
def test_payload_carries_no_emails_or_user_ids(db, no_ledger):
    import json
    u = _user(db, fill=REQ, scanned=True)
    blob = json.dumps(metrics.compute(db, ledger_path=no_ledger), default=str)
    assert "@example.com" not in blob
    assert u.email not in blob


# -------------------------------------------------------- admin endpoints --
def test_metrics_json_is_admin_gated_and_returns_metrics(monkeypatch):
    from fastapi.testclient import TestClient

    from web.app.config import config
    from web.app.main import app
    with TestClient(app) as c:
        monkeypatch.setattr(config, "admin_token", "")
        assert c.get("/admin/metrics.json").status_code == 404
        monkeypatch.setattr(config, "admin_token", "t0k-r306")
        assert c.get("/admin/metrics.json").status_code == 401
        assert c.get("/admin/metrics.json", auth=("a", "wrong")).status_code == 401
        r = c.get("/admin/metrics.json", auth=("a", "t0k-r306"))
        assert r.status_code == 200
        body = r.json()
        assert "activated" in body["metrics"] and "generated_at" in body
        assert r.headers.get("cache-control", "").startswith("no-store")
        page = c.get("/admin", auth=("a", "t0k-r306"))
        assert page.status_code == 200 and "Business metrics" in page.text
