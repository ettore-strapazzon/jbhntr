"""R3-14 gate prompt — "Compared with how you search for jobs today, this
shortlist is: much better / better / about the same / worse".

Rules under test (services/gate.py):

* Shown only after the user has REVIEWED their first scan: a completed
  (non-import) scan with >=1 result AND a first triage action (save / dismiss /
  applied / rating event, or any JobState row — referral.has_triaged's rule).
* One answer per user, ever: a unique row per user; a second POST is 409.
* "Not now" hides it; it is re-asked once, no sooner than REASK_AFTER later;
  a second "not now" means never again.
* POSTs need the logged-in session AND the per-session CSRF token.
* Events: gate_prompt_shown (once per ask, n=1|2), gate_prompt_answered
  (answer=...), gate_prompt_dismissed (n=...).
"""

import os
import tempfile
import uuid
from datetime import timedelta

os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/test_gate.sqlite")
os.environ.setdefault("SECRET_KEY", "x" * 48)
if not os.environ.get("FILE_ENCRYPTION_KEY"):
    from cryptography.fernet import Fernet
    os.environ["FILE_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ.setdefault("DEBUG", "true")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from web.app.main import app  # noqa: E402

PREFIX = "gate+"
MARK = 'id="gate-prompt"'


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True, scope="module")
def _cleanup_module_rows():
    """Shared suite DB: remove every row this module created."""
    yield
    from web.app.db import SessionLocal
    from web.app.models import (CreditLedger, GateAnswer, JobResult, JobState,
                                ProductEvent, Profile, Search, Session, User)
    db = SessionLocal()
    try:
        ids = [u.id for u in db.query(User).filter(User.email.like(f"{PREFIX}%"))]
        if ids:
            for model in (GateAnswer, ProductEvent, JobState, JobResult, Search,
                          CreditLedger, Session, Profile):
                db.query(model).filter(model.user_id.in_(ids)).delete(
                    synchronize_session=False)
            db.query(User).filter(User.id.in_(ids)).delete(synchronize_session=False)
            db.commit()
    finally:
        db.close()


# ----------------------------------------------------------------- helpers --
def _signup(client) -> int:
    email = f"{PREFIX}{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/signup", data={"email": email, "password": "Sup3rSecret!x",
                                     "accept_tos": "1"}, follow_redirects=False)
    assert r.status_code in (302, 303)
    from web.app.db import SessionLocal
    from web.app.models import User
    db = SessionLocal()
    try:
        return db.query(User).filter_by(email=email).one().id
    finally:
        db.close()


def _scan(uid, *, status="done", stage="Done", results=1):
    from web.app.db import SessionLocal
    from web.app.models import JobResult, Search
    db = SessionLocal()
    try:
        s = Search(user_id=uid, status=status, stage=stage)
        db.add(s)
        db.flush()
        for i in range(results):
            db.add(JobResult(search_id=s.id, user_id=uid, position=i + 1,
                             short_id=uuid.uuid4().hex[:8], dedup_key=uuid.uuid4().hex,
                             title="Data Lead", company="Acme", score=80, tier=2))
        db.commit()
    finally:
        db.close()


def _triage(uid, name="job_saved"):
    from web.app.db import SessionLocal
    from web.app.services.events import record
    db = SessionLocal()
    try:
        record(db, name, uid)
    finally:
        db.close()


def _reviewed_user(client) -> int:
    uid = _signup(client)
    _scan(uid)
    _triage(uid)
    return uid


def _csrf(client) -> str:
    from web.app.auth import COOKIE
    from web.app.security import csrf_token
    return csrf_token(client.cookies.get(COOKIE))


def _events(uid, name):
    from web.app.db import SessionLocal
    from web.app.models import ProductEvent
    db = SessionLocal()
    try:
        return [e.properties for e in db.query(ProductEvent)
                .filter_by(user_id=uid, name=name).order_by(ProductEvent.id)]
    finally:
        db.close()


def _row(uid):
    from web.app.db import SessionLocal
    from web.app.models import GateAnswer
    db = SessionLocal()
    try:
        return db.query(GateAnswer).filter_by(user_id=uid).one_or_none()
    finally:
        db.close()


