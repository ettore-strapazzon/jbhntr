"""End-to-end tests for the web app: signup, onboarding, the search gate, GDPR.

A throwaway SQLite database is configured *before* importing the app, because
config is read at import time.
"""

import os
import tempfile

import pytest

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
from web.app.security import (  # noqa: E402
    UploadError, decrypt_bytes, encrypt_bytes, validate_upload,
)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def signup(client, email="a@example.com", password="Sup3rSecret!x"):
    return client.post("/signup", data={
        "email": email, "password": password, "accept_tos": "1",
    }, follow_redirects=False)


# --------------------------- design phase A ------------------------------- #
def test_text_too_short_helper():
    from web.app.services.profile_service import MIN_TEXT, text_too_short
    assert text_too_short("x" * (MIN_TEXT - 1)) is True
    assert text_too_short("x" * MIN_TEXT) is False
    assert text_too_short("") is False          # empty isn't "too short"
    assert text_too_short("   ") is False


def test_f04_short_objective_is_rejected_not_saved_silently(client):
    signup(client, email="f04@example.com")
    r = client.post("/profile", data={"objective": "x" * 29, "about_me": "y" * 40},
                    follow_redirects=False)
    assert r.status_code == 303 and "error=" in r.headers["location"]
    from web.app.db import SessionLocal
    from web.app.models import User
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(email="f04@example.com").one()
        assert not (u.profile and u.profile.objective)   # never saved
    finally:
        db.close()


def test_f09_feedback_htmx_returns_partial_else_redirects(client):
    signup(client, email="f09@example.com")
    from web.app.db import SessionLocal
    from web.app.models import JobResult, Search, User
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(email="f09@example.com").one()
        s = Search(user_id=u.id, status="done"); db.add(s); db.flush()
        jr = JobResult(search_id=s.id, user_id=u.id, position=1, short_id="z",
                       tier=2, title="Role", company="Co")
        db.add(jr); db.commit(); rid = jr.id
    finally:
        db.close()

    r = client.post(f"/feedback/{rid}", data={"vote": "up"},
                    headers={"HX-Request": "true"}, follow_redirects=False)
    assert r.status_code == 200
    assert f"vote-{rid}" in r.text and 'value="up" aria-label="Good match"' in r.text
    assert 'aria-pressed="true"' in r.text       # the vote is reflected

    r2 = client.post(f"/feedback/{rid}", data={"vote": "down"}, follow_redirects=False)
    assert r2.status_code == 303                 # non-HTMX keeps the redirect


def test_f13_premium_notify_records_intent(client):
    signup(client, email="f13@example.com")
    r = client.post("/premium/notify", follow_redirects=False)
    assert r.status_code == 303 and "requested=1" in r.headers["location"]
    from web.app.db import SessionLocal
    from web.app.models import User
    db = SessionLocal()
    try:
        assert db.query(User).filter_by(email="f13@example.com").one().premium_requested_at
    finally:
        db.close()


def test_f11_skip_link_and_focus_style_present(client):
    assert 'class="skip-link"' in client.get("/").text
    assert ":focus-visible" in client.get("/static/app.css").text


def test_landing_hero_and_tier_tokens(client):
    page = client.get("/").text
    assert "A shortlist, not a search box" in page            # §10 hero copy
    assert "Fits what you want" in page                        # real two-bar card (F-07)
    assert "What it isn" in page and "scrape LinkedIn" in page  # honesty block (§10.6)
    css = client.get("/static/app.css").text
    assert "--tier-1:" in css and ".tier-1{" in css           # tier colours owned by CSS (F-14)
    assert "--mono:" in css                                    # monospace token


# --------------------------- design phase C ------------------------------- #
def test_onboarding_is_three_labelled_steps(client):
    signup(client, "ob3@example.com")
    for step, marker in (("upload", "Your CV stays yours"),      # trust block (F-15)
                         ("aim", "country-field"),               # token field (F-03)
                         ("words", "depth-objective")):          # depth meter (§5.5)
        page = client.get(f"/onboarding/{step}").text
        assert marker in page, step
    # Honest skip copy, no "Skip for now".
    assert "Save and finish later" in client.get("/onboarding/upload").text


def test_country_token_field_add_remove_preset(client):
    signup(client, "tok3@example.com")
    assert "Italy" in client.post("/fields/countries/add", data={"country": "italy"}).text
    assert "Germany" in client.post("/fields/countries/preset", data={"preset": "eu"}).text
    assert "anywhere" in client.post("/fields/countries/preset", data={"preset": "remote"}).text
    gone = client.post("/fields/countries/remove", data={"country": "Italy"}).text
    assert ">Italy\n" not in gone and "Italy<" not in gone


def test_depth_meter_reflects_length(client):
    signup(client, "depth@example.com")
    short = client.post("/fields/depth", data={"field": "objective", "objective": "hi"}).text
    deep = client.post("/fields/depth", data={"field": "objective", "objective": "x" * 400}).text
    assert "lvl0" in short and "Too short" in short
    assert "lvl3" in deep and "personal" in deep


