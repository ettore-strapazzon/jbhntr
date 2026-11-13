"""R3-17 — admin CSRF on every /admin POST.

/admin is gated by HTTP Basic auth, which a browser re-sends on a cross-site form
POST, so every state-changing admin route must also enforce require_admin_csrf
(HMAC token bound to SECRET_KEY + ADMIN_TOKEN, plus a same-origin check). The
enumeration tests fail if a new admin POST route or form ships without it.
"""

import os
import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

if "web.app.main" not in sys.modules:
    _tmp = tempfile.mkdtemp()
    os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.sqlite"
    os.environ["SECRET_KEY"] = "x" * 48
    os.environ.setdefault("FILE_ENCRYPTION_KEY", "")
    if not os.environ["FILE_ENCRYPTION_KEY"]:
        from cryptography.fernet import Fernet

        os.environ["FILE_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    os.environ["DEBUG"] = "true"

from fastapi.routing import APIRoute  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from web.app.main import app  # noqa: E402
from web.app.routes import admin as admin_mod  # noqa: E402

ADMIN = ("op", "r317-admin-token")
EMAIL = "r317-csrf@example.com"
TEMPLATES = Path(__file__).resolve().parents[1] / "web" / "app" / "templates"

# Minimal valid form body per route (beyond csrf) so a request that passes the
# guard reaches the handler instead of failing validation with 422.
FORM = {
    "/admin/grant-credits": {"email": EMAIL, "amount": "0"},
    "/admin/reset-usage": {"email": "r317-nobody@example.com"},
    "/admin/set-plan": {"email": "r317-nobody@example.com", "plan": "free"},
    "/admin/clear-board": {"email": "r317-nobody@example.com"},
    "/admin/purge-aggregators": {"cutoff": "0"},     # < 1 => early redirect, no work
    "/admin/referral-unlock": {"reward_id": "999999999"},
    "/admin/referral-hold": {"reward_id": "999999999", "reason": "review"},
    # R3-21 diagnostics: bodies that return early (unknown source / no target);
    # the admin fixture also stubs their outbound calls in case one gets further.
    "/admin/test-source": {"name": "r321-no-such-source"},
    "/admin/test-careers": {},
    "/admin/test-browser": {"name": "", "domain": ""},
    "/admin/test-careers-sample": {"n": "1"},
}

# R3-21: converted from state-changing / money-spending GETs. Diagnostics answer
# with the plain-text report (200); everything else redirects back to /admin (303).
CONVERTED_FROM_GET = ["/admin/reprobe-unresolved", "/admin/test-source",
                      "/admin/test-careers", "/admin/test-browser",
                      "/admin/test-careers-sample"]
DIAGNOSTICS = {"/admin/test-source", "/admin/test-careers", "/admin/test-browser",
               "/admin/test-careers-sample"}


def _api_routes(routes, prefix=""):
    """Every APIRoute in the app with its full path. FastAPI >= 0.16x wraps each
    include_router() in a lazy _IncludedRouter, so walk into those too."""
    for r in routes:
        if isinstance(r, APIRoute):
            yield prefix + r.path, r
        elif getattr(r, "original_router", None) is not None:
            ctx = getattr(r, "include_context", None)
            yield from _api_routes(r.original_router.routes,
                                   prefix + (getattr(ctx, "prefix", "") or ""))


def _admin_post_routes() -> list[APIRoute]:
    return [r for path, r in _api_routes(app.routes)
            if path.startswith("/admin") and "POST" in r.methods]


def _dep_calls(dependant) -> list:
    out = []
    for d in dependant.dependencies:
        out.append(d.call)
        out.extend(_dep_calls(d))
    return out


ROUTES = sorted(r.path for r in _admin_post_routes())


@pytest.fixture(scope="module", autouse=True)
def _app_started():
    with TestClient(app):
        yield


@pytest.fixture
def admin(monkeypatch):
    from web.app.config import config
    monkeypatch.setattr(config, "admin_token", ADMIN[1])
    # Job buttons start detached daemon threads that do real ingest/network work;
    # a request that passes the guard must not actually launch them in tests.
    monkeypatch.setattr(admin_mod, "threading",
                        SimpleNamespace(Thread=lambda *a, **k: SimpleNamespace(
                            start=lambda: None)))
    _stub_outbound(monkeypatch)
    return TestClient(app)


def _stub_outbound(monkeypatch):
    """The diagnostic routes make real (paid) outbound calls: LLM careers scrape,
    Bright Data browser, Clearbit domain lookups. Never in tests."""
    import jbhntr_engine

    from web.app.services import companies_service
    monkeypatch.setattr(jbhntr_engine, "scrape_careers", lambda *a, **k: [])
    monkeypatch.setattr(jbhntr_engine, "browser_fetch_portal", lambda *a, **k: [])
    monkeypatch.setattr(jbhntr_engine, "browser_debug_portal", lambda *a, **k: {})
    monkeypatch.setattr(jbhntr_engine, "browser_configured", lambda *a, **k: False)
    monkeypatch.setattr(companies_service, "_resolve_domain", lambda *a, **k: "")


# ---- regression guards: nothing new can ship unguarded ----

def test_there_are_admin_post_routes_to_check():
    assert len(ROUTES) >= 23, ROUTES
    assert "/admin/run-agencies" in ROUTES      # R3-20: was a job-starting GET
    assert set(CONVERTED_FROM_GET) <= set(ROUTES), set(CONVERTED_FROM_GET) - set(ROUTES)


def test_every_admin_post_route_enforces_require_admin_csrf():
    missing = []
    for r in _admin_post_routes():
        calls = _dep_calls(r.dependant)
        if admin_mod.require_admin_csrf not in calls:
            missing.append(r.path)
        else:   # Basic auth first, so an unauthenticated POST still gets the 401 prompt
            assert calls.index(admin_mod.require_admin) < calls.index(
                admin_mod.require_admin_csrf), r.path
    assert not missing, f"admin POST routes without require_admin_csrf: {missing}"


def test_every_admin_post_form_in_templates_carries_csrf_field():
    forms = []
    for path in TEMPLATES.rglob("*.html"):
        for m in re.finditer(r"<form\b[^>]*>.*?</form>", path.read_text(), re.S | re.I):
            tag = m.group(0)
            if re.search(r'method="post"', tag, re.I) and re.search(r'action="/admin', tag):
                forms.append((path.name, tag))
    assert len(forms) >= 23
    bad = [re.search(r'action="([^"]+)"', t).group(1) for _, t in forms
           if '<input type="hidden" name="csrf" value="{{ admin_csrf }}">' not in t]
    assert not bad, f"admin POST forms without the hidden csrf field: {bad}"
    actions = {re.search(r'action="([^"]+)"', t).group(1) for _, t in forms}
    assert actions <= set(ROUTES), actions - set(ROUTES)
    # R3-21: each converted route is reachable from the UI as a CSRF-carrying form.
    assert set(CONVERTED_FROM_GET) <= actions, set(CONVERTED_FROM_GET) - actions


def test_rendered_admin_page_puts_the_real_token_in_every_post_form(admin):
    html = admin.get("/admin", auth=ADMIN).text
    forms = [f for f in re.findall(r"<form\b[^>]*>.*?</form>", html, re.S | re.I)
             if 'method="post"' in f and 'action="/admin' in f]
    assert forms
    tok = admin_mod.admin_csrf_token()
    assert all(f'name="csrf" value="{tok}"' in f for f in forms)


# ---- per-route behaviour ----

@pytest.mark.parametrize("path", ROUTES)
@pytest.mark.parametrize("case", ["missing", "forged", "foreign-origin",
                                  "null-origin", "sec-fetch-cross-site"])
def test_forged_admin_post_is_refused_403(admin, path, case):
    data = dict(FORM.get(path, {}))
    headers = {}
    if case == "forged":
        data["csrf"] = "forged"
    elif case != "missing":
        data["csrf"] = admin_mod.admin_csrf_token()
        headers = {"foreign-origin": {"Origin": "https://evil.example"},
                   "null-origin": {"Origin": "null"},
                   "sec-fetch-cross-site": {"Sec-Fetch-Site": "cross-site"}}[case]
    r = admin.post(path, data=data, headers=headers, auth=ADMIN, follow_redirects=False)
    assert r.status_code == 403, (path, case, r.status_code)


@pytest.mark.parametrize("path", ROUTES)
def test_same_origin_admin_post_with_token_still_works(admin, path):
    data = dict(FORM.get(path, {}), csrf=admin_mod.admin_csrf_token())
    r = admin.post(path, data=data, auth=ADMIN, follow_redirects=False,
                   headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"})
    expected = 200 if path in DIAGNOSTICS else 303
    assert r.status_code == expected, (path, r.status_code, r.text[:200])


@pytest.mark.parametrize("path", ROUTES)
def test_unauthenticated_admin_post_still_401(admin, path):
    data = dict(FORM.get(path, {}), csrf=admin_mod.admin_csrf_token())
    assert admin.post(path, data=data, follow_redirects=False).status_code == 401


def test_forged_grant_credits_changes_no_balance(admin):
    from web.app.db import SessionLocal
    from web.app.models import CreditLedger, User
    from web.app.services import credits
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(email=EMAIL).first()
        if not user:
            user = User(email=EMAIL)
            db.add(user)
            db.commit()
        before = credits.balance(db, user)
        r = admin.post("/admin/grant-credits", data={"email": EMAIL, "amount": "500"},
                       headers={"Origin": "https://evil.example"}, auth=ADMIN,
                       follow_redirects=False)
        assert r.status_code == 403
        db.expire_all()
        assert credits.balance(db, user) == before
        r = admin.post("/admin/grant-credits",
                       data={"email": EMAIL, "amount": "5",
                             "csrf": admin_mod.admin_csrf_token()},
                       auth=ADMIN, follow_redirects=False)
        assert r.status_code == 303
        db.expire_all()
        assert credits.balance(db, user) == before + 5
    finally:
        db.query(CreditLedger).filter(CreditLedger.user_id == user.id).delete()
        db.query(User).filter(User.id == user.id).delete()
        db.commit()
        db.close()


# ---- R3-20: a GET must never start a background job ----

def _admin_get_routes() -> list[APIRoute]:
    return [r for path, r in _api_routes(app.routes)
            if path.startswith("/admin") and "GET" in r.methods]


# Source markers for "this handler changes state / spends money". A GET handler
# must contain none of them (R3-20 threads; R3-21 deletes/commits and paid calls).
GET_FORBIDDEN = {
    "starts a thread": ("threading.Thread", "Thread("),
    "writes the DB": (".commit(", ".delete(", ".add(", ".add_all(", ".merge("),
    "spends money/quota": ("scrape_careers", "browser_fetch_portal",
                           "browser_debug_portal", "KEYED_SOURCES"),
}


def _forbidden_hits(fn) -> list[str]:
    import inspect
    src = inspect.getsource(fn)
    assert len(src) > 80, fn       # a source we could not read must not pass as clean
    return [kind for kind, marks in GET_FORBIDDEN.items() if any(m in src for m in marks)]


def test_get_guard_detector_is_not_vacuous():
    """Positive controls: the detector must flag known POST handlers that do each
    forbidden thing, or the GET guard below could pass by detecting nothing."""
    assert "starts a thread" in _forbidden_hits(admin_mod.admin_run_agencies)
    assert "writes the DB" in _forbidden_hits(admin_mod.admin_reprobe_unresolved)
    assert "spends money/quota" in _forbidden_hits(admin_mod.admin_test_careers_sample)
    assert "spends money/quota" in _forbidden_hits(admin_mod.admin_test_browser)
    assert "spends money/quota" in _forbidden_hits(admin_mod.admin_test_source)


def test_no_admin_get_route_starts_a_thread_writes_or_spends():
    """Static guard: no GET /admin handler spawns a thread, writes the DB, or makes
    a paid/quota outbound call (those are POST + CSRF)."""
    gets = _admin_get_routes()
    assert len(gets) >= 12, [r.path for r in gets]
    offenders = {r.path: hits for r in gets if (hits := _forbidden_hits(r.endpoint))}
    assert not offenders, f"GET admin routes that change state or spend: {offenders}"


@pytest.mark.parametrize("path", CONVERTED_FROM_GET)
def test_converted_route_get_is_405(admin, path):
    r = admin.get(path, auth=ADMIN, follow_redirects=False)
    assert r.status_code == 405, (path, r.status_code)


def _seed_unresolved_company(name: str) -> int:
    from web.app.db import SessionLocal
    from web.app.models import Company
    db = SessionLocal()
    try:
        c = Company(name=name, ats="none", ats_token=name.lower().replace(" ", "-"))
        db.add(c)
        db.commit()
        return c.id
    finally:
        db.close()


def _company_exists(cid: int) -> bool:
    from web.app.db import SessionLocal
    from web.app.models import Company
    db = SessionLocal()
    try:
        return db.get(Company, cid) is not None
    finally:
        db.close()


def test_get_reprobe_unresolved_is_405_and_deletes_nothing(admin):
    cid = _seed_unresolved_company("R321 Get Co")
    r = admin.get("/admin/reprobe-unresolved", auth=ADMIN, follow_redirects=False)
    assert r.status_code == 405
    assert _company_exists(cid)
    admin.post("/admin/reprobe-unresolved", auth=ADMIN, follow_redirects=False,
               data={"csrf": admin_mod.admin_csrf_token()})       # clean up


@pytest.mark.parametrize("case", ["missing", "forged", "foreign-origin"])
def test_forged_reprobe_post_deletes_nothing(admin, case):
    cid = _seed_unresolved_company(f"R321 Forged {case}")
    data, headers = {}, {}
    if case == "forged":
        data["csrf"] = "forged"
    elif case == "foreign-origin":
        data["csrf"] = admin_mod.admin_csrf_token()
        headers = {"Origin": "https://evil.example"}
    r = admin.post("/admin/reprobe-unresolved", data=data, headers=headers, auth=ADMIN,
                   follow_redirects=False)
    assert r.status_code == 403
    assert _company_exists(cid)
    admin.post("/admin/reprobe-unresolved", auth=ADMIN, follow_redirects=False,
               data={"csrf": admin_mod.admin_csrf_token()})       # clean up


def test_reprobe_post_with_token_clears_markers_and_redirects(admin):
    cid = _seed_unresolved_company("R321 Real Co")
    r = admin.post("/admin/reprobe-unresolved", auth=ADMIN, follow_redirects=False,
                   data={"csrf": admin_mod.admin_csrf_token()},
                   headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 303
    assert r.headers["location"].startswith("/admin?reset_msg=")
    assert not _company_exists(cid)


def test_get_run_agencies_is_405_and_starts_no_job(monkeypatch):
    from web.app.config import config
    monkeypatch.setattr(config, "admin_token", ADMIN[1])
    started = []
    monkeypatch.setattr(admin_mod, "threading", SimpleNamespace(
        Thread=lambda *a, **k: SimpleNamespace(start=lambda: started.append(k))))
    r = TestClient(app).get("/admin/run-agencies?country=it&n=25", auth=ADMIN,
                            follow_redirects=False)
    assert r.status_code == 405, r.status_code
    assert started == []


def test_post_run_agencies_with_token_starts_one_job_for_the_country(monkeypatch):
    from web.app.config import config
    monkeypatch.setattr(config, "admin_token", ADMIN[1])
    started = []
    monkeypatch.setattr(admin_mod, "threading", SimpleNamespace(
        Thread=lambda *a, **k: SimpleNamespace(start=lambda: started.append(k))))
    r = TestClient(app).post("/admin/run-agencies", auth=ADMIN, follow_redirects=False,
                             data={"country": "de", "n": "10",
                                   "csrf": admin_mod.admin_csrf_token()})
    assert r.status_code == 303
    assert "de" in r.headers["location"]
    assert len(started) == 1