def _age_dismissal(uid, days):
    from web.app.db import SessionLocal
    from web.app.models import GateAnswer, utcnow
    db = SessionLocal()
    try:
        row = db.query(GateAnswer).filter_by(user_id=uid).one()
        row.dismissed_at = utcnow() - timedelta(days=days)
        db.commit()
    finally:
        db.close()


# ------------------------------------------------- shown only after review --
def test_not_shown_before_any_scan(client):
    _signup(client)
    assert MARK not in client.get("/matches").text


def test_not_shown_after_scan_without_a_triage_action(client):
    uid = _signup(client)
    _scan(uid)
    assert MARK not in client.get("/matches").text
    assert _row(uid) is None and _events(uid, "gate_prompt_shown") == []


def test_not_shown_for_triage_on_an_imported_job_only(client):
    uid = _signup(client)
    _scan(uid, stage="Imported job")
    _triage(uid)
    assert MARK not in client.get("/matches").text


def test_not_shown_while_first_scan_is_still_running(client):
    uid = _signup(client)
    _scan(uid, status="running", stage="Scoring", results=0)
    _triage(uid)
    assert MARK not in client.get("/matches").text


def test_shown_after_first_scan_reviewed_with_all_four_options(client):
    uid = _reviewed_user(client)
    html = client.get("/matches").text
    assert MARK in html
    assert "Compared with how you search for jobs today" in html
    for value, label in (("much_better", "Much better"), ("better", "Better"),
                         ("same", "About the same"), ("worse", "Worse")):
        assert f'value="{value}"' in html and label in html
    assert "Not now" in html
    assert f'name="csrf" value="{_csrf(client)}"' in html
    # CSP: no inline script / handler in the prompt markup
    block = html[html.index(MARK):]
    block = block[:block.index("</section>")]
    assert "<script>" not in block and "onclick" not in block
    assert _events(uid, "gate_prompt_shown") == [{"n": 1}]


def test_any_triage_kind_counts_as_review(client):
    uid = _signup(client)
    _scan(uid)
    _triage(uid, "match_rated")
    assert MARK in client.get("/matches").text


def test_shown_event_once_per_ask_not_per_page_load(client):
    uid = _reviewed_user(client)
    client.get("/matches")
    client.get("/matches")
    assert _events(uid, "gate_prompt_shown") == [{"n": 1}]


