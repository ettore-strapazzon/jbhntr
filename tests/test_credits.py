"""Credit ledger tests (Guide v3.0 §18, items 1–8)."""

import pytest


def _fresh_user(db, email):
    from web.app.models import User
    u = User(email=email, password_hash="x")
    db.add(u)
    db.commit()
    return u


@pytest.fixture()
def db():
    from web.app.db import SessionLocal, init_db
    init_db()
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def test_balance_is_sum_of_deltas(db):
    from web.app.services import credits
    u = _fresh_user(db, "sum@example.com")
    credits.grant(db, u, 10, "signup_grant", idempotency_key=f"signup:{u.id}")
    credits.debit(db, u, 2, "search", idempotency_key="search:1")
    credits.debit(db, u, 3, "doc_cv", idempotency_key="doc:cv:1")
    assert credits.balance(db, u) == 5
    assert u.credit_balance == 5           # mirror matches projection


def test_debit_is_idempotent(db):
    from web.app.models import CreditLedger
    from web.app.services import credits
    u = _fresh_user(db, "idem@example.com")
    credits.grant(db, u, 10, "signup_grant", idempotency_key=f"signup:{u.id}")
    r1 = credits.debit(db, u, 2, "search", idempotency_key="search:42")
    r2 = credits.debit(db, u, 2, "search", idempotency_key="search:42")
    assert r1.id == r2.id                  # same row, charged once
    assert credits.balance(db, u) == 8
    assert db.query(CreditLedger).filter_by(idempotency_key="search:42").count() == 1


def test_debit_beyond_balance_raises_and_writes_nothing(db):
    from web.app.models import CreditLedger
    from web.app.services import credits
    from web.app.services.credits import InsufficientCredits
    u = _fresh_user(db, "poor@example.com")
    credits.grant(db, u, 1, "signup_grant", idempotency_key=f"signup:{u.id}")
    n_before = db.query(CreditLedger).filter_by(user_id=u.id).count()
    with pytest.raises(InsufficientCredits):
        credits.debit(db, u, 5, "search", idempotency_key="search:x")
    assert db.query(CreditLedger).filter_by(user_id=u.id).count() == n_before
    assert credits.balance(db, u) == 1


def test_refund_is_idempotent_per_row(db):
    from web.app.services import credits
    u = _fresh_user(db, "refund@example.com")
    credits.grant(db, u, 10, "signup_grant", idempotency_key=f"signup:{u.id}")
    d = credits.debit(db, u, 2, "search", idempotency_key="search:r")
    credits.refund(db, d)
    credits.refund(db, d)                  # second refund is a no-op
    assert credits.balance(db, u) == 10


def test_weekly_cap_blocks_capped_reasons_only(db):
    from web.app.config import config
    from web.app.services import credits
    u = _fresh_user(db, "cap@example.com")
    # Fill the weekly cap with outcome credits (each keyed uniquely).
    per = config.outcome_credits
    n = config.weekly_earn_cap // per
    for i in range(n):
        assert credits.grant(db, u, per, "outcome_report", ref_id=f"job{i}") is not None
    # The next capped grant is refused...
    assert credits.grant(db, u, per, "outcome_report", ref_id="jobX") is None
    # ...but referral and signup are exempt.
    assert credits.grant(db, u, config.referral_credits, "referral_activated",
                         idempotency_key="referral:1") is not None


def test_mirror_never_diverges_over_random_ops(db):
    import random
    from web.app.services import credits
    u = _fresh_user(db, "prop@example.com")
    credits.grant(db, u, 100, "signup_grant", idempotency_key=f"signup:{u.id}")
    for i in range(40):
        if random.random() < 0.5 and credits.balance(db, u) >= 3:
            credits.debit(db, u, 3, "search", idempotency_key=f"s:{i}")
        else:
            credits.grant(db, u, 5, "operator_adjustment", idempotency_key=f"g:{i}")
        assert u.credit_balance == credits.balance(db, u)


def test_backfill_is_idempotent(db):
    from web.app.config import config
    from web.app.models import CreditLedger
    from web.app.services import migrate_credits
    u = _fresh_user(db, "mig@example.com")
    migrate_credits.run(db)
    migrate_credits.run(db)                # twice
    rows = (db.query(CreditLedger)
            .filter_by(user_id=u.id, reason="signup_grant").all())
    assert len(rows) == 1                  # exactly one signup grant
    assert rows[0].delta == config.signup_grant_credits
    # no debit for historic usage
    assert not db.query(CreditLedger).filter(
        CreditLedger.user_id == u.id, CreditLedger.delta < 0).count()
