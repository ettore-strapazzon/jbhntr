"""R3-11 — referral payout aligned with TERMS_DRAFT §6 / GTM §5.

The inviter's reward is never paid at the friend's activation. It is recorded
as a pending ReferralReward and released by an idempotent step (nightly cron +
opportunistic) once >= REFERRAL_PAYOUT_DELAY_HOURS (48) have passed AND the
friend has taken a first triage action (save / dismiss / applied / rating).
Past REFERRAL_MONTHLY_CEILING (25) rewards in a calendar month, further rewards
are held for an admin unlock. Every row this module adds is removed at teardown.
"""

import os
import sys
import tempfile
from datetime import timedelta

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

PREFIX = "r311-"
_n = [0]


@pytest.fixture(scope="module", autouse=True)
def _app_started():
    """Start the app once so init_db() has created every table (incl. the new
    referral_rewards) even when this module runs on its own."""
    with TestClient(app):
        yield


@pytest.fixture(autouse=True, scope="module")
def _cleanup_module_rows(_app_started):
    yield
    from web.app.db import SessionLocal
    from web.app.models import (CreditLedger, JobState, ProductEvent, Profile,
                                ReferralReward, User)
    db = SessionLocal()
    try:
        ids = [u.id for u in db.query(User).filter(User.email.like(f"{PREFIX}%"))]
        if ids:
            db.query(ReferralReward).filter(
                ReferralReward.inviter_id.in_(ids) | ReferralReward.friend_id.in_(ids)
            ).delete(synchronize_session=False)
            for model in (CreditLedger, ProductEvent, JobState, Profile):
                db.query(model).filter(model.user_id.in_(ids)).delete(
                    synchronize_session=False)
            db.query(User).filter(User.id.in_(ids)).delete(synchronize_session=False)
            db.commit()
    finally:
        db.close()


@pytest.fixture
def db():
    from web.app.db import SessionLocal
    s = SessionLocal()
    yield s
    s.close()


def _user(db, tag):
    from web.app.auth import create_user
    _n[0] += 1
    return create_user(db, f"{PREFIX}{tag}{_n[0]}@example.com")


def _pair(db):
    """An inviter and a referred friend. Returns (inviter, friend)."""
    from web.app.services import referral
    inviter = _user(db, "inv")
    friend = _user(db, "frd")
    assert referral.attach_and_reward_friend(db, friend, inviter.referral_code)
    return inviter, friend


def _bal(db, u):
    from web.app.services import credits
    return credits.balance(db, u)


def _reward(db, friend):
    from web.app.models import ReferralReward
    db.expire_all()
    return db.query(ReferralReward).filter_by(friend_id=friend.id).one()


def _age(db, friend, hours):
    """Backdate the friend's activation by `hours`."""
    from web.app.models import utcnow
    rw = _reward(db, friend)
    rw.activated_at = utcnow() - timedelta(hours=hours)
    db.commit()


def _triage(db, friend, name="job_saved"):
    from web.app.services.events import record
    record(db, name, user_id=friend.id)


# ------------------------------------------------------------- no immediate pay
def test_activation_does_not_pay_immediately(db):
    from web.app.services import referral
    inviter, friend = _pair(db)
    start = _bal(db, inviter)
    _triage(db, friend)                            # even with triage already done
    referral.reward_inviter_if_activated(db, friend)
    assert _bal(db, inviter) == start
    rw = _reward(db, friend)
    assert rw.status == "pending" and rw.inviter_id == inviter.id
    assert rw.amount > 0 and rw.released_at is None


def test_activation_is_idempotent_one_reward_row(db):
    from web.app.models import ReferralReward
    from web.app.services import referral
    inviter, friend = _pair(db)
    referral.reward_inviter_if_activated(db, friend)
    referral.reward_inviter_if_activated(db, friend)
    assert db.query(ReferralReward).filter_by(friend_id=friend.id).count() == 1


def test_non_referred_user_gets_no_reward_row(db):
    from web.app.models import ReferralReward
    from web.app.services import referral
    u = _user(db, "solo")
    referral.reward_inviter_if_activated(db, u)
    assert db.query(ReferralReward).filter_by(friend_id=u.id).count() == 0


