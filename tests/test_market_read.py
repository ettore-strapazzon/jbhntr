"""R3-02 — shareable "my market read" (/r/{token}).

Owner-only lazy mint on Search.share_token, public no-auth stage funnel,
anonymise toggle (default on, no PII), events, OG PNG + static fallback.
Same throwaway-SQLite setup as test_web.py (config is read at import time, so
the env is only set if the app hasn't already been imported by another module).
"""

import os
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

from fastapi.testclient import TestClient  # noqa: E402

from web.app.main import app  # noqa: E402

PW = "Sup3rSecret!x"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True, scope="module")
def _clear_profile_terms_after_module():
    """The suite shares one DB: leave no search_terms/countries behind, or the
    corpus-ranking tests in test_web.py see this module's canary profiles."""
    yield
    from web.app.models import Profile, User
    db = _db()
    try:
        ids = [u.id for u in db.query(User).filter(
            User.email.like("mr%@example.com") | User.email.like("gc%@example.com"))]
        for p in db.query(Profile).filter(Profile.user_id.in_(ids)):
            p.search_terms = []
            p.countries = []
        db.commit()
    finally:
        db.close()


def signup(client, email):
    return client.post("/signup", data={"email": email, "password": PW,
                                        "accept_tos": "1"}, follow_redirects=False)


def _db():
    from web.app.db import SessionLocal
    return SessionLocal()


def _scan(email, status="done", **over):
    """A completed scan with real-looking stage counts, an employer-named result,
    and a profile full of PII canaries. Returns (search_id, user_id)."""
    from web.app.models import JobResult, Profile, Search, User
    db = _db()
    try:
        u = db.query(User).filter_by(email=email).one()
        p = db.query(Profile).filter_by(user_id=u.id).first()
        if p is None:
            p = Profile(user_id=u.id); db.add(p)
        p.objective = "SECRETOBJECTIVE text about me"
        p.about_me = "SECRETABOUTME"
        p.search_terms = ["Head of Operations"]
        p.countries = ["Ireland", "United Kingdom"]
        fields = dict(status=status, raw_count=1840, located_count=612,
                      ranked_count=120, scored_count=14)
        fields.update(over)
        s = Search(user_id=u.id, **fields); db.add(s); db.flush()
        db.add(JobResult(search_id=s.id, user_id=u.id, position=1, short_id="mr",
                         tier=1, score=80, title="Head of Ops",
                         company="SECRETEMPLOYERCO", why_good="x", why_bad="y",
                         dedup_key=f"dk-mr-{s.id}"))
        db.commit()
        return s.id, u.id
    finally:
        db.close()


def _search(sid):
    from web.app.models import Search
    db = _db()
    try:
        return db.get(Search, sid)
    finally:
        db.close()


def _events(name, user_id=None):
    from web.app.models import ProductEvent
    db = _db()
    try:
        q = db.query(ProductEvent).filter(ProductEvent.name == name)
        if user_id is not None:
            q = q.filter(ProductEvent.user_id == user_id)
        return q.all()
    finally:
        db.close()


def test_search_has_share_token_and_anonymous_columns(client):
    from sqlalchemy import inspect

    from web.app.db import engine
    cols = {c["name"]: c for c in inspect(engine).get_columns("searches")}
    assert cols["share_token"]["nullable"] is True
    assert "share_anonymous" in cols


def test_share_mints_token_idempotent_owner_only(client):
    signup(client, "mr1@example.com")
    sid, uid = _scan("mr1@example.com")
    assert _search(sid).share_token is None              # unshared = no surface
    r = client.post(f"/search/{sid}/share", data={"source": "matches"})
    assert r.status_code == 200
    tok = _search(sid).share_token
    assert tok and f"/r/{tok}" in r.text
    client.post(f"/search/{sid}/share", data={"source": "matches"})
    assert _search(sid).share_token == tok               # idempotent

    # Another user cannot share (or learn about) this scan.
    signup(client, "mr1b@example.com")
    assert client.post(f"/search/{sid}/share").status_code == 404
    # Logged out cannot share.
    anon = TestClient(app)
    assert anon.post(f"/search/{sid}/share", follow_redirects=False).status_code in (302, 303, 401, 403, 404)


def test_share_refused_for_running_or_failed_scan(client):
    signup(client, "mr2@example.com")
    sid_run, _ = _scan("mr2@example.com", status="running")
    sid_fail, _ = _scan("mr2@example.com", status="failed")
    assert client.post(f"/search/{sid_run}/share").status_code == 404
    assert client.post(f"/search/{sid_fail}/share").status_code == 404
    assert _search(sid_run).share_token is None


