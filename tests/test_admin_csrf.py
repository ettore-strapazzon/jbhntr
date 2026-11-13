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
}


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
    return TestClient(app)


# ---- regression guards: nothing new can ship unguarded ----

def test_there_are_admin_post_routes_to_check():
    assert len(ROUTES) >= 18, ROUTES
    assert "/admin/run-agencies" in ROUTES      # R3-20: was a job-starting GET


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
    assert len(forms) >= 18
    bad = [re.search(r'action="([^"]+)"', t).group(1) for _, t in forms
           if '<input type="hidden" name="csrf" value="{{ admin_csrf }}">' not in t]
    assert not bad, f"admin POST forms without the hidden csrf field: {bad}"
    actions = {re.search(r'action="([^"]+)"', t).group(1) for _, t in forms}
    assert actions <= set(ROUTES), actions - set(ROUTES)


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
    assert r.status_code == 303, (path, r.status_code, r.text[:200])


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


def test_no_admin_get_route_starts_a_background_thread():
    """Static guard: no GET /admin handler spawns a thread (jobs are POST + CSRF)."""
    import inspect
    gets = _admin_get_routes()
    assert len(gets) >= 15, [r.path for r in gets]
    offenders = [r.path for r in gets if "threading.Thread" in inspect.getsource(r.endpoint)]
    assert not offenders, f"GET admin routes that start a background job: {offenders}"


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
