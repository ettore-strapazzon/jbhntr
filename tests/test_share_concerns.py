"""R3-10 — match-card fit-notes control (COMPLIANCE_CARD v1.1 card verdict #2, C11).

The share sheet previews the EXACT bullets the public /m/{token} page and OG PNG
will show; the "Watch out" (concerns) bullets are a separate owner-only opt-in,
`JobResult.share_show_concerns`, default OFF. Same throwaway-SQLite setup as
test_web.py; every row this module adds is removed in a module teardown.
"""

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

from fastapi.testclient import TestClient  # noqa: E402

from web.app.main import app  # noqa: E402

PW = "Sup3rSecret!x"
PREFIX = "r310-"
GOOD = "Strong remote culture. Pay band above your floor. Clear scope."
BAD = "Travel heavy role. Wants German fluency."


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _db():
    from web.app.db import SessionLocal
    return SessionLocal()


@pytest.fixture(autouse=True, scope="module")
def _cleanup_module_rows():
    """The suite shares one DB: remove every row this module created."""
    yield
    from web.app.models import (CreditLedger, JobResult, ProductEvent, Profile,
                                Search, Session, User)
    from web.app.routes.share import delete_user_artefact_pngs
    db = _db()
    try:
        ids = [u.id for u in db.query(User).filter(User.email.like(f"{PREFIX}%"))]
        if ids:
            for uid in ids:
                delete_user_artefact_pngs(db, uid)
            for model in (JobResult, Search, CreditLedger, ProductEvent, Profile,
                          Session):
                db.query(model).filter(model.user_id.in_(ids)).delete(
                    synchronize_session=False)
            db.query(User).filter(User.id.in_(ids)).delete(synchronize_session=False)
            db.commit()
    finally:
        db.close()


def signup(client, email):
    return client.post("/signup", data={"email": email, "password": PW,
                                        "accept_tos": "1"}, follow_redirects=False)


def _result(email):
    from web.app.models import JobResult, Search, User
    db = _db()
    try:
        u = db.query(User).filter_by(email=email).one()
        s = Search(user_id=u.id, status="done"); db.add(s); db.flush()
        jr = JobResult(search_id=s.id, user_id=u.id, position=1, short_id="fn",
                       tier=1, score=80, fit_role=78, fit_candidate=70,
                       title="Head of Data", company="Acme Corp",
                       why_good=GOOD, why_bad=BAD, dedup_key=f"dk-{email}")
        db.add(jr); db.commit()
        return jr.id
    finally:
        db.close()


def _row(rid):
    from web.app.models import JobResult
    db = _db()
    try:
        return db.get(JobResult, rid)
    finally:
        db.close()


def _bullets(html: str, col: str) -> list[str]:
    """The <li> texts of one .why-col (good|bad) block, in order."""
    m = re.search(rf'class="why-col {col}".*?<ul>(.*?)</ul>', html, re.S)
    if not m:
        return []
    return [re.sub(r"\s+", " ", t).strip()
            for t in re.findall(r"<li[^>]*>(.*?)</li>", m.group(1), re.S)]


def _new_share(client, n):
    email = f"{PREFIX}{n}@example.com"
    signup(client, email)
    rid = _result(email)
    sheet = client.post(f"/job/{rid}/share", data={"source": "matches"})
    assert sheet.status_code == 200
    return rid, sheet.text


# ---------------------------------------------------------------- model / default
def test_column_exists_and_defaults_off(client):
    rid, _ = _new_share(client, 1)
    assert _row(rid).share_show_concerns is False


def test_migrator_lists_the_column():
    import inspect

    from web.app import db as dbmod
    assert '"share_show_concerns": ("BOOLEAN", "DEFAULT false")' in inspect.getsource(dbmod)


# ---------------------------------------------------------------- default off
def test_default_off_hides_concerns_on_page(client):
    rid, _ = _new_share(client, 2)
    page = TestClient(app).get(f"/m/{_row(rid).share_token}").text
    assert "Travel heavy role" not in page and "German fluency" not in page
    assert "Watch out" not in page
    assert "Strong remote culture" in page            # "Fits" stays on