def test_public_read_renders_funnel_anonymised_no_pii(client):
    signup(client, "mr3@example.com")
    sid, uid = _scan("mr3@example.com")
    client.post(f"/search/{sid}/share", data={"source": "matches"})
    tok = _search(sid).share_token
    assert _search(sid).share_anonymous is True          # default ON

    r = TestClient(app).get(f"/r/{tok}")
    assert r.status_code == 200
    body = r.text
    assert "1,840 roles scanned → 14 worth a decision." in body
    for n in ("1,840", "612", "120", "14"):
        assert n in body
    assert "noindex" in body
    assert f"/r/{tok}/card.png" in body                  # og:image is the read PNG
    # No PII / private surfaces when anonymised.
    for leak in ("mr3@example.com", "SECRETOBJECTIVE", "SECRETABOUTME",
                 "SECRETEMPLOYERCO", "Head of Operations", "Ireland"):
        assert leak not in body, leak


def test_anonymise_off_adds_role_but_never_pii(client):
    signup(client, "mr4@example.com")
    sid, uid = _scan("mr4@example.com")
    client.post(f"/search/{sid}/share", data={"source": "matches"})
    tok = _search(sid).share_token
    # Toggle form re-submit with the box unchecked -> anonymise off.
    client.post(f"/search/{sid}/share", data={"source": "matches", "prefs": "1"})
    assert _search(sid).share_anonymous is False
    body = TestClient(app).get(f"/r/{tok}").text
    assert "Head of Operations" in body and "Ireland" in body
    for leak in ("mr4@example.com", "SECRETOBJECTIVE", "SECRETABOUTME",
                 "SECRETEMPLOYERCO"):
        assert leak not in body, leak
    # And back on.
    client.post(f"/search/{sid}/share",
                data={"source": "matches", "prefs": "1", "anonymous": "1"})
    assert "Head of Operations" not in TestClient(app).get(f"/r/{tok}").text


def test_bad_token_404(client):
    anon = TestClient(app)
    assert anon.get("/r/does-not-exist").status_code == 404
    assert anon.get("/r/does-not-exist/card.png").status_code == 404


def test_cta_carries_referral_code(client):
    signup(client, "mr5@example.com")
    sid, uid = _scan("mr5@example.com")
    client.post(f"/search/{sid}/share", data={"source": "matches"})
    from web.app.models import User
    db = _db()
    try:
        code = db.get(User, uid).referral_code
    finally:
        db.close()
    assert code
    assert f"/signup?ref={code}" in TestClient(app).get(f"/r/{_search(sid).share_token}").text


def test_events_emitted(client):
    signup(client, "mr6@example.com")
    sid, uid = _scan("mr6@example.com")
    client.post(f"/search/{sid}/share", data={"source": "matches"})
    client.post(f"/search/{sid}/share", data={"source": "bogus"})       # re-share
    client.post(f"/search/{sid}/share", data={"source": "matches", "prefs": "1"})
    shared = _events("market_read_shared", uid)
    assert len(shared) == 2                               # toggle saves don't count
    assert all(e.properties.get("source") == "matches" for e in shared)

    before = len([e for e in _events("shared_artifact_viewed")
                  if e.properties.get("kind") == "read" and e.user_id is None])
    anon = TestClient(app)
    tok = _search(sid).share_token
    anon.get(f"/r/{tok}"); anon.get(f"/r/{tok}")
    after = len([e for e in _events("shared_artifact_viewed")
                 if e.properties.get("kind") == "read" and e.user_id is None])
    assert after - before == 2


def test_not_ready_read_is_friendly_and_not_a_funnel(client):
    signup(client, "mr7@example.com")
    sid, uid = _scan("mr7@example.com")
    client.post(f"/search/{sid}/share", data={"source": "matches"})
    tok = _search(sid).share_token
    from web.app.models import Search
    db = _db()
    try:
        db.get(Search, sid).status = "running"; db.commit()
    finally:
        db.close()
    r = TestClient(app).get(f"/r/{tok}")
    assert r.status_code == 200 and "isn’t ready yet" in r.text
    assert "roles scanned →" not in r.text and "funnel-row" not in r.text