# ------------------------------------------------------------- release rules
def test_no_release_before_48h_even_with_triage(db):
    from web.app.services import referral
    inviter, friend = _pair(db)
    start = _bal(db, inviter)
    referral.reward_inviter_if_activated(db, friend)
    _triage(db, friend)
    _age(db, friend, 47)
    referral.release_due(db)
    assert _bal(db, inviter) == start
    assert _reward(db, friend).status == "pending"


def test_no_release_after_48h_without_triage(db):
    from web.app.services import referral
    inviter, friend = _pair(db)
    start = _bal(db, inviter)
    referral.reward_inviter_if_activated(db, friend)
    _age(db, friend, 100)
    referral.release_due(db)
    assert _bal(db, inviter) == start
    assert _reward(db, friend).status == "pending"


@pytest.mark.parametrize("action", ["job_saved", "job_dismissed",
                                    "job_marked_applied", "match_rated"])
def test_release_after_48h_and_first_triage(db, action):
    from web.app.config import config
    from web.app.services import referral
    inviter, friend = _pair(db)
    start = _bal(db, inviter)
    referral.reward_inviter_if_activated(db, friend)
    _age(db, friend, 49)
    _triage(db, friend, action)
    assert referral.release_due(db) >= 1
    assert _bal(db, inviter) == start + config.referral_credits
    rw = _reward(db, friend)
    assert rw.status == "paid" and rw.released_at is not None


def test_triage_via_job_state_counts(db):
    """A saved/dismissed JobState is a triage action even if the event was lost."""
    from web.app.models import JobState
    from web.app.services import referral
    inviter, friend = _pair(db)
    referral.reward_inviter_if_activated(db, friend)
    _age(db, friend, 49)
    db.add(JobState(user_id=friend.id, dedup_key="dk-r311", saved=True)); db.commit()
    referral.release_due(db)
    assert _reward(db, friend).status == "paid"


def test_release_is_idempotent(db):
    from web.app.config import config
    from web.app.services import referral
    inviter, friend = _pair(db)
    start = _bal(db, inviter)
    referral.reward_inviter_if_activated(db, friend)
    _age(db, friend, 72)
    _triage(db, friend)
    referral.release_due(db)
    referral.release_due(db)
    referral.reward_inviter_if_activated(db, friend)   # a later scan
    referral.release_due(db)
    assert _bal(db, inviter) == start + config.referral_credits


def test_legacy_already_paid_friend_is_not_paid_twice(db):
    """A friend whose inviter was paid under the old immediate rule: the ledger
    key referral:{friend} already exists, so the new reward is marked paid."""
    from web.app.config import config
    from web.app.services import credits, referral
    inviter, friend = _pair(db)
    credits.grant(db, inviter, config.referral_credits, "referral_activated",
                  idempotency_key=f"referral:{friend.id}")
    paid = _bal(db, inviter)
    referral.reward_inviter_if_activated(db, friend)
    _age(db, friend, 72)
    _triage(db, friend)
    referral.release_due(db)
    assert _bal(db, inviter) == paid
    assert _reward(db, friend).status == "paid"


# ------------------------------------------------------------- monthly ceiling
def test_soft_ceiling_holds_beyond_limit_until_admin_unlock(db, monkeypatch):
    from web.app.config import config
    from web.app.services import referral
    monkeypatch.setattr(config, "referral_monthly_ceiling", 2)
    inviter = _user(db, "big")
    friends = []
    for _ in range(3):
        f = _user(db, "f")
        referral.attach_and_reward_friend(db, f, inviter.referral_code)
        referral.reward_inviter_if_activated(db, f)
        friends.append(f)
    statuses = [_reward(db, f).status for f in friends]
    assert statuses == ["pending", "pending", "held"]
    assert _reward(db, friends[2]).hold_reason == "monthly_ceiling"

    start = _bal(db, inviter)
    for f in friends:
        _age(db, f, 60)
        _triage(db, f)
    referral.release_due(db)
    assert _bal(db, inviter) == start + 2 * config.referral_credits   # held one waits
    assert _reward(db, friends[2]).status == "held"

    # Human unlock -> released by the next run (still subject to delay + triage).
    assert referral.unlock(db, _reward(db, friends[2]).id) is True
    referral.release_due(db)
    assert _bal(db, inviter) == start + 3 * config.referral_credits
    assert _reward(db, friends[2]).status == "paid"
    assert referral.unlock(db, _reward(db, friends[2]).id) is False   # not held


