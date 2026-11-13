"""R3-03 — /invite page.

Flag-gated (INVITE_PAGE, default off -> 404); signed-in user's code + link,
the six §3.5.6 messages with incentive disclosure, a live counter that reads the
DB, invite_page_viewed / invite_link_copied events, logged-out redirect, noindex,
and no other user's data on the page. Same throwaway-SQLite setup as
test_web.py. Every row this module adds is deleted at module teardown.
"""

import os
import sys
import tempfile
from urllib.parse import quote

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

from web.app.config import config  # noqa: E402
from web.app.main import app  # noqa: E402

PW = "Sup3rSecret!x"
PREFIX = "invr3"          # every account this module creates: invr3-*@example.com


def _db():
    from web.app.db import SessionLocal
    return SessionLocal()


@pytest.fixture(autouse=True, scope="module")
def _cleanup_module_rows():
    """The suite shares one DB: delete every row this module created (all
    user_id-keyed rows of our accounts, then the accounts)."""
    with TestClient(app):          # runs lifespan -> init_db() on a fresh DB
        yield
    from web.app.models import Base, ReferralReward
    from web.app.models import User
    db = _db()
    try:
        ids = [u.id for u in db.query(User).filter(User.email.like(f"{PREFIX}-%@example.com"))]
        if ids:
            db.query(ReferralReward).filter(
                ReferralReward.inviter_id.in_(ids) | ReferralReward.friend_id.in_(ids)
            ).delete(synchronize_session=False)
            for table in reversed(Base.metadata.sorted_tables):
                if table.name != "users" and "user_id" in table.c:
                    db.execute(table.delete().where(table.c.user_id.in_(ids)))
            db.query(User).filter(User.referred_by_user_id.in_(ids)).update(
                {User.referred_by_user_id: None}, synchronize_session=False)
            db.query(User).filter(User.id.in_(ids)).delete(synchronize_session=False)
            db.commit()
    finally:
        db.close()


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr(config, "invite_page", True)
    monkeypatch.setattr(config, "first_scan_free", True)


def _client():
    return TestClient(app)


def signup(client, name):
    email = f"{PREFIX}-{name}@example.com"
    r = client.post("/signup", data={"email": email, "password": PW, "accept_tos": "1"},
                    follow_redirects=False)
    assert r.status_code in (302, 303), r.text
    return email


def _user(email):
    from web.app.models import User
    db = _db()
    try:
        return db.query(User).filter_by(email=email).one()
    finally:
        db.close()


def _events(name, user_id):
    from web.app.models import ProductEvent
    db = _db()
    try:
        return (db.query(ProductEvent)
                .filter(ProductEvent.name == name, ProductEvent.user_id == user_id).all())
    finally:
        db.close()


def _refer(inviter_email, friend_name, scanned=False, credited=False, status=None):
    """A friend signed up through the inviter's code. `scanned` = the friend ran a
    first scan (scan_completed event + the R3-11 ReferralReward row, 'pending');
    `credited` = the payout landed (the ledger row keyed referral:{friend_id}, the
    reward row 'paid'); `status` overrides the reward row's status (e.g. 'held').
    Written directly, not via the payout path, so this stays independent of the
    R3-11 delay/hold logic."""
    from web.app.models import ReferralReward, User
    from web.app.services import referral
    friend_email = signup(_client(), friend_name)
    db = _db()
    try:
        inviter = db.query(User).filter_by(email=inviter_email).one()
        code = referral.ensure_code(db, inviter)
        db.commit()
        friend = db.query(User).filter_by(email=friend_email).one()
        assert referral.attach_and_reward_friend(db, friend, code) is not None
        if scanned:
            from web.app.services.events import record
            record(db, "scan_completed", user_id=friend.id, count=3)
            db.add(ReferralReward(inviter_id=inviter.id, friend_id=friend.id,
                                  amount=config.referral_credits,
                                  status=status or ("paid" if credited else "pending")))
            db.commit()
        if credited:
            from web.app.services import credits
            credits.grant(db, inviter, config.referral_credits, "referral_activated",
                          idempotency_key=f"referral:{friend.id}")
            db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------- #