def test_og_png_renders_and_falls_back(client, monkeypatch):
    signup(client, "mr8@example.com")
    sid, uid = _scan("mr8@example.com")
    client.post(f"/search/{sid}/share", data={"source": "matches"})
    tok = _search(sid).share_token
    r = TestClient(app).get(f"/r/{tok}/card.png")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/")

    # Rasteriser unavailable -> static brand fallback, never a 500.
    from web.app.routes import market_read
    market_read._drop_png(tok)
    monkeypatch.setattr(market_read, "rasterise_svg", lambda svg, dest: False)
    r = TestClient(app).get(f"/r/{tok}/card.png")
    assert r.status_code in (200, 302)
    if r.status_code == 200:
        assert r.headers["content-type"].startswith("image/")
    assert not market_read._png_path(tok).exists()


def test_og_svg_escapes_and_respects_anonymise():
    from web.app.models import Search
    from web.app.routes.market_read import _og_svg
    s = Search(raw_count=10, located_count=5, ranked_count=3, scored_count=1)
    svg = _og_svg(s, "<script>x</script>")
    assert "<script>" not in svg and "&lt;script&gt;" in svg
    assert "Head of" not in _og_svg(s, "")


def test_share_button_on_matches_page(client):
    signup(client, "mr9@example.com")
    sid, uid = _scan("mr9@example.com")
    html = client.get("/matches/results").text
    assert f"/search/{sid}/share" in html and "Share this market read" in html


# ------------------- GC send-back (COMPLIANCE_CARD 2026-11-13) ------------------ #
def _card(email):
    """An owned JobResult (employer canary) for match-card tests."""
    from web.app.models import JobResult, User
    sid, uid = _scan(email)
    db = _db()
    try:
        return db.query(JobResult).filter_by(search_id=sid).one().id, uid
    finally:
        db.close()


def _card_token(rid):
    from web.app.models import JobResult
    db = _db()
    try:
        return db.get(JobResult, rid).share_token
    finally:
        db.close()


def test_read_unshare_404s_page_and_image(client):
    signup(client, "gc1@example.com")
    sid, uid = _scan("gc1@example.com")
    client.post(f"/search/{sid}/share", data={"source": "matches"})
    tok = _search(sid).share_token
    anon = TestClient(app)
    assert anon.get(f"/r/{tok}/card.png").status_code == 200
    from web.app.routes.share import read_png_path
    png_cached = read_png_path(tok).exists()

    # Not the owner -> 404, still shared.
    signup(client, "gc1b@example.com")
    assert client.post(f"/search/{sid}/unshare").status_code == 404
    assert _search(sid).share_token == tok

    owner = TestClient(app)
    owner.post("/login", data={"email": "gc1@example.com", "password": PW})
    r = owner.post(f"/search/{sid}/unshare")
    assert r.status_code == 200 and "Link turned off" in r.text
    assert _search(sid).share_token is None
    assert anon.get(f"/r/{tok}").status_code == 404
    assert anon.get(f"/r/{tok}/card.png").status_code == 404
    if png_cached:
        assert not read_png_path(tok).exists()
    # Re-sharing mints a new token.
    owner.post(f"/search/{sid}/share", data={"source": "matches"})
    assert _search(sid).share_token not in (None, tok)


def test_card_unshare_404s_page_and_image(client):
    signup(client, "gc2@example.com")
    rid, uid = _card("gc2@example.com")
    sheet = client.post(f"/job/{rid}/share", data={"source": "matches"}).text
    assert f"/job/{rid}/unshare" in sheet and "Stop sharing" in sheet
    assert "You can stop sharing at any time." in sheet
    tok = _card_token(rid)
    anon = TestClient(app)
    assert anon.get(f"/m/{tok}/card.png").status_code == 200
    r = client.post(f"/job/{rid}/unshare")
    assert r.status_code == 200 and "Link turned off" in r.text
    assert _card_token(rid) is None
    assert anon.get(f"/m/{tok}").status_code == 404
    assert anon.get(f"/m/{tok}/card.png").status_code == 404


def test_read_sheet_has_stop_sharing(client):
    signup(client, "gc3@example.com")
    sid, uid = _scan("gc3@example.com")
    sheet = client.post(f"/search/{sid}/share", data={"source": "matches"}).text
    assert f"/search/{sid}/unshare" in sheet and "Stop sharing" in sheet