def test_default_off_hides_concerns_in_png_source(client):
    from web.app.routes.share import _og_svg
    rid, _ = _new_share(client, 3)
    svg = _og_svg(_row(rid))
    assert "Travel heavy role" not in svg and "Watch out" not in svg
    assert "Strong remote culture" in svg             # PNG carries the fits too


# ---------------------------------------------------------------- toggle on/off
def test_toggle_on_shows_concerns_then_off_hides(client):
    from web.app.routes.share import _og_svg
    rid, _ = _new_share(client, 4)
    tok = _row(rid).share_token
    client.post(f"/job/{rid}/share",
                data={"source": "matches", "prefs": "1", "show_concerns": "1"})
    assert _row(rid).share_show_concerns is True
    page = TestClient(app).get(f"/m/{tok}").text
    assert "Travel heavy role" in page and "Watch out" in page
    svg = _og_svg(_row(rid))
    assert "Travel heavy role" in svg and "Watch out" in svg
    # Unchecking (field absent) turns it back off; the employer toggle is independent.
    client.post(f"/job/{rid}/share", data={"source": "matches", "prefs": "1"})
    assert _row(rid).share_show_concerns is False
    assert "Travel heavy role" not in TestClient(app).get(f"/m/{tok}").text


def test_toggle_drops_cached_png(client):
    from web.app.routes.share import card_png_path
    rid, _ = _new_share(client, 5)
    tok = _row(rid).share_token
    p = card_png_path(tok)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"stale")
    client.post(f"/job/{rid}/share",
                data={"source": "matches", "prefs": "1", "show_concerns": "1"})
    assert not p.exists()                             # re-renders with the new choice


def test_reshare_after_stop_resets_concerns_off(client):
    rid, _ = _new_share(client, 6)
    client.post(f"/job/{rid}/share",
                data={"source": "matches", "prefs": "1", "show_concerns": "1"})
    client.post(f"/job/{rid}/unshare")
    client.post(f"/job/{rid}/share", data={"source": "matches"})
    assert _row(rid).share_show_concerns is False


# ---------------------------------------------------------------- authz
def test_non_owner_cannot_toggle(client):
    rid, _ = _new_share(client, 7)
    tok = _row(rid).share_token
    with TestClient(app) as other:
        signup(other, f"{PREFIX}7b@example.com")
        r = other.post(f"/job/{rid}/share",
                       data={"source": "matches", "prefs": "1", "show_concerns": "1"})
        assert r.status_code == 404
    assert _row(rid).share_show_concerns is False
    assert "Travel heavy role" not in TestClient(app).get(f"/m/{tok}").text


def test_anonymous_cannot_toggle(client):
    rid, _ = _new_share(client, 8)
    r = TestClient(app).post(f"/job/{rid}/share",
                             data={"prefs": "1", "show_concerns": "1"},
                             follow_redirects=False)
    assert r.status_code in (303, 401, 403, 404)
    assert _row(rid).share_show_concerns is False


# ---------------------------------------------------------------- preview == public
def test_preview_matches_public_output_off_and_on(client):
    from web.app.routes.share import _og_svg
    rid, sheet = _new_share(client, 9)
    tok = _row(rid).share_token
    anon = TestClient(app)

    # OFF: preview shows the fits, no concerns, and so does the public page.
    page = anon.get(f"/m/{tok}").text
    assert _bullets(sheet, "good") == _bullets(page, "good") != []
    assert _bullets(sheet, "bad") == _bullets(page, "bad") == []
    assert "Your card will show" in sheet

    # ON: the sheet re-renders with the concerns, identical to page bullets.
    sheet = client.post(f"/job/{rid}/share", data={
        "source": "matches", "prefs": "1", "show_concerns": "1"}).text
    page = anon.get(f"/m/{tok}").text
    assert _bullets(sheet, "good") == _bullets(page, "good")
    assert _bullets(sheet, "bad") == _bullets(page, "bad") != []
    # Every previewed bullet is the text the PNG draws too (XML-escaped there).
    import html as _h
    svg = _og_svg(_row(rid))
    for b in _bullets(sheet, "good") + _bullets(sheet, "bad"):
        assert _h.escape(_h.unescape(b)) in svg
