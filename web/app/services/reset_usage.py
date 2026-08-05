"""One-off operator tool: reset a single user's free-tier usage.

Run it on a box that can reach the database (locally against the dev DB, or on
Railway against production):

    python -m web.app.services.reset_usage e.strapazzon@gmail.com

It sets searches_used and documents_used back to 0 and deletes that user's
generated documents, so the per-distinct-job free CV / cover-letter allowance
starts fresh. It does NOT touch the account, profile, uploaded materials,
searches or results. Only the named user is affected.
"""

from __future__ import annotations

import sys

from ..db import SessionLocal
from ..models import Document, User, utcnow


def reset(email: str) -> str:
    """Reset one user's free-tier usage. Returns a human-readable result line."""
    email = (email or "").strip().lower()
    if not email:
        return "No email given — nothing changed."
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            return f"No user found with email {email!r} — nothing changed."
        before_s, before_d = user.searches_used, user.documents_used
        deleted = (db.query(Document)
                   .filter(Document.user_id == user.id)
                   .delete(synchronize_session=False))
        user.searches_used = 0
        user.documents_used = 0
        # Also clear the premium daily fair-use cap: it only counts searches
        # started after this point, so the user can search again immediately.
        user.usage_reset_at = utcnow()
        db.commit()
        return (f"Reset {email}: searches_used {before_s} -> 0, "
                f"documents_used {before_d} -> 0, deleted {deleted} generated documents, "
                f"and cleared the daily search cap. Free and premium usage are fresh.")
    finally:
        db.close()


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m web.app.services.reset_usage <email>")
        raise SystemExit(2)
    print(reset(sys.argv[1]))


if __name__ == "__main__":
    main()
