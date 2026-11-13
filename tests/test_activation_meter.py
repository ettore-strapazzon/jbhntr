"""R3-04 activation meter — the first A/B (ARTEFACTS_SPEC §8.4).

The guard that matters most: the CTA's enabled state follows
``Completeness.can_search`` (not missing_required), never ``score >= 70`` and
never the band ``Strength.can_search``. Fixtures below build a profile that
reads ~91% but is still locked, and the reverse.
"""

import os
import tempfile
import uuid

# Same bootstrapping as test_web.py, but setdefault so the full suite's
# test_web.py configuration wins when both run in one session.
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/test_meter.sqlite")
os.environ.setdefault("SECRET_KEY", "x" * 48)
if not os.environ.get("FILE_ENCRYPTION_KEY"):
    from cryptography.fernet import Fernet
    os.environ["FILE_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ.setdefault("DEBUG", "true")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from web.app.main import app  # noqa: E402

LONG = "x" * 40   # clears MIN_TEXT


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True, scope="module")
def _clear_profile_terms_after_module():
    """The suite shares one DB: leave no search_terms/locations behind, or the
    corpus-ranking tests in test_web.py see this module's fixture profiles."""
    yield
    from web.app.db import SessionLocal
    from web.app.models import Profile, User
    db = SessionLocal()
    try:
        ids = [u.id for u in db.query(User).filter(User.email.like("meter+%@example.com"))]
        for p in db.query(Profile).filter(Profile.user_id.in_(ids)):
            p.search_terms = []
            p.locations = []
        db.commit()
    finally:
        db.close()


@pytest.fixture
def arm(monkeypatch):
    """Force the experiment arm via the kill switch: arm('on') / arm('off')."""
    from web.app.config import config

    def _set(mode):
        monkeypatch.setattr(config, "activation_meter", mode, raising=False)
    return _set


def _signup(client):
    email = f"meter+{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/signup", data={"email": email, "password": "Sup3rSecret!x",
                                     "accept_tos": "1"}, follow_redirects=False)
    assert r.status_code in (302, 303)
    from web.app.db import SessionLocal
    from web.app.models import User
    db = SessionLocal()
    try:
        return db.query(User).filter_by(email=email).one().id
    finally:
        db.close()


def _fill(uid, *, required=(), optional=()):
    """Fill the named FIELDS keys for user `uid` directly in the DB."""
    from web.app.db import SessionLocal
    from web.app.models import Material, Profile, SeedCompany, User
    from web.app.security import encrypt_bytes
    db = SessionLocal()
    try:
        u = db.get(User, uid)
        p = u.profile or Profile(user_id=uid)
        db.add(p)
        for key in (*required, *optional):
            if key in ("cv", "cover_letter", "linkedin"):
                db.add(Material(user_id=uid, kind=key, filename=f"{key}.txt",
                                mime="text/plain", size_bytes=10,
                                ciphertext=encrypt_bytes(b"hello"), text="hello"))
            elif key in ("about_me", "objective"):
                setattr(p, key, LONG)
            elif key == "seeds":
                db.add(SeedCompany(user_id=uid, value="Acme"))
            elif key == "salary_floor":
                p.salary_floor_eur = 60000
            elif key == "search_terms":
                p.search_terms = ["Product manager"]
            elif key == "locations":
                p.locations = ["United Kingdom"]
            else:   # seniority, company_type, verticals, job_type
                setattr(p, key, ["something"])
        db.commit()
    finally:
        db.close()


def _state(uid):
    from web.app.db import SessionLocal
    from web.app.models import User
    from web.app.services.profile_service import completeness
    db = SessionLocal()
    try:
        return completeness(db, db.get(User, uid))
    finally:
        db.close()


def _events(name, uid):
    from web.app.db import SessionLocal
    from web.app.models import ProductEvent
    db = SessionLocal()
    try:
        return db.query(ProductEvent).filter_by(name=name, user_id=uid).all()
    finally:
        db.close()


def _meter_button(html):
    """The meter's own <button> tag (not the page's other buttons)."""
    start = html.index('action="/onboarding/first-scan"')
    b = html.index("<button", start)
    return html[b:html.index(">", b) + 1]


REQ = ["cv", "about_me", "objective", "seniority", "company_type",
       "verticals", "locations", "job_type"]
OPT = ["cover_letter", "linkedin", "seeds", "search_terms", "salary_floor"]


# ------------------------------ A/B assignment ----------------------------- #
def test_assignment_is_deterministic_and_roughly_balanced(arm):
    arm("ab")
    from web.app.services.activation import assign_variant
    assert all(assign_variant(i) == assign_variant(i) for i in range(500))
    arms = [assign_variant(i) for i in range(1, 2001)]
    assert set(arms) == {"meter", "control"}
    share = arms.count("meter") / len(arms)
    assert 0.45 < share < 0.55


def test_kill_switch_forces_an_arm(arm):
    from web.app.services.activation import assign_variant
    arm("on")
    assert {assign_variant(i) for i in range(50)} == {"meter"}
    arm("off")
    assert {assign_variant(i) for i in range(50)} == {"control"}


# ------------------- CTA bound to Completeness.can_search ------------------ #
def test_score_above_70_but_one_required_missing_keeps_cta_disabled(client, arm):
    """THE fixture test (§8.4): all 5 optional + 7 of 8 required reads 91% —
    above the 70 line — yet search is locked, so the CTA must stay disabled."""
    arm("on")
    from web.app.services.activation import build_meter
    from web.app.services.profile_service import REQUIRED_WEIGHT
    uid = _signup(client)
    _fill(uid, required=[k for k in REQ if k != "job_type"], optional=OPT)

    state = _state(uid)
    assert state.score >= REQUIRED_WEIGHT and state.score == 91
    assert state.can_search is False and state.missing_required == ["Job type"]
    assert build_meter(state).cta_enabled is False

    html = client.get("/profile").text
    assert "Profile 91%" in html
    assert " disabled" in _meter_button(html)
    # Honest copy: never "unlocks at 70%" while already showing 91%.
    assert "unlocks once the required fields below are in" in html
    assert '<a href="/profile#targets">Job type</a>' in html