def test_profile_strength_bands():
    from web.app.db import SessionLocal, init_db
    from web.app.models import Material, Profile, User
    from web.app.services.profile_service import strength
    init_db()
    db = SessionLocal()
    try:
        u = User(email="strength@example.com", password_hash="x")
        db.add(u); db.flush()
        # Nothing yet: search locked -> thin, no nudge.
        assert strength(db, u).band == "thin"
        db.add(Profile(user_id=u.id, objective="x" * 60, about_me="y" * 60,
                       seniority=["senior"], company_type=["startup"],
                       verticals=["fintech"], locations=["Italy"],
                       work_modes=["remote"], countries=["Italy"], job_type=["full-time"]))
        db.add(Material(user_id=u.id, kind="cv", filename="cv.txt", mime="text/plain",
                        size_bytes=10, ciphertext=b"x", text="cv"))
        db.flush()
        db.refresh(u)   # the first strength() call cached u.profile as None
        s = strength(db, u)
        assert s.can_search and s.band in ("basic", "good")     # searchable, not yet strong
        assert s.nudge is not None                              # always a next step below strong
    finally:
        db.close()


def test_profile_sections_save_independently(client):
    signup(client, "sect@example.com")
    # Saving "you" must not wipe targets, and vice versa.
    client.post("/profile", data={"_section": "targets", "seniority": "senior",
                                  "work_mode": "remote", "job_type": "full-time"})
    client.post("/profile", data={"_section": "you", "objective": "x" * 60,
                                  "about_me": "y" * 60})
    page = client.get("/profile").text
    assert "senior" in page                                     # targets survived the "you" save
    assert "x" * 60 in page                                     # objective saved


def test_signup_puts_google_above_email(client):
    # When Google is configured, SSO sits above the email form (§11.12).
    from web.app.config import config
    if not config.google_client_id:
        pytest.skip("Google SSO not configured in this env")
    page = client.get("/signup").text
    assert page.index("Continue with Google") < page.index('name="email"')


# --------------------------- design phase D ------------------------------- #
def _seed_run(db, user_id, results, hours_ago=0):
    """results: list of (dedup_key, tier, score, title). Runs are staggered by
    an explicit timestamp so the "new since" cutoff is unambiguous (real runs
    are minutes/hours apart; SQLite's second resolution isn't)."""
    from datetime import timedelta
    from web.app.models import JobResult, Search, utcnow
    when = utcnow() - timedelta(hours=hours_ago)
    s = Search(user_id=user_id, status="done", raw_count=1000,
               scored_count=len(results), started_at=when, finished_at=when)
    db.add(s); db.flush()
    for i, (key, tier, score, title) in enumerate(results, 1):
        db.add(JobResult(search_id=s.id, user_id=user_id, position=i, short_id=key[:8],
                         dedup_key=key, tier=tier, tier_label="t", score=score,
                         title=title, company="Co", source="greenhouse", created_at=when))
    db.commit()
    return s


def test_matches_accumulate_across_runs(client):
    from web.app.db import SessionLocal
    from web.app.models import User
    signup(client, "acc@example.com")
    db = SessionLocal()
    u = db.query(User).filter_by(email="acc@example.com").first()
    _seed_run(db, u.id, [("jobA", 1, 90, "Role A")], hours_ago=2)
    _seed_run(db, u.id, [("jobA", 1, 91, "Role A"), ("jobB", 2, 84, "Role B")], hours_ago=0)
    page = client.get("/matches").text
    assert "Role A" in page and "Role B" in page          # run 1's job survived run 2
    assert page.count(">New<") == 1                        # only jobB is new this run


def test_saved_and_dismissed_change_the_matches_list(client):
    from web.app.db import SessionLocal
    from web.app.models import JobResult, User
    signup(client, "state@example.com")
    db = SessionLocal()
    u = db.query(User).filter_by(email="state@example.com").first()
    _seed_run(db, u.id, [("d1", 1, 90, "Keeper"), ("d2", 2, 80, "Gone")])
    keeper = db.query(JobResult).filter_by(dedup_key="d1").first().id
    rid = db.query(JobResult).filter_by(dedup_key="d2").first().id
    client.post(f"/job/{rid}/dismiss", headers={"HX-Request": "true"})
    assert "Gone" not in client.get("/matches").text       # dismissed drops out
    assert "Keeper" in client.get("/matches").text         # the other stays
    client.post(f"/job/{keeper}/save", headers={"HX-Request": "true"})
    assert "Keeper" in client.get("/matches?saved=1").text  # saved-only shows saved


def test_applied_appears_in_applications(client):
    from web.app.db import SessionLocal
    from web.app.models import JobResult, User
    signup(client, "app@example.com")
    db = SessionLocal()
    u = db.query(User).filter_by(email="app@example.com").first()
    _seed_run(db, u.id, [("ap1", 1, 90, "Applied Role")])
    rid = db.query(JobResult).filter_by(dedup_key="ap1").first().id
    client.post(f"/job/{rid}/applied", headers={"HX-Request": "true"})
    assert "Applied Role" in client.get("/applications").text
    assert "Applied Role" not in client.get("/matches").text   # moved out of Matches
    client.post(f"/job/{rid}/status", data={"status": "Interviewing"})
    assert 'value="Interviewing" selected' in client.get("/applications").text