def test_flag_off_is_404_for_everyone(monkeypatch):
    monkeypatch.setattr(config, "invite_page", False)
    c = _client()
    assert c.get("/invite", follow_redirects=False).status_code == 404
    signup(c, "off")
    assert c.get("/invite", follow_redirects=False).status_code == 404
    assert c.post("/invite/copied", data={"channel": "link"}).status_code == 404
    # No nav entry while the flag is off.
    assert 'href="/invite"' not in c.get("/credits").text


def test_flag_default_is_off():
    from web.app.config import WebConfig
    old = os.environ.pop("INVITE_PAGE", None)
    try:
        assert WebConfig().invite_page is False
    finally:
        if old is not None:
            os.environ["INVITE_PAGE"] = old


def test_logged_out_redirects_to_login(flag_on):
    r = _client().get("/invite", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    r = _client().post("/invite/copied", data={"channel": "link"}, follow_redirects=False)
    assert r.status_code == 303


def test_page_shows_code_link_messages_disclosure(flag_on):
    from web.app.services import referral
    c = _client()
    email = signup(c, "a")
    r = c.get("/invite")
    assert r.status_code == 200
    u = _user(email)
    link = referral.invite_url(u.referral_code)
    html = r.text

    # Code + link, noindex (meta + header), title.
    assert u.referral_code in html and link in html
    assert '<meta name="robots" content="noindex,nofollow">' in html
    assert "noindex" in r.headers.get("x-robots-tag", "")
    assert "<title>Invite friends · JBHNTR</title>" in html
    assert "Know someone applying to everything?" in html
    assert "Copy link" in html and "Copy code" in html

    # Numbers from config, not hard-coded.
    fc, ic = config.referral_friend_credits, config.referral_credits
    assert (f"Your friend gets {fc} bonus credits. You get {ic} for every friend "
            "who runs their first scan and starts using their results. No fixed limit.") in html
    assert f"your friend can type {link.split('://', 1)[1]} into their browser" in html
    assert "activated" not in html.lower()                       # IN4
    assert f"You get {ic} credits." in html

    # Fine print: no cash value / held / disclose publicly.
    assert "they have no cash value and can't be sold," in html
    assert "we review the extra ones by hand" in html
    assert "say that you earn credits from" in html

    # Six channel messages, each with the link and an incentive disclosure.
    msgs = __import__("web.app.routes.invite", fromlist=["x"]).channel_messages(link)
    assert [m["channel"] for m in msgs] == ["whatsapp", "linkedin", "email", "x",
                                            "bluesky", "slack_teams"]
    for m in msgs:
        assert link in m["message"]
        low = m["message"].lower()
        assert "disclosure" in low and "credits" in low
        assert 'id="msg-%s"' % m["channel"] in html
    # Verbatim spot-checks with config numbers filled.
    assert f"my link adds {fc} bonus credits. Full disclosure, I get credits too" in msgs[1]["message"]
    assert f"Full disclosure: I get {ic} credits if you sign up and run a scan." in msgs[2]["message"]
    # Share intents carry the URL-encoded message.
    assert f"https://wa.me/?text={quote(msgs[0]['message'], safe='')}" in msgs[0]["href"]
    assert msgs[2]["href"].startswith("mailto:?subject=A%20job-search%20tool")
    assert "https://bsky.app/intent/compose?text=" in html
    assert "https://twitter.com/intent/tweet?text=" in html
    # CSP: no inline handlers, JS from a static file.
    assert "onclick" not in html and "/static/invite.js" in html


def test_page_view_and_copy_events(flag_on):
    c = _client()
    uid = _user(signup(c, "ev")).id
    c.get("/invite"); c.get("/invite")
    assert len(_events("invite_page_viewed", uid)) == 2          # one per load
    assert c.post("/invite/copied", data={"channel": "whatsapp"}).status_code == 204
    assert c.post("/invite/copied", data={"channel": "x", "source": "intent"}).status_code == 204
    assert c.post("/invite/copied", data={"channel": "evil"}).status_code == 422
    ev = _events("invite_link_copied", uid)
    assert sorted((e.properties["channel"], e.properties["source"]) for e in ev) == [
        ("whatsapp", "copy"), ("x", "intent")]


def test_counter_zero_then_signed_up_then_activated(flag_on):
    c = _client()
    email = signup(c, "cnt")
    assert "No invites yet." in c.get("/invite").text

    _refer(email, "cnt-f1")
    html = c.get("/invite").text
    assert "0 friends credited · +0 credits earned" in html
    assert "1 signed up with your link · waiting for their first scan" in html
    assert "waiting for checks" not in html

    _refer(email, "cnt-f2", scanned=True)                  # scanned, not yet paid
    html = c.get("/invite").text
    assert "0 friends credited · +0 credits earned" in html
    assert "2 signed up with your link</p>" in html
    assert "1 waiting for checks. Credits arrive two to three days" in html

    _refer(email, "cnt-f3", scanned=True, credited=True)   # paid out
    html = c.get("/invite").text
    assert f"1 friend credited · +{config.referral_credits} credits earned" in html
    assert "3 signed up with your link</p>" in html
    assert "1 waiting for checks." in html
    assert "activated" not in html.lower()


def test_counter_pending_reads_reward_rows_not_events(flag_on):
    """GC E-3: "waiting for checks" counts ReferralReward rows in pending+held,
    so a scan event whose reward insert failed shows nothing as waiting, and a
    held reward still counts as waiting."""
    from web.app.models import ReferralReward
    from web.app.routes.invite import counter
    c = _client()
    email = signup(c, "e3")
    _refer(email, "e3-f1", scanned=True)                     # pending row
    _refer(email, "e3-f2", scanned=True, status="held")      # held row
    _refer(email, "e3-f3", scanned=True, credited=True)      # paid row
    f4 = _user(signup(_client(), "e3-f4"))                   # event, no reward row
    db = _db()
    try:
        from web.app.services import referral
        from web.app.services.events import record
        me = _user(email)
        assert referral.attach_and_reward_friend(db, db.get(type(me), f4.id),
                                                 me.referral_code) is not None
        record(db, "scan_completed", user_id=f4.id, count=3)
        rows = db.query(ReferralReward).filter(
            ReferralReward.inviter_id == me.id,
            ReferralReward.status.in_(("pending", "held"))).count()
        got = counter(db, me)
    finally:
        db.close()
    assert rows == 2
    assert got["pending"] == rows
    assert got["signed_up"] == 4 and got["credited"] == 1
    assert "2 waiting for checks." in c.get("/invite").text


def test_no_other_users_data(flag_on):
    from web.app.services import referral
    other = signup(_client(), "other")
    _refer(other, "other-f1", scanned=True, credited=True)
    o = _user(other)

    c = _client()
    signup(c, "me")
    html = c.get("/invite").text
    assert o.referral_code not in html
    assert referral.invite_url(o.referral_code) not in html
    assert "No invites yet." in html                 # other's friend not counted
    assert "@example.com" not in html                # no emails of anyone


def test_first_scan_free_off_drops_those_sentences(flag_on, monkeypatch):
    monkeypatch.setattr(config, "first_scan_free", False)
    from web.app.routes.invite import channel_messages
    c = _client()
    signup(c, "nofree")
    html = c.get("/invite").text
    assert "first scan is free" not in html.lower()
    for m in channel_messages("https://x.test/signup?ref=AB"):
        assert "first scan is free" not in m["message"].lower()
        assert "https://x.test/signup?ref=AB" in m["message"]      # link survives
        assert "disclosure" in m["message"].lower()
