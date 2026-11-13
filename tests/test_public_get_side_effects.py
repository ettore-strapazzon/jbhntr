"""R3-22 — public GET side effects.

* GET /logout is gone (405); logout is a same-origin POST form in the nav.
* View/click KPI events (shared_artifact_viewed on /m and /r, channel_click on
  /go, invite_page_viewed) only count a top-level document load by a person:
  a cross-site embed (Sec-Fetch-Dest image/iframe/script/...), a prefetch, or a
  link-preview crawler still gets the page/redirect but records no event.
* /unsubscribe: GET shows a confirm page (mail scanners prefetch GETs); POST with
  the same signed token unsubscribes (RFC 8058 one-click).
* Static guard: no public GET handler writes state unless it is on an explicit
  allowlist of legitimate tracked GETs.

Same throwaway-SQLite setup as test_web.py; rows are deleted at module teardown.
"""

import inspect
import os
import re
import sys
import tempfile

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

from web.app.config import config  # noqa: E402
from web.app.main import app  # noqa: E402

PW = "Sup3rSecret!x"
PREFIX = "r322"           # every account this module creates: r322-*@example.com


def _db():
    from web.app.db import SessionLocal
    return SessionLocal()


@pytest.fixture(autouse=True, scope="module")
def _cleanup_module_rows():
    with TestClient(app):          # runs lifespan -> init_db() on a fresh DB
        yield
    from web.app.models import Base, User
    db = _db()
    try:
        ids = [u.id for u in db.query(User).filter(User.email.like(f"{PREFIX}-%@example.com"))]
        if ids:
            for table in reversed(Base.metadata.sorted_tables):
                if table.name != "users" and "user_id" in table.c:
                    db.execute(table.delete().where(table.c.user_id.in_(ids)))
            db.query(User).filter(User.id.in_(ids)).delete(synchronize_session=False)
            db.commit()
    finally:
        db.close()


def _signup(name) -> tuple[TestClient, int]:
    from web.app.models import User
    c = TestClient(app)
    email = f"{PREFIX}-{name}@example.com"
    r = c.post("/signup", data={"email": email, "password": PW, "accept_tos": "1"},
               follow_redirects=False)
    assert r.status_code == 303, r.text[:300]
    db = _db()
    try:
        return c, db.query(User).filter_by(email=email).one().id
    finally:
        db.close()


def _count(name, **props) -> int:
    from web.app.models import ProductEvent
    db = _db()
    try:
        rows = db.query(ProductEvent).filter_by(name=name).all()
        return len([e for e in rows
                    if all((e.properties or {}).get(k) == v for k, v in props.items())])
    finally:
        db.close()


def _shared_card(uid) -> str:
    """A shared JobResult owned by uid; returns its public token."""
    from web.app.models import JobResult, Search
    db = _db()
    try:
        s = Search(user_id=uid, status="done"); db.add(s); db.flush()
        tok = f"r322card{s.id}"
        db.add(JobResult(search_id=s.id, user_id=uid, position=1, short_id="r3",
                         tier=1, score=80, fit_role=80, fit_candidate=70,
                         title="Head of Ops", company="Acme", why_good="x",
                         why_bad="y", dedup_key=f"dk-r322-{s.id}", share_token=tok))
        db.commit()
        return tok
    finally:
        db.close()


def _shared_read(uid) -> str:
    from web.app.models import JobResult, Search
    db = _db()
    try:
        s = Search(user_id=uid, status="done", raw_count=100, located_count=50,
                   ranked_count=20, scored_count=5)
        db.add(s); db.flush()
        s.share_token = f"r322read{s.id}"
        db.add(JobResult(search_id=s.id, user_id=uid, position=1, short_id="r3",
                         tier=1, score=80, title="Head of Ops", company="Acme",
                         why_good="x", why_bad="y", dedup_key=f"dk-r322r-{s.id}"))
        db.commit()
        return s.share_token
    finally:
        db.close()


# ============================== 1. logout ================================== #

def test_get_logout_is_405_and_keeps_the_session():
    c, _ = _signup("getout")
    r = c.get("/logout", follow_redirects=False)
    assert r.status_code == 405
    assert c.get("/account", follow_redirects=False).status_code == 200   # still in