def test_ceiling_is_per_calendar_month(db, monkeypatch):
    from web.app.config import config
    from web.app.models import utcnow
    from web.app.services import referral
    monkeypatch.setattr(config, "referral_monthly_ceiling", 1)
    inviter = _user(db, "mo")
    f1 = _user(db, "f")
    referral.attach_and_reward_friend(db, f1, inviter.referral_code)
    referral.reward_inviter_if_activated(db, f1)
    # Move the first reward into last month: this month's count is 0 again.
    rw = _reward(db, f1)
    rw.activated_at = utcnow().replace(day=1) - timedelta(days=2)
    db.commit()
    f2 = _user(db, "f")
    referral.attach_and_reward_friend(db, f2, inviter.referral_code)
    referral.reward_inviter_if_activated(db, f2)
    assert _reward(db, f2).status == "pending"


def test_admin_hold_blocks_release_until_unlock(db):
    from web.app.services import referral
    inviter, friend = _pair(db)
    start = _bal(db, inviter)
    referral.reward_inviter_if_activated(db, friend)
    assert referral.hold(db, _reward(db, friend).id, "duplicate_suspect") is True
    _age(db, friend, 72)
    _triage(db, friend)
    referral.release_due(db)
    assert _bal(db, inviter) == start and _reward(db, friend).status == "held"
    referral.unlock(db, _reward(db, friend).id)
    referral.release_due(db)
    assert _reward(db, friend).status == "paid"
    assert referral.hold(db, _reward(db, friend).id) is False      # paid: no-op


# ------------------------------------------------------------- admin + cron
def test_admin_unlock_route_requires_admin(db):
    from web.app.services import referral
    inviter, friend = _pair(db)
    referral.reward_inviter_if_activated(db, friend)
    rid = _reward(db, friend).id
    r = TestClient(app).post("/admin/referral-unlock", data={"reward_id": rid},
                             follow_redirects=False)
    assert r.status_code in (401, 403, 404)
    assert _reward(db, friend).status == "pending"


def test_admin_unlock_route_unlocks_held(db, monkeypatch):
    from web.app.config import config
    from web.app.services import referral
    monkeypatch.setattr(config, "referral_monthly_ceiling", 0)   # everything held
    monkeypatch.setattr(config, "admin_token", "t0k3n-admin-r311")
    inviter, friend = _pair(db)
    referral.reward_inviter_if_activated(db, friend)
    rw = _reward(db, friend)
    assert rw.status == "held"
    c = TestClient(app)
    listed = c.get("/admin/referral-rewards", auth=("admin", "t0k3n-admin-r311"))
    assert listed.status_code == 200
    assert any(x["id"] == rw.id for x in listed.json()["held"])
    from web.app.routes.admin import admin_csrf_token
    r = c.post("/admin/referral-unlock",
               data={"reward_id": rw.id, "csrf": admin_csrf_token()},
               auth=("admin", "t0k3n-admin-r311"), follow_redirects=False)
    assert r.status_code == 303
    assert _reward(db, friend).status == "pending"


# ------------------------------------------- R3-15 / GC E-2: held-referral queue
ADMIN = ("admin", "t0k3n-admin-r315")


def _held_and_pending(db, monkeypatch):
    """One pending reward, then one held past the (zeroed) ceiling."""
    from web.app.config import config
    from web.app.services import referral
    _, f_pending = _pair(db)
    referral.reward_inviter_if_activated(db, f_pending)
    monkeypatch.setattr(config, "referral_monthly_ceiling", 0)
    inviter, f_held = _pair(db)
    referral.reward_inviter_if_activated(db, f_held)
    held, pending = _reward(db, f_held), _reward(db, f_pending)
    assert (held.status, pending.status) == ("held", "pending")
    return inviter, f_held, held, pending


def _row(html, rid):
    import re
    m = re.search(rf'<tr data-reward-id="{rid}">(.*?)</tr>', html, re.S)
    return m.group(1) if m else None


def test_admin_queue_renders_held_rows_only(db, monkeypatch):
    from web.app.config import config
    monkeypatch.setattr(config, "admin_token", ADMIN[1])
    inviter, f_held, held, pending = _held_and_pending(db, monkeypatch)
    html = TestClient(app).get("/admin", auth=ADMIN).text
    assert 'id="referral-held-queue"' in html
    row = _row(html, held.id)
    assert row is not None and _row(html, pending.id) is None
    assert f"/admin/users/{inviter.id}" in row and f"/admin/users/{f_held.id}" in row
    assert "monthly_ceiling" in row
    assert held.activated_at.strftime("%Y-%m-%d") in row       # created date
    assert held.held_at is not None                            # held date stamped
    assert inviter.email not in row and f_held.email not in row  # ids only, no PII