def test_cta_enabled_follows_can_search_even_below_70():
    """Vice versa: a gate-open Completeness with a low score still enables the
    CTA (synthetic — the real weighting can't produce it, which is the point:
    the binding is to can_search, not to the number)."""
    from web.app.services.activation import build_meter
    from web.app.services.profile_service import Completeness
    from web.app.templating import templates
    open_low = Completeness(missing_required=[], missing_optional=["x"], score=40)
    locked_high = Completeness(missing_required=["Locations"], missing_optional=[], score=95)
    assert build_meter(open_low).cta_enabled is True
    assert build_meter(locked_high).cta_enabled is False

    tpl = templates.env.get_template("partials/activation_meter.html")
    html_open = tpl.render(meter=build_meter(open_low))
    html_locked = tpl.render(meter=build_meter(locked_high))
    assert " disabled" not in _meter_button(html_open)
    assert " disabled" in _meter_button(html_locked)
    assert "Still needed" not in html_open
    assert "Locations" in html_locked


def test_all_required_no_optional_is_exactly_70_and_enabled(client, arm):
    arm("on")
    uid = _signup(client)
    _fill(uid, required=REQ)
    state = _state(uid)
    assert state.score == 70 and state.can_search
    html = client.get("/profile").text
    assert "Profile 70%" in html and "Ready." in html
    btn = _meter_button(html)
    assert " disabled" not in btn
    assert "Run my free scan" in html


# ------------------------------ what's missing ----------------------------- #
def test_fresh_user_sees_top_missing_with_onboarding_links(client, arm):
    arm("on")
    _signup(client)
    html = client.get("/onboarding/upload").text
    assert "actmeter--onboarding" in html
    assert "Profile 0%" in html and "unlocks at 70%" in html
    assert '<a href="/onboarding/upload">At least one CV</a>' in html
    assert '<a href="/onboarding/words">About you</a>' in html
    assert "and 4 more" in html             # 8 required, top 4 shown
    assert " disabled" in _meter_button(html)


def test_unlock_number_comes_from_the_weight_constant(monkeypatch):
    from web.app.services import activation
    from web.app.services.profile_service import Completeness
    monkeypatch.setattr(activation, "REQUIRED_WEIGHT", 65)
    m = activation.build_meter(Completeness(["Locations"], [], 10))
    assert m.unlock_at == 65


# --------------------------- arms + instrumentation ------------------------ #
def test_control_arm_sees_no_meter(client, arm):
    arm("off")
    _signup(client)
    assert "actmeter" not in client.get("/profile").text
    assert "actmeter" not in client.get("/onboarding/upload").text


def test_signup_event_carries_variant(client, arm):
    arm("on")
    uid = _signup(client)
    su = _events("signup_completed", uid)
    assert su and su[0].properties.get("variant") == "meter"


def test_locked_cta_post_logs_blocked_with_variant(client, arm):
    arm("on")
    uid = _signup(client)
    r = client.post("/onboarding/first-scan", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/profile?error=")
    ev = _events("scan_blocked_incomplete", uid)
    assert ev and ev[-1].properties.get("variant") == "meter"
    assert not _events("scan_started", uid)


def test_live_cta_starts_free_first_scan_and_hides_meter(client, arm, monkeypatch):
    arm("on")
    from web.app.services import search_service
    monkeypatch.setattr(search_service, "_run_search", lambda *a, **k: None)
    uid = _signup(client)
    _fill(uid, required=REQ)
    client.get("/profile")   # gate seen open -> threshold event
    th = _events("profile_threshold_reached", uid)
    assert len(th) == 1 and th[0].properties.get("variant") == "meter"
    client.get("/profile")   # once only
    assert len(_events("profile_threshold_reached", uid)) == 1

    r = client.post("/onboarding/first-scan", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/matches"
    st = _events("scan_started", uid)
    assert len(st) == 1 and st[0].properties.get("variant") == "meter"

    from web.app.db import SessionLocal
    from web.app.models import CreditLedger, User
    db = SessionLocal()
    try:
        assert db.get(User, uid).first_scan_used_at is not None
        assert db.query(CreditLedger).filter_by(user_id=uid, reason="first_scan_free").count() == 1
    finally:
        db.close()
    assert "actmeter" not in client.get("/profile").text   # after first scan: gone


def test_first_scan_rate_by_variant_counts_per_arm(client, arm):
    from web.app.db import SessionLocal
    from web.app.services.activation import first_scan_rate_by_variant
    from web.app.services.events import record
    db = SessionLocal()
    try:
        before = first_scan_rate_by_variant(db)
        arm("on"); ua = _signup(client)     # meter arm, scans
        arm("off"); _signup(client)         # control arm, doesn't
        record(db, "scan_started", user_id=ua, variant="meter")
        record(db, "scan_started", user_id=ua, variant="meter")   # repeat scan: still one user
        after = first_scan_rate_by_variant(db)
        assert after["meter"]["signups"] == before["meter"]["signups"] + 1
        assert after["meter"]["scanned"] == before["meter"]["scanned"] + 1
        assert after["control"]["signups"] == before["control"]["signups"] + 1
        assert after["control"]["scanned"] == before["control"]["scanned"]
        assert 0 <= after["meter"]["rate"] <= 1
    finally:
        db.close()