def test_noindex_headers_on_pages_and_images(client):
    signup(client, "gc4@example.com")
    sid, uid = _scan("gc4@example.com")
    client.post(f"/search/{sid}/share", data={"source": "matches"})
    rid, _ = _card("gc4@example.com")
    client.post(f"/job/{rid}/share", data={"source": "matches"})
    rtok, mtok = _search(sid).share_token, _card_token(rid)
    anon = TestClient(app)
    for url in (f"/r/{rtok}", f"/r/{rtok}/card.png", f"/m/{mtok}",
                f"/m/{mtok}/card.png", "/r/nope", "/r/nope/card.png",
                "/m/nope", "/m/nope/card.png"):
        r = anon.get(url, follow_redirects=False)
        assert "noindex" in r.headers.get("x-robots-tag", ""), url


def test_png_cache_is_outside_public_static(client):
    from web.app.config import ROOT
    from web.app.routes import share
    static = (ROOT / "web" / "app" / "static").resolve()
    assert static not in share._OG_DIR.resolve().parents
    signup(client, "gc5@example.com")
    sid, uid = _scan("gc5@example.com")
    client.post(f"/search/{sid}/share", data={"source": "matches"})
    tok = _search(sid).share_token
    TestClient(app).get(f"/r/{tok}/card.png")
    assert TestClient(app).get(f"/static/og/r-{tok}.png").status_code == 404


def test_captions_disclose_referral_incentive(client):
    signup(client, "gc6@example.com")
    sid, uid = _scan("gc6@example.com")
    import html as _h
    read = _h.unescape(client.post(f"/search/{sid}/share",
                                   data={"source": "matches"}).text)
    assert ("I ran a JBHNTR scan: 1,840 live roles, narrowed to 14 worth a decision."
            in read)
    assert ("(Sign up from the read and you get bonus credits; I get some once "
            "you run your first scan.)") in read
    rid, _ = _card("gc6@example.com")
    card = _h.unescape(client.post(f"/job/{rid}/share", data={"source": "matches"}).text)
    assert "I'm trying JBHNTR: it scores each job both ways" in card
    assert ("(Sign up from the card and you get bonus credits; I get some once "
            "you run your first scan.)") in card
    assert "every live role" not in card.lower()


def test_public_copy_cleared_and_first_scan_free_gated(client, monkeypatch):
    signup(client, "gc7@example.com")
    sid, uid = _scan("gc7@example.com")
    client.post(f"/search/{sid}/share", data={"source": "matches"})
    tok = _search(sid).share_token
    body = TestClient(app).get(f"/r/{tok}").text
    assert "Every live role" not in body and "Every role is scored" not in body
    assert "The shortlisted roles are scored both ways" in body
    assert "First scan free, no credit card." in body and "No card." not in body
    assert "bonus credits; the person who shared it" in body      # referral disclosed
    from web.app.config import config
    monkeypatch.setattr(config, "first_scan_free", False)
    body = TestClient(app).get(f"/r/{tok}").text
    assert "first scan free" not in body.lower()


def test_employer_defaults_off_on_first_share(client):
    signup(client, "gc8@example.com")
    rid, uid = _card("gc8@example.com")
    client.post(f"/job/{rid}/share", data={"source": "matches"})
    body = TestClient(app).get(f"/m/{_card_token(rid)}").text
    assert "SECRETEMPLOYERCO" not in body


def test_account_deletion_removes_artefact_pngs(client):
    signup(client, "gc9@example.com")
    sid, uid = _scan("gc9@example.com")
    client.post(f"/search/{sid}/share", data={"source": "matches"})
    rid, _ = _card("gc9@example.com")
    client.post(f"/job/{rid}/share", data={"source": "matches"})
    rtok, mtok = _search(sid).share_token, _card_token(rid)
    from web.app.routes.share import card_png_path, read_png_path
    # Plant cached files so the test holds even where cairosvg is unavailable.
    for p in (read_png_path(rtok), card_png_path(mtok)):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x89PNG")
    client.post("/account/delete", data={"confirm": "DELETE"})
    assert not read_png_path(rtok).exists() and not card_png_path(mtok).exists()
    anon = TestClient(app)
    assert anon.get(f"/r/{rtok}/card.png").status_code == 404
    assert anon.get(f"/m/{mtok}/card.png").status_code == 404


def test_cookies_and_privacy_disclose_jb_ref_and_shares(client):
    c = TestClient(app).get("/cookies").text
    assert "jb_ref" in c and "<b>two</b> cookies" in c
    p = TestClient(app).get("/privacy").text
    assert "Shared match cards (only if you press Share)" in p and "Referrals" in p
    assert "Two strictly-necessary cookies" in p
