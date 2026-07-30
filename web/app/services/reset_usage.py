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
from ..models import Document, User


def reset(email: str) -> bool:
    email = (email or "").strip().lower()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"No user found with email {email!r} — nothing changed.")
            return False
        before_s, before_d = user.searches_used, user.documents_used
        deleted = (db.query(Document)
                   .filter(Document.user_id == user.id)
                   .delete(synchronize_session=False))
        user.searches_used = 0
        user.documents_used = 0
        db.commit()
        print(f"Reset {email}: searches_used {before_s} -> 0, "
              f"documents_used {before_d} -> 0, deleted {deleted} generated documents. "
              f"Free searches and CV/cover-letter allowance are fresh.")
        return True
    finally:
        db.close()


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m web.app.services.reset_usage <email>")
        raise SystemExit(2)
    reset(sys.argv[1])


if __name__ == "__main__":
    main()
