"""One-off operator tool: reset a single tester on the credit economy.

Run it on a box that can reach the database (locally against the dev DB, or on
Railway against production):

    python -m web.app.services.reset_usage e.strapazzon@gmail.com

It re-enables the free first scan (clears first_scan_used_at) and deletes that
user's generated documents so they can regenerate from scratch. It does NOT
change the credit balance (use the admin "Grant credits" tool for that), the
account, profile, uploaded materials, searches or results. Only the named user
is affected.
"""

from __future__ import annotations

import sys

from ..db import SessionLocal
from ..models import Document, User


def reset(email: str) -> str:
    """Reset one tester's free first scan + generated documents. Returns a
    human-readable result line."""
    email = (email or "").strip().lower()
    if not email:
        return "No email given — nothing changed."
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            return f"No user found with email {email!r} — nothing changed."
        had_free_scan = user.first_scan_used_at is not None
        deleted = (db.query(Document)
                   .filter(Document.user_id == user.id)
                   .delete(synchronize_session=False))
        user.first_scan_used_at = None      # first scan is on us again
        db.commit()
        return (f"Reset {email}: free first scan re-enabled"
                f"{' (was used)' if had_free_scan else ''}, "
                f"deleted {deleted} generated documents. Credit balance unchanged.")
    finally:
        db.close()


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m web.app.services.reset_usage <email>")
        raise SystemExit(2)
    print(reset(sys.argv[1]))


if __name__ == "__main__":
    main()