# ------------------------------------------------------- answer persisted --
def test_answer_is_persisted_and_emits_event(client):
    uid = _reviewed_user(client)
    client.get("/matches")
    r = client.post("/gate", data={"answer": "much_better", "csrf": _csrf(client)},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/matches"
    row = _row(uid)
    assert row.answer == "much_better" and row.answered_at is not None
    assert _events(uid, "gate_prompt_answered") == [{"answer": "much_better"}]
    assert MARK not in client.get("/matches").text      # once answered, never again


def test_htmx_answer_returns_a_thank_you_fragment(client):
    _reviewed_user(client)
    client.get("/matches")
    r = client.post("/gate", data={"answer": "same", "csrf": _csrf(client)},
                    headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "Thank you" in r.text and 'role="status"' in r.text


def test_double_submit_is_rejected_and_first_answer_kept(client):
    uid = _reviewed_user(client)
    client.get("/matches")
    tok = _csrf(client)
    assert client.post("/gate", data={"answer": "worse", "csrf": tok},
                       follow_redirects=False).status_code == 303
    r = client.post("/gate", data={"answer": "much_better", "csrf": tok},
                    follow_redirects=False)
    assert r.status_code == 409
    assert _row(uid).answer == "worse"
    assert len(_events(uid, "gate_prompt_answered")) == 1


def test_unknown_answer_is_rejected(client):
    uid = _reviewed_user(client)
    client.get("/matches")
    r = client.post("/gate", data={"answer": "amazing", "csrf": _csrf(client)},
                    follow_redirects=False)
    assert r.status_code == 400 and _row(uid).answer is None


def test_cannot_answer_before_being_asked(client):
    uid = _signup(client)            # no scan, no triage -> never shown
    r = client.post("/gate", data={"answer": "better", "csrf": _csrf(client)},
                    follow_redirects=False)
    assert r.status_code == 409 and _row(uid) is None


# ------------------------------------------------------------ CSRF / auth --
def test_post_requires_login(client):
    client.cookies.clear()
    r = client.post("/gate", data={"answer": "better", "csrf": "x"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    r = client.post("/gate/dismiss", data={"csrf": "x"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_post_requires_valid_csrf_token(client):
    uid = _reviewed_user(client)
    client.get("/matches")
    for data in ({"answer": "better"}, {"answer": "better", "csrf": "forged"}):
        r = client.post("/gate", data=data, follow_redirects=False)
        assert r.status_code == 403
    assert client.post("/gate/dismiss", data={"csrf": "forged"},
                       follow_redirects=False).status_code == 403
    row = _row(uid)
    assert row.answer is None and row.dismiss_count == 0


def test_csrf_token_is_bound_to_the_session(client):
    _reviewed_user(client)
    client.get("/matches")
    stale = _csrf(client)
    client.cookies.clear()
    _reviewed_user(client)           # a different user / session
    client.get("/matches")
    r = client.post("/gate", data={"answer": "better", "csrf": stale},
                    follow_redirects=False)
    assert r.status_code == 403


# ------------------------------------------------------------- not now --
def test_not_now_hides_then_reasks_once_after_the_wait(client):
    uid = _reviewed_user(client)
    client.get("/matches")
    r = client.post("/gate/dismiss", data={"csrf": _csrf(client)}, follow_redirects=False)
    assert r.status_code == 303
    assert MARK not in client.get("/matches").text            # hidden right away
    assert _events(uid, "gate_prompt_dismissed") == [{"n": 1}]

    _age_dismissal(uid, days=2)                               # too soon
    assert MARK not in client.get("/matches").text
    _age_dismissal(uid, days=4)                               # past REASK_AFTER
    assert MARK in client.get("/matches").text
    assert _events(uid, "gate_prompt_shown") == [{"n": 1}, {"n": 2}]

    client.post("/gate/dismiss", data={"csrf": _csrf(client)})
    _age_dismissal(uid, days=60)
    assert MARK not in client.get("/matches").text            # second "not now" = never
    assert _row(uid).dismiss_count == 2


def test_can_still_answer_on_the_reask(client):
    uid = _reviewed_user(client)
    client.get("/matches")
    client.post("/gate/dismiss", data={"csrf": _csrf(client)})
    _age_dismissal(uid, days=4)
    client.get("/matches")
    assert client.post("/gate", data={"answer": "better", "csrf": _csrf(client)},
                       follow_redirects=False).status_code == 303
    assert _row(uid).answer == "better"


def test_dismiss_after_answer_is_rejected(client):
    uid = _reviewed_user(client)
    client.get("/matches")
    client.post("/gate", data={"answer": "better", "csrf": _csrf(client)})
    r = client.post("/gate/dismiss", data={"csrf": _csrf(client)}, follow_redirects=False)
    assert r.status_code == 409 and _row(uid).dismiss_count == 0


def test_kill_switch_hides_prompt(client, monkeypatch):
    from web.app.config import config
    monkeypatch.setattr(config, "gate_prompt", False, raising=False)
    uid = _reviewed_user(client)
    assert MARK not in client.get("/matches").text and _row(uid) is None


# ----------------------------------------------------------- unique row --
def test_one_row_per_user_is_enforced_by_the_database():
    from sqlalchemy.exc import IntegrityError

    from web.app.db import SessionLocal
    from web.app.models import GateAnswer, User
    db = SessionLocal()
    try:
        u = User(email=f"{PREFIX}{uuid.uuid4().hex[:10]}@example.com")
        db.add(u)
        db.flush()
        db.add(GateAnswer(user_id=u.id))
        db.commit()
        db.add(GateAnswer(user_id=u.id))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()


# ------------------------------------------ R3-18: also on /applications --
# Same prompt on My Jobs after the user's first save, under the SAME
# once-per-user rule: one GateAnswer row, one eligibility function
# (gate.prompt_for), so answering or exhausting "not now" on either page
# suppresses it on both. GateAnswer.surface records where it was answered.
APPS = "/applications"


def test_my_jobs_shows_prompt_after_first_save(client):
    uid = _reviewed_user(client)             # completed scan + job_saved
    html = client.get(APPS).text
    assert html.count(MARK) == 1             # never twice in one page load
    assert "Compared with how you search for jobs today" in html
    assert 'name="surface" value="applications"' in html
    assert f'name="csrf" value="{_csrf(client)}"' in html
    assert _events(uid, "gate_prompt_shown") == [{"n": 1}]


def test_my_jobs_counts_a_saved_job_state_without_an_event(client):
    from web.app.db import SessionLocal
    from web.app.models import JobState
    uid = _signup(client)
    _scan(uid)
    db = SessionLocal()
    try:
        db.add(JobState(user_id=uid, dedup_key=uuid.uuid4().hex, saved=True))
        db.commit()
    finally:
        db.close()
    assert MARK in client.get(APPS).text


def test_my_jobs_hides_prompt_before_any_save(client):
    uid = _signup(client)
    _scan(uid)
    assert MARK not in client.get(APPS).text
    _triage(uid, "job_dismissed")            # triaged, but nothing saved yet
    assert MARK not in client.get(APPS).text
    assert _row(uid) is None and _events(uid, "gate_prompt_shown") == []


def test_my_jobs_hides_prompt_for_a_save_without_a_real_scan(client):
    uid = _signup(client)
    _scan(uid, stage="Imported job")         # only an imported job, no shortlist
    _triage(uid, "job_saved")
    assert MARK not in client.get(APPS).text


def test_my_jobs_hides_prompt_once_answered_on_matches(client):
    uid = _reviewed_user(client)
    assert MARK in client.get("/matches").text
    r = client.post("/gate", data={"answer": "better", "csrf": _csrf(client)},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/matches"
    assert _row(uid).surface == "matches"
    assert MARK not in client.get(APPS).text


def test_answer_on_my_jobs_records_surface_and_hides_on_matches(client):
    uid = _reviewed_user(client)
    client.get(APPS)
    r = client.post("/gate", data={"answer": "much_better", "surface": "applications",
                                   "csrf": _csrf(client)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == APPS
    row = _row(uid)
    assert row.answer == "much_better" and row.surface == "applications"
    assert MARK not in client.get("/matches").text
    assert MARK not in client.get(APPS).text


def test_unknown_surface_falls_back_to_matches(client):
    uid = _reviewed_user(client)
    client.get(APPS)
    r = client.post("/gate", data={"answer": "same", "surface": "https://evil.example",
                                   "csrf": _csrf(client)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/matches"
    assert _row(uid).surface == "matches"


def test_my_jobs_respects_kill_switch(client, monkeypatch):
    from web.app.config import config
    monkeypatch.setattr(config, "gate_prompt", False, raising=False)
    uid = _reviewed_user(client)
    assert MARK not in client.get(APPS).text and _row(uid) is None


def test_shown_event_is_shared_across_both_pages(client):
    uid = _reviewed_user(client)
    client.get("/matches")
    client.get(APPS)
    assert _events(uid, "gate_prompt_shown") == [{"n": 1}]


def test_not_now_cadence_is_shared_across_both_pages(client):
    uid = _reviewed_user(client)
    assert MARK in client.get("/matches").text
    r = client.post("/gate/dismiss", data={"surface": "applications", "csrf": _csrf(client)},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == APPS
    assert MARK not in client.get(APPS).text           # hidden on both right away
    assert MARK not in client.get("/matches").text

    _age_dismissal(uid, days=2)                        # too soon on either page
    assert MARK not in client.get(APPS).text
    _age_dismissal(uid, days=4)                        # the one re-ask, on My Jobs
    assert MARK in client.get(APPS).text
    assert MARK in client.get("/matches").text         # same ask, not a third
    assert _events(uid, "gate_prompt_shown") == [{"n": 1}, {"n": 2}]

    client.post("/gate/dismiss", data={"csrf": _csrf(client)})   # 2nd not-now on /matches
    _age_dismissal(uid, days=60)
    assert MARK not in client.get(APPS).text           # never again, on either
    assert MARK not in client.get("/matches").text
    assert _row(uid).dismiss_count == 2