def test_same_origin_post_logout_ends_the_session():
    c, _ = _signup("postout")
    r = c.post("/logout", headers={"Sec-Fetch-Site": "same-origin",
                                   "Origin": "http://testserver"},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert c.get("/account", follow_redirects=False).status_code in (303, 307)


@pytest.mark.parametrize("headers", [
    {"Sec-Fetch-Site": "cross-site"},
    {"Origin": "https://evil.example"},
    {"Origin": "null"},
])
def test_cross_site_post_logout_is_refused(headers):
    c, _ = _signup("xsout" + str(abs(hash(tuple(headers.items()))) % 10000))
    r = c.post("/logout", headers=headers, follow_redirects=False)
    assert r.status_code == 403
    assert c.get("/account", follow_redirects=False).status_code == 200   # still in


def test_nav_logout_is_a_post_form_not_a_link():
    c, _ = _signup("navout")
    html = c.get("/account").text
    assert 'href="/logout"' not in html
    forms = re.findall(r'<form[^>]*action="/logout"[^>]*>', html)
    assert len(forms) == 2, forms                 # desktop nav + mobile menu
    assert all('method="post"' in f for f in forms), forms


# ============================ 2. KPI view gating =========================== #

NOT_A_PAGE_VIEW = [
    {"Sec-Fetch-Dest": "image"},
    {"Sec-Fetch-Dest": "iframe"},
    {"Sec-Fetch-Dest": "frame"},
    {"Sec-Fetch-Dest": "script"},
    {"Sec-Fetch-Dest": "style"},
    {"Sec-Fetch-Dest": "embed"},
    {"Sec-Fetch-Dest": "object"},
    {"Sec-Fetch-Dest": "empty"},                  # fetch()/XHR
    {"Sec-Purpose": "prefetch"},                  # speculative load, not a visit
    {"Purpose": "prefetch"},
    {"User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"},
    {"User-Agent": "Twitterbot/1.0"},
    {"User-Agent": "Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)"},
    {"User-Agent": "LinkedInBot/1.0 (compatible; Mozilla/5.0; Apache-HttpClient +http://www.linkedin.com)"},
    {"User-Agent": "WhatsApp/2.23.20.0 A"},
    {"User-Agent": "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)"},
    {"User-Agent": "TelegramBot (like TwitterBot)"},
    {"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"},
    {"User-Agent": ""},
]
BROWSER = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
REAL_VIEW = [
    {"User-Agent": BROWSER, "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
     "Sec-Fetch-Site": "cross-site"},          # a click from another site counts
    {"User-Agent": BROWSER},                   # older browser: no Sec-Fetch-* at all
]


@pytest.fixture(scope="module")
def card_token():
    _, uid = _signup("cardowner")
    return _shared_card(uid)


@pytest.fixture(scope="module")
def read_token():
    _, uid = _signup("readowner")
    return _shared_read(uid)


@pytest.mark.parametrize("headers", NOT_A_PAGE_VIEW)
def test_card_embed_or_crawler_gets_page_but_records_no_view(card_token, headers):
    before = _count("shared_artifact_viewed", kind="card")
    r = TestClient(app).get(f"/m/{card_token}", headers=headers)
    assert r.status_code == 200 and "Head of Ops" in r.text
    assert _count("shared_artifact_viewed", kind="card") == before


@pytest.mark.parametrize("headers", REAL_VIEW)
def test_card_document_view_still_counts(card_token, headers):
    before = _count("shared_artifact_viewed", kind="card")
    assert TestClient(app).get(f"/m/{card_token}", headers=headers).status_code == 200
    assert _count("shared_artifact_viewed", kind="card") == before + 1


@pytest.mark.parametrize("headers", NOT_A_PAGE_VIEW)
def test_read_embed_or_crawler_gets_page_but_records_no_view(read_token, headers):
    before = _count("shared_artifact_viewed", kind="read")
    r = TestClient(app).get(f"/r/{read_token}", headers=headers)
    assert r.status_code == 200
    assert _count("shared_artifact_viewed", kind="read") == before


@pytest.mark.parametrize("headers", REAL_VIEW)
def test_read_document_view_still_counts(read_token, headers):
    before = _count("shared_artifact_viewed", kind="read")
    assert TestClient(app).get(f"/r/{read_token}", headers=headers).status_code == 200
    assert _count("shared_artifact_viewed", kind="read") == before + 1


@pytest.mark.parametrize("ua", [BROWSER, "facebookexternalhit/1.1", "Twitterbot/1.0"])
def test_og_image_fetch_never_counts_as_a_view(card_token, read_token, ua):
    before = _count("shared_artifact_viewed")
    c = TestClient(app)
    for path in (f"/m/{card_token}/card.png", f"/r/{read_token}/card.png"):
        r = c.get(path, headers={"User-Agent": ua, "Sec-Fetch-Dest": "image"},
                  follow_redirects=False)
        assert r.status_code in (200, 302), (path, r.status_code)
    assert _count("shared_artifact_viewed") == before


@pytest.mark.parametrize("headers", NOT_A_PAGE_VIEW)
def test_go_embed_or_crawler_redirects_but_records_no_click(headers):
    ch = "r322embed"
    before = _count("channel_click", channel=ch)
    r = TestClient(app).get(f"/go/{ch}?to=/credits", headers=headers,
                            follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/credits"
    assert _count("channel_click", channel=ch) == before


@pytest.mark.parametrize("headers", REAL_VIEW)
def test_go_document_click_still_counts(headers):
    ch = "r322real"
    before = _count("channel_click", channel=ch)
    r = TestClient(app).get(f"/go/{ch}?to=/credits", headers=headers,
                            follow_redirects=False)
    assert r.status_code == 302
    assert _count("channel_click", channel=ch) == before + 1


@pytest.fixture
def invite_on(monkeypatch):
    monkeypatch.setattr(config, "invite_page", True)


def _invite_views(uid) -> int:
    from web.app.models import ProductEvent
    db = _db()
    try:
        return db.query(ProductEvent).filter_by(name="invite_page_viewed",
                                                user_id=uid).count()
    finally:
        db.close()


@pytest.mark.parametrize("dest", ["iframe", "image", "script", "empty"])
def test_invite_embed_gets_page_but_records_no_view(invite_on, dest):
    c, uid = _signup(f"inv-{dest}")
    r = c.get("/invite", headers={"Sec-Fetch-Dest": dest})
    assert r.status_code == 200
    assert _invite_views(uid) == 0


def test_invite_document_view_still_counts(invite_on):
    c, uid = _signup("inv-doc")
    assert c.get("/invite", headers={"Sec-Fetch-Dest": "document"}).status_code == 200
    assert c.get("/invite").status_code == 200
    assert _invite_views(uid) == 2


# ============================= 3. unsubscribe ============================== #

def _digest_state(uid):
    from web.app.models import User
    db = _db()
    try:
        u = db.get(User, uid)
        return u.digest, u.premium_requested_at
    finally:
        db.close()


def _set_digest(uid, value="daily"):
    from web.app.models import User, utcnow
    db = _db()
    try:
        u = db.get(User, uid)
        u.digest = value
        u.premium_requested_at = utcnow()
        db.commit()
    finally:
        db.close()


def test_get_unsubscribe_shows_confirm_form_and_changes_nothing():
    from web.app.services.email import make_unsub_token
    _, uid = _signup("unsget")
    _set_digest(uid)
    tok = make_unsub_token(uid)
    r = TestClient(app).get(f"/unsubscribe?t={tok}")
    assert r.status_code == 200
    assert re.search(r'<form[^>]*method="post"[^>]*action="/unsubscribe"', r.text) or \
        re.search(r'<form[^>]*action="/unsubscribe"[^>]*method="post"', r.text)
    assert f'value="{tok}"' in r.text
    assert _digest_state(uid)[0] == "daily"            # a prefetch unsubscribes nobody


def test_get_unsubscribe_with_bad_token_has_no_form():
    r = TestClient(app).get("/unsubscribe?t=garbage")
    assert r.status_code == 200
    assert 'action="/unsubscribe"' not in r.text
    assert "expired" in r.text


def test_rfc8058_one_click_post_unsubscribes():
    """A mailbox provider POSTs `List-Unsubscribe=One-Click` to the exact URI in
    the List-Unsubscribe header — no cookies, no Origin of ours."""
    from web.app.services.email import make_unsub_token
    _, uid = _signup("unspost")
    _set_digest(uid)
    tok = make_unsub_token(uid)
    r = TestClient(app).post(f"/unsubscribe?t={tok}",
                             data={"List-Unsubscribe": "One-Click"},
                             headers={"Origin": "https://mail.example"})
    assert r.status_code == 200
    assert _digest_state(uid)[0] == "off"


def test_confirm_form_post_unsubscribes():
    from web.app.services.email import make_unsub_token
    _, uid = _signup("unsform")
    _set_digest(uid)
    r = TestClient(app).post("/unsubscribe", data={"t": make_unsub_token(uid)})
    assert r.status_code == 200 and "No more digests" in r.text
    assert _digest_state(uid)[0] == "off"


def test_post_unsubscribe_waitlist_scope():
    from web.app.services.email import make_unsub_token
    _, uid = _signup("unswl")
    _set_digest(uid)
    r = TestClient(app).post("/unsubscribe",
                             data={"t": make_unsub_token(uid), "scope": "waitlist"})
    assert r.status_code == 200
    digest, requested = _digest_state(uid)
    assert requested is None and digest == "daily"


def test_post_unsubscribe_bad_token_is_400_and_changes_nothing():
    _, uid = _signup("unsbad")
    _set_digest(uid)
    r = TestClient(app).post("/unsubscribe", data={"t": "garbage"})
    assert r.status_code == 400
    assert _digest_state(uid)[0] == "daily"


def test_digest_headers_point_at_a_working_one_click_post(monkeypatch):
    """The headers the digest is sent with must round-trip: POSTing the RFC 8058
    body to the List-Unsubscribe URI turns the digest off."""
    from urllib.parse import urlsplit

    from web.app.services import email as mail
    _, uid = _signup("unshdr")
    _set_digest(uid)
    sent = {}

    def fake_send(to, subject, text, html, headers=None):
        sent.update(headers or {})
        return True

    monkeypatch.setattr(mail, "send", fake_send)
    assert mail.send_digest("x@example.com", {
        "n": 1, "top_score": 90, "top_title": "A", "top_company": "B",
        "top_location": "C", "reviewed": 40, "jobs": [], "remaining": 0,
        "closing": "ok", "email": "x@example.com"}, mail.make_unsub_token(uid))
    assert sent["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    m = re.fullmatch(r"<(.+)>", sent["List-Unsubscribe"])
    assert m, sent["List-Unsubscribe"]
    u = urlsplit(m.group(1))
    r = TestClient(app).post(f"{u.path}?{u.query}", data={"List-Unsubscribe": "One-Click"})
    assert r.status_code == 200
    assert _digest_state(uid)[0] == "off"


# ===================== 4. static guard: public GET writes ================== #

def _api_routes(routes, prefix=""):
    for r in routes:
        if isinstance(r, APIRoute):
            yield prefix + r.path, r
        elif getattr(r, "original_router", None) is not None:
            yield from _api_routes(r.original_router.routes,
                                   prefix + getattr(r, "prefix", ""))
        elif getattr(r, "routes", None):
            yield from _api_routes(r.routes, prefix + getattr(r, "path", ""))


# A public GET handler containing any of these changes state or emits an event.
WRITE_MARKS = (".commit(", ".delete(", ".add(", ".add_all(", ".merge(",
               "record(", "record_once(", "logout(", "Thread(")

# Legitimate GETs that write, each with why it is safe. Anything new must be
# added here deliberately (or made a POST).
ALLOWED_GET_WRITES = {
    "/auth/google/callback": "OAuth redirect target; state-checked by authlib",
    "/matches": "record_once(first_shortlist_viewed): idempotent, own session only",
    "/m/{token}": "shared_artifact_viewed, gated by countable_view()",
    "/r/{token}": "shared_artifact_viewed (gated by countable_view()) + "
                  "ensure_code commit (idempotent backfill)",
    "/go/{channel}": "channel_click, gated by countable_view()",
    "/invite": "invite_page_viewed (gated by countable_view()) + ensure_code commit",
    "/credits": "ensure_code commit (idempotent backfill of a missing referral code)",
    "/boardroom/pull": "admin Basic auth + require_same_origin (R3-21)",
}
GATED_VIEWS = {"/m/{token}", "/r/{token}", "/go/{channel}", "/invite"}


def _public_gets():
    return {p: r for p, r in _api_routes(app.routes)
            if "GET" in r.methods and not p.startswith("/admin")}


def _writes(fn) -> list[str]:
    src = inspect.getsource(fn)
    assert "def " in src, fn       # a source we could not read must not pass as clean
    return [m for m in WRITE_MARKS if m in src]


def test_public_get_write_detector_is_not_vacuous():
    from web.app.routes import account, auth_routes
    assert _writes(account.set_digest)            # a known POST that commits
    assert _writes(auth_routes.do_logout)


def test_no_public_get_writes_outside_the_allowlist():
    gets = _public_gets()
    assert len(gets) >= 20, sorted(gets)
    offenders = {p: hits for p, r in gets.items()
                 if p not in ALLOWED_GET_WRITES and (hits := _writes(r.endpoint))}
    assert not offenders, f"public GET routes that write state: {offenders}"
    stale = set(ALLOWED_GET_WRITES) - set(gets)
    assert not stale, f"allowlisted GETs that no longer exist: {stale}"


def test_logout_and_unsubscribe_are_not_get_writes():
    gets = _public_gets()
    assert "/logout" not in gets
    assert "/unsubscribe" in gets and not _writes(gets["/unsubscribe"].endpoint)


def test_tracked_view_gets_go_through_the_gate():
    gets = _public_gets()
    for p in GATED_VIEWS:
        assert "countable_view(" in inspect.getsource(gets[p].endpoint), p
