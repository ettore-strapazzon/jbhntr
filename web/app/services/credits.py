"""The credit economy's single source of truth (Guide v3.0, LEDGER-03).

This is the ONLY module that writes credits. Balance is a projection of the
immutable `credit_ledger`; `User.credit_balance` is a denormalised mirror written
only here. Every mutation is one row + one mirror update in one transaction, keyed
on an idempotency key so a retry, a double-submit or a re-run worker charges once.

Design rules (spec §4.3):
  1. One transaction per write; balance_after computed from the projection.
  2. debit requires an explicit idempotency_key; a repeat returns the existing row.
  3. No negative balances — debit raises InsufficientCredits and writes nothing.
  4. Refunds are compensating rows keyed refund:{original_id}.
  5. Weekly earn cap on outcome/feedback grants only (referral + signup exempt).
  6. Never reads user.plan.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from ..config import config
from ..models import CreditLedger, OpsLog, User, utcnow

log = logging.getLogger("jbhntr.credits")

# Earn reasons that count against config.weekly_earn_cap. Referral and signup grants
# are deliberately uncapped (spec §10.5, D-1) and so are operator adjustments.
CAPPED_REASONS = {"outcome_report", "outcome_details", "product_feedback"}


class InsufficientCredits(Exception):
    """Raised by debit when the balance can't cover the amount. Writes nothing."""

    def __init__(self, needed: int, balance: int):
        self.needed = needed
        self.balance = balance
        super().__init__(f"needs {needed}, has {balance}")


def balance(db: DbSession, user: User) -> int:
    """Authoritative balance = SUM(delta) over the ledger."""
    return int(db.query(func.coalesce(func.sum(CreditLedger.delta), 0))
               .filter(CreditLedger.user_id == user.id).scalar() or 0)


def history(db: DbSession, user: User, limit: int = 50) -> list[CreditLedger]:
    return (db.query(CreditLedger).filter(CreditLedger.user_id == user.id)
            .order_by(CreditLedger.id.desc()).limit(limit).all())


def can_afford(db: DbSession, user: User, amount: int) -> bool:
    return balance(db, user) >= amount


def earned_this_week(db: DbSession, user: User) -> int:
    """Positive capped-reason grants in the trailing 7 days."""
    since = utcnow() - timedelta(days=7)
    return int(db.query(func.coalesce(func.sum(CreditLedger.delta), 0))
               .filter(CreditLedger.user_id == user.id,
                       CreditLedger.reason.in_(CAPPED_REASONS),
                       CreditLedger.delta > 0,
                       CreditLedger.created_at >= since).scalar() or 0)


def _write(db: DbSession, user: User, delta: int, reason: str, *,
           ref_type: str, ref_id: str, note: str, idempotency_key: str) -> CreditLedger:
    """Insert one ledger row + update the mirror, idempotently. On a key collision
    returns the existing row and changes nothing."""
    existing = (db.query(CreditLedger)
                .filter(CreditLedger.idempotency_key == idempotency_key).first())
    if existing is not None:
        return existing
    new_balance = balance(db, user) + delta      # from the projection, pre-insert
    row = CreditLedger(user_id=user.id, delta=delta, reason=reason,
                       balance_after=new_balance, ref_type=ref_type, ref_id=ref_id,
                       idempotency_key=idempotency_key, note=note)
    db.add(row)
    user.credit_balance = new_balance
    try:
        db.commit()
    except IntegrityError:                        # raced on the same key — idempotent
        db.rollback()
        return (db.query(CreditLedger)
                .filter(CreditLedger.idempotency_key == idempotency_key).first())
    return row


def grant(db: DbSession, user: User, amount: int, reason: str, *,
          ref_type: str = "", ref_id: str = "", note: str = "",
          idempotency_key: str | None = None) -> CreditLedger | None:
    """Add credits. Returns None (and logs) if a capped-reason grant would exceed
    the weekly earn cap."""
    if amount <= 0:
        return None
    if reason in CAPPED_REASONS and earned_this_week(db, user) + amount > config.weekly_earn_cap:
        db.add(OpsLog(kind="credit_cap",
                      detail=f"user {user.id}: {reason} +{amount} refused (weekly cap "
                             f"{config.weekly_earn_cap}, earned {earned_this_week(db, user)})"))
        db.commit()
        return None
    key = idempotency_key or f"{reason}:{user.id}:{ref_id or ''}"
    return _write(db, user, amount, reason, ref_type=ref_type, ref_id=ref_id,
                  note=note, idempotency_key=key)


def debit(db: DbSession, user: User, amount: int, reason: str, *,
          ref_type: str = "", ref_id: str = "", idempotency_key: str) -> CreditLedger:
    """Spend credits. Idempotent per key. Raises InsufficientCredits (writing
    nothing) when the balance can't cover a genuinely new charge."""
    if amount <= 0:
        raise ValueError("debit amount must be positive")
    existing = (db.query(CreditLedger)
                .filter(CreditLedger.idempotency_key == idempotency_key).first())
    if existing is not None:
        return existing                           # already charged — never double
    bal = balance(db, user)
    if bal < amount:
        raise InsufficientCredits(amount, bal)
    return _write(db, user, -amount, reason, ref_type=ref_type, ref_id=ref_id,
                  note="", idempotency_key=idempotency_key)


def refund(db: DbSession, ledger_row: CreditLedger,
           reason: str = "search_refund") -> CreditLedger | None:
    """Compensating row that reverses a debit, keyed to the original so a retried
    worker cannot double-refund. Only refunds an actual debit (delta < 0)."""
    if ledger_row is None or ledger_row.delta >= 0:
        return None
    user = db.get(User, ledger_row.user_id)
    if user is None:
        return None
    return _write(db, user, -ledger_row.delta, reason,
                  ref_type=ledger_row.ref_type, ref_id=ledger_row.ref_id,
                  note=f"refund of #{ledger_row.id}",
                  idempotency_key=f"refund:{ledger_row.id}")


def record(db: DbSession, user: User, reason: str, *,
           ref_type: str = "", ref_id: str = "", note: str = "") -> CreditLedger:
    """A zero-delta row, for a legible history (first free scan, free re-run)."""
    return _write(db, user, 0, reason, ref_type=ref_type, ref_id=ref_id, note=note,
                  idempotency_key=f"{reason}:{user.id}:{ref_id or utcnow().timestamp()}")