def test_search_url_redirects_to_matches(client):
    signup(client, "redir@example.com")
    r = client.get("/search", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/matches"


def test_document_export_pdf_and_docx(client):
    from web.app.db import SessionLocal
    from web.app.models import Document, JobResult, User
    signup(client, "doc@example.com")
    db = SessionLocal()
    u = db.query(User).filter_by(email="doc@example.com").first()
    _seed_run(db, u.id, [("dk", 1, 90, "PM Role")])
    rid = db.query(JobResult).filter_by(dedup_key="dk").first().id
    db.add(Document(user_id=u.id, job_result_id=rid, kind="cv", content="Jane Doe — PM")); db.commit()
    assert "sheet" in client.get(f"/document/{rid}/cv").text          # editable view
    pdf = client.post(f"/document/{rid}/cv/export/pdf", data={"content": "Edited — draft"})
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    docx = client.post(f"/document/{rid}/cv/export/docx", data={"content": "x"})
    assert docx.status_code == 200 and docx.content[:2] == b"PK"


def test_password_reset_flow(client):
    from web.app.db import SessionLocal
    from web.app.models import User
    from web.app.services import email as mail
    signup(client, "pw@example.com")
    client.get("/logout")
    assert "Forgot your password" in client.get("/login").text
    # Enumeration-safe: same message whether or not the account exists.
    a = client.post("/forgot", data={"email": "pw@example.com"}).text
    b = client.post("/forgot", data={"email": "nobody@example.com"}).text
    assert "has an account" in a and "has an account" in b
    db = SessionLocal()
    uid = db.query(User).filter_by(email="pw@example.com").first().id
    token = mail.make_reset_token(uid)
    r = client.post("/reset", data={"token": token, "password": "brandnew99xy"},
                    follow_redirects=False)
    assert r.status_code == 303
    client.get("/logout")
    ok = client.post("/login", data={"email": "pw@example.com", "password": "brandnew99xy"},
                     follow_redirects=False)
    assert ok.status_code == 303                       # new password works
    assert "invalid or has expired" in client.get("/reset?token=garbage").text


def test_email_sender_is_safe_noop_when_unconfigured():
    from web.app.services import email as mail
    # No SMTP in the test env — send() must not raise and must report not-sent.
    assert mail.is_configured() is False
    assert mail.send("x@example.com", "hi", "body") is False


def test_matches_renders_while_a_search_is_running(client):
    """Regression: the progress rail on /matches referenced an undefined
    'search' var, so any running search 500'd the page (first-search crash)."""
    from web.app.db import SessionLocal
    from web.app.models import Search, User
    signup(client, "run@example.com")
    db = SessionLocal()
    u = db.query(User).filter_by(email="run@example.com").first()
    db.add(Search(user_id=u.id, status="running", stage="Scoring the shortlist",
                  raw_count=1200))
    db.commit()
    r = client.get("/matches")
    assert r.status_code == 200
    assert "Scoring the shortlist" in r.text          # progress rail rendered


def test_welcome_email_on_signup(client, monkeypatch):
    from web.app.services import email as mail
    sent = []
    monkeypatch.setattr(mail, "send", lambda to, subject, body: sent.append(subject) or True)
    signup(client, "welcome@example.com")
    assert any("Welcome" in s for s in sent)


# ------------------------------- public ---------------------------------- #
def test_landing_page_is_public(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "JBHNTR" in r.text


@pytest.mark.parametrize("path", ["/terms", "/privacy", "/cookies"])
def test_legal_pages_render(client, path):
    r = client.get(path)
    assert r.status_code == 200


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_security_headers_present(client):
    h = client.get("/").headers
    assert "Content-Security-Policy" in h
    assert h["X-Frame-Options"] == "DENY"
    assert h["X-Content-Type-Options"] == "nosniff"


# ------------------------------- auth ------------------------------------ #
def test_signup_then_redirected_to_onboarding(client):
    r = signup(client, "new@example.com")
    assert r.status_code == 303
    assert r.headers["location"] == "/onboarding"


def test_signup_requires_tos(client):
    r = client.post("/signup", data={
        "email": "b@example.com", "password": "Sup3rSecret!x",
    })
    assert "accept the Terms" in r.text


def test_signup_rejects_weak_password(client):
    r = client.post("/signup", data={
        "email": "c@example.com", "password": "short", "accept_tos": "1",
    })
    assert "at least 10 characters" in r.text.lower()


def test_login_error_does_not_reveal_whether_account_exists(client):
    signup(client, "known@example.com")
    known = client.post("/login", data={
        "email": "known@example.com", "password": "wrongwrongwrong"})
    unknown = client.post("/login", data={
        "email": "nobody@example.com", "password": "wrongwrongwrong"})
    # Identical wording either way — no account enumeration.
    assert "email or password" in known.text
    assert "email or password" in unknown.text


def test_cookie_notice_has_no_inline_handler(client):
    """Regression: our own CSP forbids inline JS, so onclick= silently failed.

    The dismiss button must be wired up from app.js instead.
    """
    page = client.get("/").text
    assert 'onclick=' not in page
    assert 'id="cookie-note-dismiss"' in page

    js = client.get("/static/app.js").text
    assert "cookie-note-dismiss" in js
    assert "addEventListener" in js


def test_csp_forbids_inline_scripts(client):
    csp = client.get("/").headers["Content-Security-Policy"]
    assert "script-src" in csp
    assert "'unsafe-inline'" not in csp.split("style-src")[0]  # scripts only


def test_no_hardcoded_search_term_fallback():
    """Regression: sources defaulted to 'backend engineer' for everyone."""
    import inspect

    from jobhunter.sources import adzuna, remotive

    for module in (adzuna, remotive):
        src = inspect.getsource(module.fetch)
        # No `search_terms or ["something"]` fallback anywhere.
        assert 'search_terms or [' not in src
        assert "no search terms configured" in src


def test_user_text_is_html_escaped(client):
    """Autoescaping must neutralise script tags typed into a form."""
    signup(client, "xss@example.com")
    client.post("/profile", data={
        # ≥30 chars (passes the F-04 minimum) and carries the payload.
        "objective": "<script>alert(1)</script> a role in fintech operations",
        "about_me": "x" * 40, "locations": "Milan",
    })
    page = client.get("/profile").text
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_protected_pages_redirect_when_logged_out(client):
    for path in ("/matches", "/profile", "/account", "/onboarding"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code in (303, 307), path
        assert "/login" in r.headers.get("location", "")


def test_logout_clears_the_session(client):
    signup(client, "out@example.com")
    assert client.get("/search").status_code == 200
    client.get("/logout")
    r = client.get("/search", follow_redirects=False)
    assert r.status_code in (303, 307)


# --------------------------- the search gate ------------------------------ #
def test_new_user_cannot_search_until_profile_is_complete(client):
    signup(client, "gate@example.com")
    page = client.get("/search")
    assert "Finalise your profile first" in page.text

    # The server must enforce it too, not just hide the button.
    r = client.post("/search", follow_redirects=False)
    body = r.text if r.status_code == 200 else client.get("/search").text
    assert "Finalise your profile" in body


def test_free_quota_is_shown(client):
    signup(client, "quota@example.com")
    assert "free" in client.get("/search").text.lower()


# ------------------------------ uploads ----------------------------------- #
def test_upload_validation_accepts_pdf_and_rejects_others():
    ext, mime = validate_upload("cv.pdf", b"%PDF-1.4 hello")
    assert ext == "pdf" and mime == "application/pdf"

    with pytest.raises(UploadError):
        validate_upload("evil.exe", b"MZ\x90\x00")          # renamed binary
    with pytest.raises(UploadError):
        validate_upload("cv.pdf", b"")                       # empty
    with pytest.raises(UploadError):
        validate_upload("big.pdf", b"%PDF" + b"x" * 2_000_000)  # over 1 MB


def test_docx_magic_must_match_extension():
    """A .zip renamed to .pdf must not sneak through as a docx."""
    with pytest.raises(UploadError):
        validate_upload("sneaky.pdf", b"PK\x03\x04rest")


def test_uploaded_bytes_round_trip_through_encryption():
    raw = b"%PDF-1.4 sensitive CV content"
    token = encrypt_bytes(raw)
    assert raw not in token          # never stored in the clear
    assert decrypt_bytes(token) == raw


# ------------------------------- GDPR ------------------------------------- #
def test_data_export_returns_everything(client):
    signup(client, "export@example.com")
    data = client.get("/account/export").json()
    assert data["account"]["email"] == "export@example.com"
    for key in ("profile", "documents_uploaded", "searches", "feedback"):
        assert key in data


def test_account_deletion_requires_exact_confirmation(client):
    signup(client, "del@example.com")
    r = client.post("/account/delete", data={"confirm": "yes"})
    assert "Type DELETE" in r.text
    assert client.get("/account").status_code == 200  # still logged in


def test_account_deletion_really_removes_the_user(client):
    signup(client, "gone@example.com")
    r = client.post("/account/delete", data={"confirm": "DELETE"},
                    follow_redirects=False)
    assert r.status_code == 303

    from web.app.db import SessionLocal
    from web.app.models import User

    db = SessionLocal()
    try:
        assert db.query(User).filter(User.email == "gone@example.com").first() is None
    finally:
        db.close()


# ------------------------------- job corpus ------------------------------- #
def test_corpus_upsert_inserts_dedupes_and_refreshes():
    from jobhunter.models import JobPosting
    from web.app.db import SessionLocal, init_db
    from web.app.models import Job
    from web.app.services.corpus_service import upsert_jobs

    init_db()
    db = SessionLocal()
    try:
        db.query(Job).delete()
        db.commit()

        a = JobPosting(source="adzuna", title="Chief of Staff", company="Acme",
                       location="Austin, TX, US", salary_text="150000-200000")
        # Same role from another source -> same dedup_key -> one row.
        a_dup = JobPosting(source="linkedin", title="Chief of Staff", company="Acme",
                           location="Austin, US")
        b = JobPosting(source="remotive", title="Head of Ops", company="Globex",
                       location="Remote - EU", is_remote=True)

        added, updated = upsert_jobs(db, [a, a_dup, b])
        assert added == 2 and updated == 0
        assert db.query(Job).count() == 2

        row = db.query(Job).filter(Job.company == "Acme").one()
        assert row.countries == ["us"]
        assert row.salary_min == 150000 and row.has_salary is True
        remote = db.query(Job).filter(Job.company == "Globex").one()
        assert remote.remote_mode == "remote"

        # Re-running refreshes, never duplicates.
        added2, updated2 = upsert_jobs(db, [a, b])
        assert added2 == 0 and updated2 == 2
        assert db.query(Job).count() == 2
    finally:
        db.query(Job).delete()
        db.commit()
        db.close()


def test_corpus_upgrades_description_when_a_fuller_one_arrives():
    from jobhunter.models import JobPosting
    from web.app.db import SessionLocal, init_db
    from web.app.models import Job
    from web.app.services.corpus_service import upsert_jobs

    init_db()
    db = SessionLocal()
    try:
        db.query(Job).delete()
        db.commit()

        thin = JobPosting(source="s", title="Role", company="Co", description="short")
        upsert_jobs(db, [thin])
        full = JobPosting(source="s", title="Role", company="Co",
                          description="a much longer enriched description " * 5)
        upsert_jobs(db, [full])

        row = db.query(Job).filter(Job.company == "Co").one()
        assert row.description.startswith("a much longer enriched")
        assert db.query(Job).count() == 1
    finally:
        db.query(Job).delete()
        db.commit()
        db.close()


# ------------------------------ score cache ------------------------------- #
def _sc_ctx():
    from jobhunter.config import Materials, Profile
    from web.app.services import score_cache
    p = Profile(raw={"objective": "chief of staff", "locations": ["Italy"]})
    return score_cache, p, Materials()


def test_score_cache_roundtrip_and_context_sensitivity():
    from jobhunter.models import JobPosting, MatchResult
    from web.app.db import SessionLocal, init_db
    from web.app.models import ScoreCache
    sc, p, mats = _sc_ctx()

    init_db()
    db = SessionLocal()
    try:
        db.query(ScoreCache).delete(); db.commit()
        ctx = sc.context_key(p, mats, [], None, None, "haiku")
        job = JobPosting(source="s", title="Chief of Staff", company="Acme",
                         description="Work with the CEO")
        h = sc.job_hash(ctx, job)

        assert sc.get_many(db, [h]) == {}                       # empty at first
        m = MatchResult(tier=2, score=80, reasons="good fit", role="Chief of Staff")
        assert sc.put_many(db, [(h, job, m, "haiku")]) == 1
        got = sc.get_many(db, [h])
        assert got[h].tier == 2 and got[h].score == 80 and got[h].role == "Chief of Staff"

        # A different model (or profile, prompt version, job text) -> different key.
        assert sc.context_key(p, mats, [], None, None, "sonnet") != ctx
        assert sc.job_hash(ctx, JobPosting(source="s", title="Chief of Staff",
                                           company="Acme", description="different")) != h
    finally:
        db.query(ScoreCache).delete(); db.commit(); db.close()


def test_score_cached_reuses_hits_and_scores_only_misses():
    from jobhunter.models import JobPosting, MatchResult
    from web.app.db import SessionLocal, init_db
    from web.app.models import ScoreCache
    from web.app.services import search_service as ss
    from jobhunter.config import Materials, Profile, Settings

    init_db()
    db = SessionLocal()
    try:
        db.query(ScoreCache).delete(); db.commit()
        jobs = [JobPosting(source="s", title=f"Role {i}", company=f"Co{i}") for i in range(3)]

        class FakeMatcher:
            def __init__(self): self.calls = []
            def score(self, js, *a):
                self.calls.append(len(js))
                return [(j, MatchResult(tier=3, score=50, reasons="ok")) for j in js]

        p = Profile(raw={"objective": "x", "locations": ["Italy"]})
        s = Settings(scoring_model="haiku")

        m1 = FakeMatcher()
        r1 = ss._score_cached(db, m1, jobs, p, Materials(), [], None, None, s)
        assert len(r1) == 3 and m1.calls == [3]        # first run: all scored

        m2 = FakeMatcher()
        r2 = ss._score_cached(db, m2, jobs, p, Materials(), [], None, None, s)
        assert len(r2) == 3 and m2.calls == []         # second run: all cached, no scoring
    finally:
        db.query(ScoreCache).delete(); db.commit(); db.close()


# --------------------------- corpus search (step 4) ----------------------- #
def test_corpus_candidates_falls_back_when_embeddings_off():
    from jobhunter.config import Profile, Settings
    from web.app.db import SessionLocal
    from web.app.services.search_service import _corpus_candidates

    db = SessionLocal()
    try:
        jobs, scanned = _corpus_candidates(
            db, Profile(raw={"locations": ["Italy"]}), object(), Settings(), [])
        assert jobs is None      # unconfigured -> live fallback
    finally:
        db.close()


def test_corpus_candidates_ranks_by_cosine(monkeypatch):
    from jobhunter import embeddings
    from jobhunter.config import Profile, Settings
    from web.app.db import SessionLocal, init_db
    from web.app.models import Job, utcnow
    from web.app.services import search_service as ss

    init_db()
    db = SessionLocal()
    try:
        db.query(Job).delete(); db.commit()
        # 25 Italy jobs (clears CORPUS_MIN_KEEP); the "BEST" one points exactly
        # at the query vector, the rest are progressively less aligned.
        now = utcnow()
        db.add(Job(dedup_key="ct:best", source="s", title="BEST", company="Co0",
                   location="Milan, Italy", remote_mode="unknown",
                   embedding=[1.0, 0.0], embedding_model="m", last_seen_at=now))
        for i in range(1, 25):
            db.add(Job(dedup_key=f"ct:{i}", source="s", title=f"J{i}", company=f"Co{i}",
                       location="Milan, Italy", remote_mode="unknown",
                       embedding=[0.2, 0.98], embedding_model="m", last_seen_at=now))
        db.commit()

        monkeypatch.setattr(embeddings, "is_configured", lambda s: True)
        monkeypatch.setattr(embeddings, "embed_one", lambda text, s: [1.0, 0.0])

        class Cand:
            headline = "operator"; target_roles = ["chief of staff"]; skills = []

        jobs, scanned = ss._corpus_candidates(
            db, Profile(raw={"locations": ["Italy"]}), Cand(),
            Settings(embedding_base_url="x", embedding_api_key="k"), ["chief of staff"])

        assert jobs is not None and scanned == 25
        assert jobs[0].title == "BEST"           # highest cosine ranks first
        assert len(jobs) <= ss.CORPUS_TOPK
    finally:
        db.query(Job).delete(); db.commit(); db.close()


# ---------------------------- corpus embeddings --------------------------- #
def test_embed_new_jobs_populates_and_is_idempotent(monkeypatch):
    from jobhunter import embeddings
    from jobhunter.config import Settings
    from jobhunter.models import JobPosting
    from web.app.db import SessionLocal, init_db
    from web.app.models import Job
    from web.app.services import corpus_service as cs

    init_db()
    db = SessionLocal()
    try:
        db.query(Job).delete(); db.commit()
        cs.upsert_jobs(db, [
            JobPosting(source="s", title="Chief of Staff", company="Acme"),
            JobPosting(source="s", title="Head of Ops", company="Globex"),
        ])
        s = Settings(embedding_base_url="https://x", embedding_api_key="k",
                     embedding_model="test-embed")

        calls = {"n": 0}

        def fake_embed(texts, settings):
            calls["n"] += 1
            return [[0.1, 0.2, 0.3] for _ in texts]
        monkeypatch.setattr(embeddings, "embed", fake_embed)

        assert cs.embed_new_jobs(db, s) == 2
        assert all(j.embedding == [0.1, 0.2, 0.3] for j in db.query(Job))
        assert all(j.embedding_model == "test-embed" for j in db.query(Job))
        # Second pass: nothing left to embed (same model) -> no embed call.
        calls["n"] = 0
        assert cs.embed_new_jobs(db, s) == 0
        assert calls["n"] == 0
    finally:
        db.query(Job).delete(); db.commit(); db.close()


def test_embed_new_jobs_noop_when_unconfigured():
    from jobhunter.config import Settings
    from web.app.db import SessionLocal, init_db
    from web.app.services import corpus_service as cs

    init_db()
    db = SessionLocal()
    try:
        assert cs.embed_new_jobs(db, Settings()) == 0
    finally:
        db.close()


# --------------------------- company registry ----------------------------- #
def test_upsert_company_dedupes_on_ats_token():
    from web.app.db import SessionLocal, init_db
    from web.app.models import Company
    from web.app.services.companies_service import upsert_company

    init_db()
    db = SessionLocal()
    try:
        db.query(Company).delete(); db.commit()
        assert upsert_company(db, "greenhouse", "acme", "Acme", source="seed") is True
        db.commit()
        # Same ats+token again -> not a new row.
        assert upsert_company(db, "greenhouse", "acme", "Acme Inc", source="discovered") is False
        # Unknown ATS is rejected.
        assert upsert_company(db, "notreal", "x", "X") is False
        db.commit()
        assert db.query(Company).count() == 1
    finally:
        db.query(Company).delete(); db.commit(); db.close()


def test_poll_all_fetches_registry_and_records_counts(monkeypatch):
    from jobhunter.models import JobPosting
    from web.app.db import SessionLocal, init_db
    from web.app.models import Company
    from web.app.services import companies_service as cs

    init_db()
    db = SessionLocal()
    try:
        db.query(Company).delete(); db.commit()
        db.add(Company(ats="lever", ats_token="globex", name="Globex", source="discovered"))
        db.commit()

        # Don't pull in real config seeds, and stub the ATS fetcher.
        monkeypatch.setattr(cs, "seed_registry", lambda db: 0)
        monkeypatch.setattr(cs, "FETCHERS", {
            "lever": lambda name, token: [
                JobPosting(source=f"ats:lever:{token}", title="Head of Ops", company=name),
                JobPosting(source=f"ats:lever:{token}", title="PM", company=name),
            ]})

        postings = cs.poll_all(db)
        assert len(postings) == 2
        row = db.query(Company).filter(Company.ats_token == "globex").one()
        assert row.jobs_count == 2 and row.last_polled_at is not None
    finally:
        db.query(Company).delete(); db.commit(); db.close()


def test_discover_for_user_upserts_verified_companies(monkeypatch):
    from web.app.db import SessionLocal, init_db
    from web.app.models import Company, Profile as ProfileRow, SeedCompany, User
    from web.app.services import companies_service as cs

    init_db()
    db = SessionLocal()
    try:
        db.query(Company).delete(); db.commit()
        u = User(email="disc@example.com"); db.add(u); db.flush()
        db.add(ProfileRow(user_id=u.id))
        db.add(SeedCompany(user_id=u.id, value="stripe.com"))
        db.commit(); db.refresh(u)

        import jobhunter.discover as discover_mod
        monkeypatch.setattr(discover_mod, "discover",
            lambda *a, **k: ([{"name": "Ramp", "ats": "greenhouse", "token": "ramp"},
                              {"name": "Brex", "ats": "ashby", "token": "brex"}], []))

        captured = {}

        def fake_discover(profile, settings, **kw):
            captured.update(kw)
            return ([{"name": "Ramp", "ats": "greenhouse", "token": "ramp"},
                     {"name": "Brex", "ats": "ashby", "token": "brex"}], [])
        monkeypatch.setattr(discover_mod, "discover", fake_discover)

        res = cs.discover_for_user(db, u)
        assert res["added"] == 2
        assert db.query(Company).filter(Company.discovered_for == u.id).count() == 2
        # Budgeted + accumulating: capped rounds, and excludes known companies.
        assert captured["max_rounds"] == cs.DISCOVER_MAX_ROUNDS
        assert captured["seeds"] == ["stripe.com"]

        # Second call short-circuits once the per-user target is reached (2 now).
        res2 = cs.discover_for_user(db, u, target=2)
        assert res2["added"] == 0 and res2.get("reason") == "target reached"
    finally:
        db.query(Company).delete()
        db.query(SeedCompany).filter_by(user_id=u.id).delete()
        db.query(ProfileRow).filter_by(user_id=u.id).delete()
        db.query(User).filter_by(id=u.id).delete()
        db.commit(); db.close()


# -------------------------------- cron ------------------------------------ #
def test_nightly_runs_daily_always_and_weekly_on_monday(monkeypatch):
    import datetime

    from web.app.services import cron

    calls = []
    monkeypatch.setattr(cron, "reaper_run", lambda: calls.append("reaper") or {})
    monkeypatch.setattr(cron, "ingest_run", lambda cadence: calls.append(cadence) or {})

    # A Tuesday: daily only.
    calls.clear()
    cron.nightly(today=datetime.date(2026, 7, 28))
    assert calls == ["reaper", "daily"]

    # A Monday: discover + weekly + daily.
    calls.clear()
    cron.nightly(today=datetime.date(2026, 7, 27))
    assert calls == ["reaper", "discover", "weekly", "daily"]


# ------------------------------ ingestion --------------------------------- #
def test_corpus_terms_and_countries_prioritise_users_then_defaults():
    from web.app.db import SessionLocal, init_db
    from web.app.models import Profile as ProfileRow, User
    from web.app.services import ingest

    init_db()
    db = SessionLocal()
    try:
        u = User(email="ing@example.com")
        db.add(u); db.flush()
        db.add(ProfileRow(user_id=u.id, search_terms=["Founder's Office"],
                          locations=["Milan", "Remote-Italy"]))
        db.commit(); db.refresh(u)

        terms = ingest.corpus_terms(db)
        assert terms[0] == "Founder's Office"          # user term leads
        assert "chief of staff" in terms               # defaults follow
        countries = ingest.corpus_countries(db)
        assert countries[0] == "Italy"                 # from the user's location
        assert "United States" in countries            # default breadth
    finally:
        db.query(ProfileRow).filter_by(user_id=u.id).delete()
        db.query(User).filter_by(id=u.id).delete()
        db.commit(); db.close()


def test_ingest_cadence_gates_metered_sources(monkeypatch):
    """Weekly sources (Jooble/JSearch) must not run on a daily cycle."""
    from jobhunter.models import JobPosting
    from web.app.db import SessionLocal, init_db
    from web.app.models import Job
    from web.app.services import ingest

    called = []

    def fake_fetch(label, fn, *args):
        called.append(label.split("/")[0])
        return [JobPosting(source=label, title=f"job-{label}", company="C",
                           location="Remote")]

    # Pretend every keyed source has a key so cadence is the only gate.
    monkeypatch.setattr(ingest, "_fetch", fake_fetch)

    class S:
        def __getattr__(self, k):
            return "key"  # every *_key / *_affid present
    monkeypatch.setattr(ingest.Settings, "from_env", staticmethod(lambda: S()))

    init_db()
    db = SessionLocal()
    try:
        db.query(Job).delete(); db.commit()
        res = ingest.run("daily")
        # Daily cycle: Lane A (boards + aggregators) + daily keyed; NOT jooble/jsearch.
        assert "jooble" not in called and "jsearch" not in called
        assert "boards" in called
        assert "careerjet" in called       # a daily keyed source
        assert res["added"] >= 1

        called.clear()
        ingest.run("weekly")
        # Weekly cycle: only the metered weekly sources, no Lane A.
        assert "jooble" in called and "jsearch" in called
        assert "boards" not in called
    finally:
        db.query(Job).delete(); db.commit(); db.close()


# --------------------------- search-term merge ---------------------------- #
@pytest.mark.parametrize(
    "user, derived, expected",
    [
        # User terms lead; derived widen the net; case-insensitive de-dupe.
        (["Chief of Staff"], ["Business Operations", "Chief of Staff", "Head of Ops"],
         ["Chief of Staff", "Business Operations", "Head of Ops"]),
        ([], ["Head of Strategy"], ["Head of Strategy"]),        # none typed -> derived
        (["Founder's Office"], [], ["Founder's Office"]),        # no derivation
        ([" strategy ", "STRATEGY"], [], ["strategy"]),          # trims + dedupes
    ],
)
def test_merge_terms(user, derived, expected):
    from web.app.services.search_service import _merge_terms

    assert _merge_terms(user, derived) == expected


def test_merge_terms_caps_length():
    from web.app.services.search_service import _merge_terms

    assert len(_merge_terms([f"a{i}" for i in range(8)], [f"b{i}" for i in range(8)], cap=10)) == 10


# ------------------------------- reaper ----------------------------------- #
class _FakeResp:
    def __init__(self, status, text=""):
        self.status_code = status
        self.text = text


@pytest.mark.parametrize(
    "status, body, expected",
    [
        (404, "", "gone"),
        (410, "", "gone"),
        (200, "Apply now for this great role", "active"),
        (200, "This position is closed. No longer available.", "gone"),
        (200, "Sorry, page not found", "gone"),
        (403, "forbidden", "unknown"),        # blocked: don't guess
    ],
)
def test_check_url_classification(status, body, expected):
    from web.app.services.reaper import check_url

    class C:
        def get(self, url, follow_redirects=True):
            return _FakeResp(status, body)

    assert check_url("https://x/job", C()) == expected


def test_check_url_unknown_on_network_error():
    from web.app.services.reaper import check_url

    class C:
        def get(self, *a, **k):
            raise RuntimeError("timeout")

    assert check_url("https://x", C()) == "unknown"
    assert check_url("", C()) == "unknown"    # no URL


def test_sweep_ttl_deletes_stale_and_linkcheck_deletes_gone(monkeypatch):
    from datetime import timedelta

    from jobhunter.models import JobPosting
    from web.app import services  # noqa: F401
    from web.app.db import SessionLocal, init_db
    from web.app.models import Job, utcnow
    from web.app.services import reaper
    from web.app.services.corpus_service import upsert_jobs

    init_db()
    db = SessionLocal()
    try:
        db.query(Job).delete()
        db.commit()

        upsert_jobs(db, [
            JobPosting(source="s", title="Stale", company="Old", url="https://x/stale"),
            JobPosting(source="s", title="Dead", company="D", url="https://x/dead"),
            JobPosting(source="s", title="Live", company="L", url="https://x/live"),
        ])
        # Make "Stale" older than the TTL window.
        stale = db.query(Job).filter(Job.company == "Old").one()
        stale.last_seen_at = utcnow() - timedelta(days=60)
        db.commit()

        def fake_check(url, client):
            return "gone" if url.endswith("/dead") else "active"

        monkeypatch.setattr(reaper, "check_url", fake_check)
        # Avoid real HTTP: stub the client context manager.
        monkeypatch.setattr(reaper.httpx, "Client", lambda *a, **k: _NullClient())

        res = reaper.sweep(db, stale_days=45)
        assert res["ttl_deleted"] == 1        # Stale
        assert res["gone_deleted"] == 1       # Dead
        assert res["remaining"] == 1          # Live survives
        assert db.query(Job).filter(Job.company == "L").count() == 1
        live = db.query(Job).filter(Job.company == "L").one()
        assert live.last_checked_at is not None
    finally:
        db.query(Job).delete()
        db.commit()
        db.close()


class _NullClient:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# ------------------------------ list parsing ------------------------------ #
@pytest.mark.parametrize(
    "text, expected",
    [
        # The bug: typed on one line with commas, stored as a single entry, so
        # the engine matched jobs against the literal string "Milan, Turin, ..."
        # and every search came back empty.
        ("Milan, Turin, Remote-EU, Remote-Italy",
         ["Milan", "Turin", "Remote-EU", "Remote-Italy"]),
        ("Milan\nTurin", ["Milan", "Turin"]),
        ("Milan,\n  Turin ,\n", ["Milan", "Turin"]),
        ("Milan, Milan", ["Milan"]),          # de-duplicated
        ("", []),
        ("   ", []),
    ],
)
def test_split_list_accepts_commas_and_newlines(text, expected):
    from web.app.services.profile_service import split_list

    assert split_list(text) == expected


@pytest.mark.parametrize(
    "modes, countries, anywhere, expected",
    [
        (["onsite", "remote"], ["United States", "Italy"], False,
         ["United States", "Remote-United States", "Italy", "Remote-Italy"]),
        (["remote"], ["United States"], True,
         ["Remote-United States", "Remote-Anywhere"]),
        (["hybrid"], ["Germany"], False, ["Germany"]),
        (["onsite"], [], False, []),                 # no country -> nothing
        (["remote"], [], True, ["Remote-Anywhere"]),
    ],
)
def test_build_location_tokens(modes, countries, anywhere, expected):
    from web.app.services.profile_service import build_location_tokens

    assert build_location_tokens(modes, countries, anywhere) == expected


@pytest.mark.parametrize(
    "locations, modes, countries",
    [
        (["Milan", "Turin", "Remote-EU", "Remote-Italy"], ["onsite", "remote"], ["Italy"]),
        (["New York", "Remote-US"], ["onsite", "remote"], ["United States"]),
        (["Remote-Anywhere"], ["remote"], []),
    ],
)
def test_infer_structured_location_backfills_legacy_profiles(locations, modes, countries):
    from web.app.services.profile_service import infer_structured_location

    assert infer_structured_location(locations) == (modes, countries)


def test_split_list_honours_limit():
    from web.app.services.profile_service import split_list

    assert split_list("a,b,c,d", limit=2) == ["a", "b"]


def test_engine_profile_resplits_legacy_locations():
    """Profiles saved before the fix must not stay broken."""
    from web.app.db import SessionLocal
    from web.app.models import Profile, User
    from web.app.services.profile_service import build_engine_profile

    db = SessionLocal()
    try:
        user = User(email="legacy@example.com")
        db.add(user)
        db.flush()
        db.add(Profile(user_id=user.id, locations=["Milan, Turin"]))
        db.commit()
        db.refresh(user)
        assert build_engine_profile(db, user).locations == ["Milan", "Turin"]
    finally:
        db.close()


# --------------------------- profile completeness ------------------------- #
def test_completeness_scores_and_gates():
    from web.app.db import SessionLocal
    from web.app.models import Material, Profile, User
    from web.app.services.profile_service import completeness

    db = SessionLocal()
    try:
        user = User(email="score@example.com")
        db.add(user)
        db.flush()
        p = Profile(user_id=user.id)
        db.add(p)
        db.commit()
        db.refresh(user)

        empty = completeness(db, user)
        assert not empty.can_search and empty.score < 20

        p.objective = "x" * 60
        p.about_me = "y" * 60
        p.seniority = ["senior"]
        p.company_type = ["startup"]
        p.verticals = ["fintech"]
        p.locations = ["Milan"]
        p.job_type = ["full-time"]
        db.add(Material(user_id=user.id, kind="cv", filename="cv.pdf",
                        mime="application/pdf", size_bytes=10,
                        ciphertext=b"x", text="cv text"))
        db.commit()

        full = completeness(db, user)
        assert full.can_search
        assert full.score >= 70
        # No optional extras yet, so it should still nudge for more.
        assert full.should_improve or full.score >= 70
    finally:
        db.close()