def test_admin_queue_buttons_post_to_unlock_and_hold_routes(db, monkeypatch):
    import re

    from web.app.config import config
    from web.app.routes.admin import admin_csrf_token
    monkeypatch.setattr(config, "admin_token", ADMIN[1])
    _, f_held, held, pending = _held_and_pending(db, monkeypatch)
    c = TestClient(app)
    html = c.get("/admin", auth=ADMIN).text
    row = _row(html, held.id)
    assert re.search(r'<form method="post" action="/admin/referral-unlock"', row)
    assert f'name="reward_id" value="{held.id}"' in row
    assert f'name="csrf" value="{admin_csrf_token()}"' in row
    queue = html[html.index('id="referral-held-queue"'):]
    assert re.search(r'<form method="post" action="/admin/referral-hold"', queue)
    assert queue.count(f'name="csrf" value="{admin_csrf_token()}"') >= 2
    # The buttons actually work end to end.
    tok = admin_csrf_token()
    r = c.post("/admin/referral-unlock", data={"reward_id": held.id, "csrf": tok},
               auth=ADMIN, follow_redirects=False)
    assert r.status_code == 303 and _reward(db, f_held).status == "pending"
    r = c.post("/admin/referral-hold",
               data={"reward_id": pending.id, "reason": "duplicate_suspect", "csrf": tok},
               auth=ADMIN, follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    from web.app.models import ReferralReward
    rw = db.get(ReferralReward, pending.id)
    assert (rw.status, rw.hold_reason) == ("held", "duplicate_suspect")
    assert rw.held_at is not None
    assert _row(c.get("/admin", auth=ADMIN).text, pending.id) is not None


def test_admin_queue_and_actions_forbidden_for_non_admin(db, monkeypatch):
    from web.app.config import config
    from web.app.routes.admin import admin_csrf_token
    monkeypatch.setattr(config, "admin_token", ADMIN[1])
    _, f_held, held, pending = _held_and_pending(db, monkeypatch)
    c = TestClient(app)
    for auth in (None, ("admin", "wrong")):
        page = c.get("/admin", auth=auth)
        assert page.status_code == 401 and 'referral-held-queue' not in page.text
        for path, rid in (("/admin/referral-unlock", held.id),
                          ("/admin/referral-hold", pending.id)):
            r = c.post(path, data={"reward_id": rid, "csrf": admin_csrf_token()},
                       auth=auth, follow_redirects=False)
            assert r.status_code == 401
    assert (_reward(db, f_held).status, pending.status) == ("held", "pending")


def test_admin_actions_reject_missing_csrf_and_cross_site(db, monkeypatch):
    """Basic-auth credentials ride along on a cross-site form POST, so the
    actions need their own CSRF proof: the HMAC token and a same-site origin."""
    from web.app.config import config
    from web.app.routes.admin import admin_csrf_token
    monkeypatch.setattr(config, "admin_token", ADMIN[1])
    _, f_held, held, _p = _held_and_pending(db, monkeypatch)
    c = TestClient(app)
    for data, headers in (
            ({"reward_id": held.id}, {}),                                  # no token
            ({"reward_id": held.id, "csrf": "forged"}, {}),                # bad token
            ({"reward_id": held.id, "csrf": admin_csrf_token()},
             {"Origin": "https://evil.example"}),                          # cross-origin
            ({"reward_id": held.id, "csrf": admin_csrf_token()},
             {"Sec-Fetch-Site": "cross-site"})):
        r = c.post("/admin/referral-unlock", data=data, headers=headers,
                   auth=ADMIN, follow_redirects=False)
        assert r.status_code == 403, (data, headers)
    assert _reward(db, f_held).status == "held"
    # Token is bound to the admin token: rotating ADMIN_TOKEN invalidates it.
    old = admin_csrf_token()
    monkeypatch.setattr(config, "admin_token", "rotated-r315")
    assert admin_csrf_token() != old


def test_nightly_cron_runs_release_stage(monkeypatch):
    from web.app.services import cron, referral
    called = {}
    monkeypatch.setattr(referral, "release_due", lambda db, **k: called.setdefault("n", 0))
    assert cron._release_referrals() == 0 and "n" in called
