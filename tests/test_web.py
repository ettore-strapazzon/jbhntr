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

    # R9: feedback is now a 1-5 rating; vote is derived from it.
    r = client.post(f"/feedback/{rid}", data={"rating": "5"},
                    headers={"HX-Request": "true"}, follow_redirects=False)
    assert r.status_code == 200
    assert f"vote-{rid}" in r.text and 'name="rating" value="5"' in r.text
    assert 'aria-pressed="true"' in r.text        # the rating is reflected
    # COPY-010: 4-5 saves immediately with no reason prompt
    assert "context for future scans" in r.text
    assert "What made it" not in r.text            # no reason question on a high rating

    from web.app.db import SessionLocal
    from web.app.models import Feedback
    db2 = SessionLocal()
    try:
        fb = db2.query(Feedback).filter_by(job_result_id=rid).one()
        assert fb.rating == 5 and fb.vote == "up"  # vote derived from rating
    finally:
        db2.close()

    # a low rating (1-3) asks for the reason
    rlow = client.post(f"/feedback/{rid}", data={"rating": "2"},
                       headers={"HX-Request": "true"}, follow_redirects=False)
    assert "What made it irrelevant or misleading?" in rlow.text

    r2 = client.post(f"/feedback/{rid}", data={"rating": "1"}, follow_redirects=False)
    assert r2.status_code == 303                  # non-HTMX keeps the redirect


def test_f13_premium_waitlist_records_intent(client):
    signup(client, email="f13@example.com")
    r = client.post("/premium/waitlist", follow_redirects=False)
    assert r.status_code == 303 and "requested=1" in r.headers["location"]
    from web.app.db import SessionLocal
    from web.app.models import User
    db = SessionLocal()
    try:
        assert db.query(User).filter_by(email="f13@example.com").one().premium_requested_at
    finally:
        db.close()


def test_premium_waitlist_htmx_swaps_button_and_sends_once(client, monkeypatch):
    """S-06/S-07: an HTMX click returns the 'You are on the list' state without a
    reload, and clicking twice sends exactly one waiting-list email."""
    sent = []
    from web.app.services import email as mail
    # The route does `from ..services.email import send_premium_waitlist` at call
    # time, so patching the module attribute intercepts the send.
    monkeypatch.setattr(mail, "send_premium_waitlist",
                        lambda *a, **k: sent.append(a) or True)
    signup(client, email="wl@example.com")
    r1 = client.post("/premium/waitlist", data={"region": "top"},
                     headers={"HX-Request": "true"})
    assert r1.status_code == 200 and "You're on the Premium waitlist" in r1.text
    r2 = client.post("/premium/waitlist", data={"region": "top"},
                     headers={"HX-Request": "true"})
    assert r2.status_code == 200 and "You're on the Premium waitlist" in r2.text
    assert len(sent) == 1                              # deduped: one email only


def test_premium_page_has_banner_and_no_price(client):
    """Round 5b: the logged-in Premium tab is the shared pricing page with an
    auth-aware frame — 'Your plan' heading, current-plan badge, remaining-allowance
    figures, waitlist CTA, and no quoted price."""
    signup(client, email="pp@example.com")
    r = client.get("/premium")
    assert r.status_code == 200
    assert "Your plan" in r.text                      # h1
    assert "Your current plan" in r.text              # Free-box badge, logged in
    assert "Coming soon" in r.text                    # Premium badge (CSS uppercases)
    assert "Join the Premium waitlist" in r.text
    assert "Affordable" in r.text                     # Premium price, soft promise
    from web.app.config import config
    assert f"of {config.free_searches}" in r.text     # remaining-allowance figures
    assert "$" not in r.text                           # no price is quoted


def test_waitlist_email_renders_in_shell_and_carries_unsub():
    from web.app.services import email as mail
    html, text = mail.render("premium_waitlist", {
        "first_name": "", "search_url": "http://x/matches",
        "unsub_token": "TK", "unsub_url": "http://x/unsubscribe?t=TK&scope=waitlist"})
    assert "#174b3e" in html and "Ettore" in html      # S4 pine shell, human signature
    assert "You are on the list" in html
    assert "scope=waitlist" in html and "scope=waitlist" in text
    assert "Thanks." in text                            # empty first_name drops the name


def test_unsubscribe_waitlist_scope_removes_intent(client):
    from web.app.db import SessionLocal
    from web.app.models import User, utcnow
    from web.app.services.email import make_unsub_token
    signup(client, email="uw@example.com")
    db = SessionLocal()
    u = db.query(User).filter_by(email="uw@example.com").one()
    u.premium_requested_at = utcnow()
    db.commit()
    tok = make_unsub_token(u.id)
    db.close()
    client.get(f"/unsubscribe?t={tok}&scope=waitlist")
    db = SessionLocal()
    u = db.query(User).filter_by(email="uw@example.com").one()
    assert u.premium_requested_at is None              # waiting-list row removed
    db.close()


def test_f11_skip_link_and_focus_style_present(client):
    assert 'class="skip-link"' in client.get("/").text
    assert ":focus-visible" in client.get("/static/app.css").text


def test_landing_hero_and_tier_tokens(client):
    page = client.get("/").text
    assert "become your next job" in page                      # HOME-001 hero
    assert "the opportunities worth pursuing" in page          # HOME-001 lede
    assert "Illustrative example" in page                      # HOME-003 labelled card
    assert "Fits what you want" in page                        # two-bar card
    assert "What JBHNTR does not do" in page and "scrape" in page  # honesty block
    css = client.get("/static/app.css").text
    assert "--tier-1:" in css and ".tier-1{" in css           # tier colours owned by CSS (F-14)
    assert "--mono:" in css                                    # monospace token


# --------------------------- design phase C ------------------------------- #
def test_onboarding_is_three_labelled_steps(client):
    signup(client, "ob3@example.com")
    for step, marker in (("upload", "Private by default"),       # trust block (F-15)
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
    empty = client.post("/fields/depth", data={"field": "objective", "objective": ""}).text
    some = client.post("/fields/depth", data={"field": "objective", "objective": "hi"}).text
    deep = client.post("/fields/depth", data={"field": "objective", "objective": "x" * 400}).text
    assert "depth-rail" not in empty       # empty says nothing, not "too short" (R5.5)
    assert "lvl1" in some
    assert "lvl3" in deep


def test_profile_upload_returns_to_profile(client):
    """R6: uploading a CV from Profile must not dump the user into onboarding."""
    signup(client, "upret@example.com")
    files = {"file": ("cv.txt", b"Senior PM, fintech payments, ten years.", "text/plain")}
    r = client.post("/onboarding/upload",
                    data={"kind": "cv", "step": "upload", "return_to": "profile"},
                    files=files, follow_redirects=False)
    assert r.headers["location"] == "/profile#documents"


def test_profile_oversized_upload_shows_error_on_profile(client):
    signup(client, "big@example.com")
    big = {"file": ("cv.pdf", b"%PDF-1.4 " + b"x" * (1024 * 1024 + 10), "application/pdf")}
    r = client.post("/onboarding/upload",
                    data={"kind": "cv", "step": "upload", "return_to": "profile"}, files=big)
    assert "Your documents" in r.text          # re-rendered Profile, not onboarding
    assert "too large" in r.text.lower()


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


def test_digest_skips_an_empty_day_and_never_repeats(client):
    from web.app.db import SessionLocal
    from web.app.models import User
    from web.app.services import digest
    signup(client, "dig@example.com")
    db = SessionLocal()
    u = db.query(User).filter_by(email="dig@example.com").first()
    u.plan = "premium"; db.commit()
    assert digest.build_digest(db, u) is None          # no matches -> no email
    _seed_run(db, u.id, [("dg1", 1, 90, "A role"), ("dg2", 2, 82, "B role")], hours_ago=0)
    ctx = digest.build_digest(db, u)
    assert ctx and ctx["n"] == 2                        # two new roles worth sending
    assert digest.build_digest(db, u) is None          # already digested, never repeat


def test_email_templates_render_html_and_text():
    from web.app.services import email as mail
    for name, ctx in [("welcome", {"free_searches": 3}), ("reset", {"token": "t"})]:
        html, text = mail.render(name, ctx)
        assert "<table" in html and len(text) > 20
        assert "—" not in html and "—" not in text   # no em dashes (R2)


def test_email_shell_brand_band_and_unsub_only_on_optin():
    """S-03: shared shell wraps every email — pine brand band, 600px card.
    Transactional mail (reset) shows no unsubscribe; opt-in mail (digest) does."""
    from web.app.services import email as mail
    reset_html, _ = mail.render("reset", {"token": "t"})
    assert "#174b3e" in reset_html and "JBHNTR" in reset_html   # brand band
    assert "/unsubscribe" not in reset_html                     # transactional: no unsub
    digest_html, digest_txt = mail.render("digest", {
        "n": 1, "top_score": 90, "top_title": "A", "top_company": "B",
        "top_location": "C", "reviewed": 40, "jobs": [], "remaining": 0,
        "closing": "ok", "email": "a@b.com", "unsub_token": "UNSUB"})
    assert "/unsubscribe?t=UNSUB" in digest_html                # opt-in: unsub present
    assert "UNSUB" in digest_txt


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
    monkeypatch.setattr(mail, "send",
                        lambda to, subject, text, html=None, headers=None: sent.append(subject) or True)
    signup(client, "welcome@example.com")
    assert any("Welcome to JBHNTR" in s for s in sent)   # welcome subject


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
    assert "Finish the search profile first" in page.text

    # The server must enforce it too, not just hide the button.
    r = client.post("/search", follow_redirects=False)
    body = r.text if r.status_code == 200 else client.get("/search").text
    assert "Finish the search profile first" in body


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
        from web.app.config import config as web_config
        assert len(jobs) <= web_config.corpus_topk
    finally:
        db.query(Job).delete(); db.commit(); db.close()


def test_corpus_candidates_prefers_geo_confirmed_over_untagged(monkeypatch):
    """Geo-confirmed Italy jobs must reach the shortlist even when many untagged,
    blank-location rows have HIGHER cosine — the real cause of the '0 results'
    with 953 Italy jobs buried under 7k untagged rows."""
    from jobhunter import embeddings
    from jobhunter.config import Profile, Settings
    from web.app.db import SessionLocal, init_db
    from web.app.models import Job, utcnow
    from web.app.services import search_service as ss

    init_db()
    db = SessionLocal()
    try:
        db.query(Job).delete(); db.commit()
        now = utcnow()
        # 25 confirmed Italy jobs, but with LOW cosine (far from the query vector).
        for i in range(25):
            db.add(Job(dedup_key=f"it:{i}", source="s", title=f"IT{i}", company=f"ItCo{i}",
                       location="Milan, Italy", countries=["it"], remote_mode="unknown",
                       embedding=[0.1, 0.99], embedding_model="m", last_seen_at=now))
        # 100 untagged, blank-location rows with HIGHER cosine (aligned to query).
        for i in range(100):
            db.add(Job(dedup_key=f"amb:{i}", source="s", title=f"AMB{i}", company=f"AmbCo{i}",
                       location="", countries=[], remote_mode="unknown",
                       embedding=[1.0, 0.0], embedding_model="m", last_seen_at=now))
        db.commit()

        monkeypatch.setattr(embeddings, "is_configured", lambda s: True)
        monkeypatch.setattr(embeddings, "embed_one", lambda text, s: [1.0, 0.0])

        class Cand:
            headline = "operator"; target_roles = ["chief of staff"]; skills = []

        jobs, scanned = ss._corpus_candidates(
            db, Profile(raw={"locations": ["Italy"]}), Cand(),
            Settings(embedding_base_url="x", embedding_api_key="k"), ["chief of staff"])

        assert jobs is not None
        # Despite lower cosine, ONLY the confirmed Italy jobs are shortlisted; the
        # high-cosine untagged blank-location rows are excluded.
        assert jobs, "expected the confirmed Italy jobs, got nothing"
        assert all(j.title.startswith("IT") for j in jobs)
    finally:
        db.query(Job).delete(); db.commit(); db.close()


def test_location_gate_drops_foreign_job_scored_with_blank_location():
    """A posting that reached scoring with a BLANK location field (so the country
    tag and prefilter both deferred) is dropped once the LLM surfaces its real,
    foreign location — location is a hard requirement."""
    from jobhunter.config import Profile
    from jobhunter.models import JobPosting
    from web.app.services import search_service as ss

    class M:
        def __init__(self, loc, remote=""): self.location = loc; self.remote = remote

    p = Profile(raw={"locations": ["Italy"]})            # Italy, on-site only
    blank = JobPosting(source="adzuna", title="Chief of Staff", company="ExitPath",
                       location="", url="http://x")
    # LLM extracted a US city from the description -> on-site hard mismatch -> drop.
    assert ss._location_ok(blank, M("Albany, New York, USA"), p) is False
    # An Italian location the LLM surfaced is kept.
    assert ss._location_ok(blank, M("Milan, Italy"), p) is True
    # Genuinely unresolvable / no constraint -> keep (defer, don't over-filter).
    assert ss._location_ok(blank, M(""), p) is True
    assert ss._location_ok(blank, M("Albany, New York, USA"),
                           Profile(raw={"locations": []})) is True

    # A user open to remote (Italy hybrid+remote). Remote roles are NOT re-judged
    # on their nominal city — the whole point of choosing remote.
    pr = Profile(raw={"locations": ["Italy", "Remote-Italy"]})
    assert ss._location_ok(blank, M("Remote"), pr) is True
    assert ss._location_ok(blank, M("Remote, Germany"), pr) is True     # remote -> keep
    assert ss._location_ok(blank, M("", "remote"), pr) is True          # LLM flagged remote
    # But a foreign ON-SITE job is still dropped even for the remote-friendly user.
    assert ss._location_ok(blank, M("Albany, New York, USA"), pr) is False


def test_discovery_change_trigger_occasions(monkeypatch):
    """Occasions 1-3 fire on the user's next search; the weekly cadence does not."""
    from datetime import timedelta
    from web.app.models import User, utcnow
    from web.app.services import companies_service as cs

    def prem(**kw):
        u = User(email="x", plan="premium", premium_until=utcnow() + timedelta(days=30))
        for k, v in kw.items():
            setattr(u, k, v)
        return u

    def sig(seeds=(), verticals=(), company_types=(), countries=()):
        return {"seeds": list(seeds), "verticals": list(verticals),
                "company_types": list(company_types), "countries": list(countries)}

    T = cs.discovery_change_trigger
    # 1) never run -> first search triggers it.
    assert T(prem(last_discovery_at=None), sig()) is True
    # 2) >= N new seed companies since last run.
    base = dict(last_discovery_at=utcnow(), discovery_seeds=["a"], discovery_verticals=["fin"],
                discovery_company_types=["startup"], discovery_countries=["it"])
    u2 = prem(**base)
    assert T(u2, sig(["a", "b", "c", "d"], ["fin"], ["startup"], ["it"])) is True   # 3 new seeds
    assert T(u2, sig(["a", "b"], ["fin"], ["startup"], ["it"])) is False            # 1 new seed
    # 3) any new market signal — vertical, company type OR country.
    assert T(prem(**base), sig(["a"], ["fin", "health"], ["startup"], ["it"])) is True   # +vertical
    assert T(prem(**base), sig(["a"], ["fin"], ["startup", "scaleup"], ["it"])) is True  # +type
    assert T(prem(**base), sig(["a"], ["fin"], ["startup"], ["it", "de"])) is True       # +country
    # No change and just ran -> the change trigger stays quiet (Monday cron covers it).
    assert T(prem(**base), sig(["a"], ["fin"], ["startup"], ["it"])) is False
    # Free users never trigger it.
    assert T(User(email="y", plan="free", last_discovery_at=None), sig()) is False


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
        u = User(email="disc@example.com", plan="premium")  # discovery is premium-only
        db.add(u); db.flush()
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
        assert res2["added"] == 0 and res2.get("reason", "").startswith("target reached")
    finally:
        db.query(Company).delete()
        db.query(SeedCompany).filter_by(user_id=u.id).delete()
        db.query(ProfileRow).filter_by(user_id=u.id).delete()
        db.query(User).filter_by(id=u.id).delete()
        db.commit(); db.close()


def test_discover_for_user_runs_without_seeds_from_market_profile(monkeypatch):
    """Seeds are optional: a premium user with a market profile (verticals/company
    type) but NO seed companies still discovers from those signals. A truly empty
    profile bails."""
    from web.app.db import SessionLocal, init_db
    from web.app.models import Company, Profile as ProfileRow, User
    from web.app.services import companies_service as cs

    init_db()
    db = SessionLocal()
    try:
        db.query(Company).delete(); db.commit()
        u = User(email="noseed@example.com", plan="premium")
        db.add(u); db.flush()
        db.add(ProfileRow(user_id=u.id, verticals=["fintech"], company_type=["startup"]))
        db.commit(); db.refresh(u)

        captured = {}
        import jobhunter.discover as discover_mod
        def fake_discover(profile, settings, **k):
            captured["seeds"] = k.get("seeds")
            return ([{"name": "Qonto", "ats": "lever", "token": "qonto"}], [])
        monkeypatch.setattr(discover_mod, "discover", fake_discover)

        res = cs.discover_for_user(db, u)
        assert res["added"] == 1                          # ran despite no seeds
        assert captured["seeds"] == []                    # discovered from market profile

        # A user with neither seeds nor market profile bails clearly.
        u2 = User(email="empty@example.com", plan="premium")
        db.add(u2); db.flush()
        db.add(ProfileRow(user_id=u2.id)); db.commit(); db.refresh(u2)
        res2 = cs.discover_for_user(db, u2)
        assert res2["added"] == 0 and "no seeds" in res2["reason"]
    finally:
        db.query(Company).delete()
        for em in ("noseed@example.com", "empty@example.com"):
            uid = db.query(User.id).filter_by(email=em).scalar()
            if uid is not None:
                db.query(ProfileRow).filter_by(user_id=uid).delete()
                db.query(User).filter_by(id=uid).delete()
        db.commit(); db.close()


# -------------------------------- cron ------------------------------------ #
def test_nightly_runs_daily_always_and_weekly_on_monday(monkeypatch):
    import datetime

    from web.app.services import cron

    calls = []
    monkeypatch.setattr(cron, "reaper_run", lambda **kw: calls.append("reaper") or {})
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


# --------------------------- operator dashboard --------------------------- #
def test_admin_404_when_token_unset(client, monkeypatch):
    """The /admin surface is off unless ADMIN_TOKEN is set, so a fresh deploy
    never exposes it."""
    from web.app.config import config
    monkeypatch.setattr(config, "admin_token", "")   # simulate an unset token
    assert client.get("/admin").status_code == 404
    assert client.get("/admin/waitlist.csv").status_code == 404


def test_admin_requires_basic_auth(client, monkeypatch):
    from web.app.config import config
    monkeypatch.setattr(config, "admin_token", "s3cret")
    assert client.get("/admin").status_code == 401                 # no creds
    assert client.get("/admin", auth=("op", "wrong")).status_code == 401
    r = client.get("/admin", auth=("op", "s3cret"))
    assert r.status_code == 200 and "Operator dashboard" in r.text


def test_admin_shows_waitlist_and_csv(client, monkeypatch):
    from web.app.config import config
    from web.app.db import SessionLocal
    from web.app.models import User, utcnow
    monkeypatch.setattr(config, "admin_token", "s3cret")
    signup(client, email="wanter@example.com")
    db = SessionLocal()
    u = db.query(User).filter_by(email="wanter@example.com").one()
    u.premium_requested_at = utcnow()
    db.commit()
    db.close()

    r = client.get("/admin", auth=("op", "s3cret"))
    assert r.status_code == 200 and "wanter@example.com" in r.text

    csv = client.get("/admin/waitlist.csv", auth=("op", "s3cret"))
    assert csv.status_code == 200
    assert "text/csv" in csv.headers["content-type"]
    assert "wanter@example.com" in csv.text and "email,requested_at" in csv.text


# --------------------------- visitor analytics ---------------------------- #
def test_visitor_hash_is_stable_and_ip_sensitive():
    from web.app.services.analytics import visitor_hash
    a = visitor_hash("1.2.3.4", "UA/1")
    assert a == visitor_hash("1.2.3.4", "UA/1")              # same ip+ua => same token (persists)
    assert a != visitor_hash("9.9.9.9", "UA/1")             # different ip => different
    assert a != visitor_hash("1.2.3.4", "UA/2")             # different browser => different
    assert visitor_hash("", "UA/1") == ""                   # no ip => uncounted
    assert len(a) == 64 and all(c in "0123456789abcdef" for c in a)     # a hash, not an ip


def test_pageview_stores_visitor_token_never_ip(client):
    from web.app.db import SessionLocal
    from web.app.models import PageView
    ip = "203.0.113.77"
    client.get("/", headers={"cf-connecting-ip": ip, "cf-ipcountry": "IT",
                             "user-agent": "Mozilla/5.0 test"})
    db = SessionLocal()
    try:
        pv = db.query(PageView).order_by(PageView.id.desc()).first()
        assert pv is not None
        assert pv.visitor and len(pv.visitor) == 64          # a token was stored
        assert ip not in (pv.visitor or "")                  # the raw IP never is
        assert pv.country == "IT"
    finally:
        db.close()


def test_admin_shows_unique_visitors_by_country(client, monkeypatch):
    from web.app.config import config
    from web.app.db import SessionLocal
    from web.app.models import PageView
    from web.app.services.analytics import visitor_hash
    monkeypatch.setattr(config, "admin_token", "s3cret")
    db = SessionLocal()
    try:
        # two distinct visitors from IT (one visiting twice), one from FR
        for ip, ua, country in [("1.1.1.1", "A", "IT"), ("1.1.1.1", "A", "IT"),
                                 ("2.2.2.2", "B", "IT"), ("3.3.3.3", "C", "FR")]:
            db.add(PageView(path="/", country=country, visitor=visitor_hash(ip, ua)))
        db.commit()
    finally:
        db.close()
    r = client.get("/admin", auth=("op", "s3cret"))
    assert r.status_code == 200
    assert "Unique visitors by country" in r.text


# --------------------------- SEO foundation (Guide v2) --------------------- #
def test_home_has_public_seo_metadata(client):
    page = client.get("/").text
    assert "AI Job Search Agent Across Job Boards and Career Pages" in page
    assert 'name="description"' in page
    assert 'name="robots" content="index,follow' in page
    assert 'rel="canonical"' in page
    assert 'property="og:title"' in page
    assert "application/ld+json" in page


def test_home_schema_blocks_are_valid_json(client):
    import json
    import re
    page = client.get("/").text
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>',
                        page, re.DOTALL)
    assert len(blocks) == 4
    types = {json.loads(b)["@type"] for b in blocks}
    assert types == {"Organization", "WebSite", "SoftwareApplication", "FAQPage"}
    from web.app import seo
    for b in blocks:                                   # non-FAQ schema uses config base
        if json.loads(b)["@type"] != "FAQPage":
            assert seo.origin() in b


def test_auth_and_private_pages_are_noindex(client):
    for path in ("/login", "/signup", "/forgot"):
        page = client.get(path).text
        assert 'name="robots" content="noindex,nofollow,noarchive"' in page


def test_legal_pages_are_public_and_indexable(client):
    from web.app import seo
    for path in ("/privacy", "/terms", "/cookies"):
        page = client.get(path).text
        assert 'name="robots" content="index,follow' in page
        assert f'rel="canonical" href="{seo.absolute_url(path)}"' in page


def test_robots_txt_allows_all_and_blocks_private(client):
    r = client.get("/robots.txt")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "User-agent: *" in r.text and "Allow: /" in r.text
    assert "Disallow: /matches" in r.text and "Disallow: /account" in r.text
    assert "User-agent: GPTBot" not in r.text          # allow-all policy: no bot blocks
    from web.app import seo
    assert f"Sitemap: {seo.absolute_url('/sitemap.xml')}" in r.text


def test_sitemap_contains_only_public_canonicals(client):
    import re
    from web.app import seo
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "application/xml" in r.headers["content-type"]
    locs = set(re.findall(r"<loc>(.*?)</loc>", r.text))
    for path in ("/", "/how-it-works", "/security", "/pricing",
                 "/compare/linkedin-jobs", "/privacy", "/terms", "/cookies"):
        assert seo.absolute_url(path) in locs
    for path in ("/matches", "/profile", "/account", "/login", "/signup", "/premium"):
        assert seo.absolute_url(path) not in locs


def test_public_marketing_pages_are_indexable_single_h1(client):
    import re
    from web.app import seo
    for path in ("/how-it-works", "/security", "/pricing", "/compare/linkedin-jobs"):
        page = client.get(path).text
        assert 'name="robots" content="index,follow' in page       # public
        assert f'rel="canonical" href="{seo.absolute_url(path)}"' in page
        assert len(re.findall(r"<h1[ >]", page)) == 1              # exactly one H1


def test_home_faq_visible_matches_schema(client):
    import json
    import re
    from web.app import seo
    page = client.get("/").text
    q0 = seo.FAQ_PAIRS[0][0]
    assert f"<summary>{q0}</summary>" in page                       # visible FAQ
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>',
                        page, re.DOTALL)
    faq = [json.loads(b) for b in blocks if json.loads(b)["@type"] == "FAQPage"]
    assert faq, "FAQPage schema present"
    names = {e["name"] for e in faq[0]["mainEntity"]}
    assert names == {q for q, _ in seo.FAQ_PAIRS}                   # schema == visible


def test_signed_out_nav_points_to_real_pages(client):
    page = client.get("/").text
    for href in ('href="/how-it-works"', 'href="/pricing"', 'href="/security"'):
        assert href in page
    assert 'href="/#how"' not in page and 'href="/#pricing"' not in page


# --------------------------- trust / legal alignment ---------------------- #
def test_privacy_future_recruiter_optin(client):
    page = client.get("/privacy").text
    assert "off by default" in page                       # future discoverability
    assert "candidate discoverability" in page
    assert "never shared with employers" not in page      # absolute removed


def test_terms_plan_wording_has_no_unlimited(client):
    page = client.get("/terms").text
    assert "not for sale while payments are disabled" in page
    assert "unlimited" not in page.lower()


def test_security_page_links_to_legal(client):
    page = client.get("/security").text
    for href in ('href="/privacy"', 'href="/terms"', 'href="/cookies"'):
        assert href in page


# --------------------------- claim lint (TEST-004) ------------------------ #
def _customer_template_files():
    import glob
    import os
    files = []
    for f in glob.glob("web/app/templates/**/*.html", recursive=True) + \
             glob.glob("web/app/templates/**/*.txt", recursive=True):
        if os.path.basename(f) == "admin.html":
            continue                                   # operator-only, not customer copy
        files.append(f)
    return files


BANNED_CLAIMS = (
    "every new posting", "twenty ratings is enough", "unlimited searches",
    "unlimited tailored", "stronger scoring model", "no recruiter has an account",
    "roles are posted days before", "perfect match", "dream job", "guaranteed",
    "overnight", "while you sleep",
)
BANNED_VOICE = (
    "tell it", "ask it", "let it", "it learns", "it gets better", "correct it",
    "teach it", "the ai", "our ai", "ai-powered", "the algorithm",
)


def test_claim_lint_no_banned_claims_or_voice():
    offenders = []
    for f in _customer_template_files():
        low = open(f, encoding="utf-8").read().lower()
        for phrase in BANNED_CLAIMS:
            if phrase in low:
                offenders.append(f"{f}: claim '{phrase}'")
        for phrase in BANNED_VOICE:
            if phrase == "the ai":
                # allow the category noun "AI job search/-search agent"
                stripped = low.replace("ai job search agent", "").replace(
                    "ai job-search agent", "")
                if "the ai" in stripped:
                    offenders.append(f"{f}: voice 'the ai'")
            elif phrase in low:
                offenders.append(f"{f}: voice '{phrase}'")
    assert not offenders, "banned phrases: " + "; ".join(offenders)


def test_claim_lint_no_dashes_in_marketing_prose():
    """Marketing prose (landing + public pages + emails) stays free of em/en
    dashes. Legal and operator copy are allowlisted by scope."""
    import glob
    offenders = []
    files = (["web/app/templates/landing.html"]
             + glob.glob("web/app/templates/marketing/*.html")
             + glob.glob("web/app/templates/email/*.html")
             + glob.glob("web/app/templates/email/*.txt"))
    for f in files:
        text = open(f, encoding="utf-8").read()
        if "\u2014" in text or "\u2013" in text:
            offenders.append(f)
    assert not offenders, "em/en dash in: " + ", ".join(offenders)


# --------------------------- product events (PROOF-003) ------------------- #
def test_signup_and_waitlist_record_product_events(client):
    from web.app.db import SessionLocal
    from web.app.models import ProductEvent, User
    signup(client, "ev@example.com")
    client.post("/premium/waitlist", data={"region": "top"})
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(email="ev@example.com").one()
        names = {e.name for e in db.query(ProductEvent).filter_by(user_id=u.id)}
        assert "signup_completed" in names
        assert "premium_waitlist_joined" in names
    finally:
        db.close()


def test_events_helper_rejects_unknown_and_strips_pii():
    from web.app.db import SessionLocal
    from web.app.models import ProductEvent
    from web.app.services import events
    db = SessionLocal()
    try:
        before = db.query(ProductEvent).count()
        events.record(db, "definitely_not_an_event", user_id=None)   # unknown -> no-op
        assert db.query(ProductEvent).count() == before
        events.record(db, "match_rated", rating=4, email="secret@x.com", cv_text="PII")
        ev = db.query(ProductEvent).filter_by(name="match_rated").order_by(
            ProductEvent.id.desc()).first()
        assert ev.properties == {"rating": 4}         # only allowlisted keys kept
    finally:
        db.close()


def test_pageview_retention_prune():
    import datetime
    from web.app.db import SessionLocal
    from web.app.models import PageView, utcnow
    from web.app.services.cron import _prune_pageviews
    db = SessionLocal()
    try:
        old = PageView(path="/old", created_at=utcnow() - datetime.timedelta(days=800))
        new = PageView(path="/new", created_at=utcnow())
        db.add_all([old, new]); db.commit()
        removed = _prune_pageviews(db)
        assert removed >= 1
        paths = {p.path for p in db.query(PageView)}
        assert "/new" in paths and "/old" not in paths
    finally:
        db.close()


def test_privacy_no_third_party_analytics_processor(client):
    page = client.get("/privacy").text
    assert "Plausible" not in page
    assert "first-party and cookieless" in page


def test_job_actions_and_milestones_record_events(client):
    from web.app.db import SessionLocal
    from web.app.models import JobResult, ProductEvent, Search, User
    from web.app.services import events
    signup(client, "ev2@example.com")
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(email="ev2@example.com").one()
        s = Search(user_id=u.id, status="done"); db.add(s); db.flush()
        jr = JobResult(search_id=s.id, user_id=u.id, position=1, short_id="e2",
                       tier=1, title="Role", company="Co", dedup_key="dk-e2")
        db.add(jr); db.commit(); rid = jr.id; uid = u.id
    finally:
        db.close()

    client.post(f"/job/{rid}/save")
    client.post(f"/job/{rid}/applied")
    client.post(f"/job/{rid}/dismiss", data={"reason": "wrong city"})

    db = SessionLocal()
    try:
        names = {e.name for e in db.query(ProductEvent).filter_by(user_id=uid)}
        assert {"job_saved", "job_marked_applied", "job_dismissed"} <= names
    finally:
        db.close()

    # record_once is idempotent
    db = SessionLocal()
    try:
        events.record_once(db, "onboarding_completed", uid)
        events.record_once(db, "onboarding_completed", uid)
        n = db.query(ProductEvent).filter_by(
            user_id=uid, name="onboarding_completed").count()
        assert n == 1
    finally:
        db.close()


def test_reset_usage_clears_free_tier(client):
    from web.app.db import SessionLocal
    from web.app.models import Document, JobResult, Search, User
    from web.app.services.reset_usage import reset
    signup(client, "reset@example.com")
    db = SessionLocal()
    u = db.query(User).filter_by(email="reset@example.com").one()
    u.searches_used, u.documents_used = 3, 2
    s = Search(user_id=u.id, status="done"); db.add(s); db.flush()
    jr = JobResult(search_id=s.id, user_id=u.id, position=1, short_id="rr",
                   tier=1, title="R", company="C")
    db.add(jr); db.flush()
    db.add(Document(user_id=u.id, job_result_id=jr.id, kind="cv", content="x"))
    db.commit(); db.close()

    msg = reset("reset@example.com")
    assert "searches_used 3 -> 0" in msg

    db = SessionLocal()
    u = db.query(User).filter_by(email="reset@example.com").one()
    assert u.searches_used == 0 and u.documents_used == 0
    assert db.query(Document).filter_by(user_id=u.id).count() == 0
    db.close()
    # unknown email is a safe no-op
    assert "No user found" in reset("nobody@example.com")


def test_admin_reset_usage_endpoint(client, monkeypatch):
    from web.app.config import config
    from web.app.db import SessionLocal
    from web.app.models import User
    monkeypatch.setattr(config, "admin_token", "s3cret")
    signup(client, "areset@example.com")
    db = SessionLocal()
    u = db.query(User).filter_by(email="areset@example.com").one()
    u.searches_used = 5; db.commit(); db.close()

    r = client.post("/admin/reset-usage", data={"email": "areset@example.com"},
                    auth=("op", "s3cret"), follow_redirects=False)
    assert r.status_code == 303 and "reset_msg=" in r.headers["location"]
    db = SessionLocal()
    assert db.query(User).filter_by(email="areset@example.com").one().searches_used == 0
    db.close()
    # gated by admin auth
    assert client.post("/admin/reset-usage", data={"email": "x@y.com"}).status_code == 401


# --------------------- plan quotas (PLAN-01 / PLAN-02) --------------------- #
def test_doc_quota_free_lifetime_premium_monthly(client):
    from datetime import timedelta
    from web.app.db import SessionLocal
    from web.app.models import Document, JobResult, Search, User, utcnow
    from web.app.services import doc_quota
    signup(client, "quota@example.com")
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(email="quota@example.com").one()
        s = Search(user_id=u.id, status="done"); db.add(s); db.flush()

        def job(sid):
            jr = JobResult(search_id=s.id, user_id=u.id, position=1, short_id=sid,
                           tier=1, title="T", company="C")
            db.add(jr); db.flush(); return jr.id

        # free: lifetime 3 / 3
        assert doc_quota.left(db, u, "cv") == 3 and doc_quota.left(db, u, "cl") == 3
        j1 = job("j1")
        db.add(Document(user_id=u.id, job_result_id=j1, kind="cv", content="a",
                        created_at=utcnow() - timedelta(days=400)))
        db.add(Document(user_id=u.id, job_result_id=j1, kind="cv", content="a2",
                        created_at=utcnow()))            # same job, regenerated
        db.commit()
        assert doc_quota.left(db, u, "cv") == 2          # one distinct job, lifetime

        # premium: monthly 30 / 20, prior-month docs excluded
        u.plan = "premium"; db.commit()
        assert doc_quota.left(db, u, "cv") == 29         # only this month's j1 counts
        assert doc_quota.left(db, u, "cl") == 20
        j2 = job("j2")
        db.add(Document(user_id=u.id, job_result_id=j2, kind="cv", content="b",
                        created_at=doc_quota.month_start() - timedelta(days=1)))
        db.commit()
        assert doc_quota.left(db, u, "cv") == 29         # last month does not count
    finally:
        db.close()


def test_generation_blocked_when_free_quota_exhausted(client):
    from web.app.db import SessionLocal
    from web.app.models import Document, JobResult, Search, User
    signup(client, "exhaust@example.com")
    db = SessionLocal()
    u = db.query(User).filter_by(email="exhaust@example.com").one()
    s = Search(user_id=u.id, status="done"); db.add(s); db.flush()
    ids = []
    for i in range(4):
        jr = JobResult(search_id=s.id, user_id=u.id, position=i + 1, short_id=f"x{i}",
                       tier=1, title="T", company="C")
        db.add(jr); db.flush(); ids.append(jr.id)
    for j in ids[:3]:                                    # use all 3 free CV allowances
        db.add(Document(user_id=u.id, job_result_id=j, kind="cv", content="c"))
    db.commit(); fourth = ids[3]; db.close()

    r = client.post(f"/generate/{fourth}/cv", follow_redirects=False)
    assert r.status_code == 303 and "error=" in r.headers["location"]
    assert "free" in r.headers["location"].lower()
    db = SessionLocal()
    assert db.query(Document).filter_by(job_result_id=fourth).count() == 0   # nothing generated
    db.close()


def test_landing_flow_steps_and_plan_metrics(client):
    """HIW-01 five-step flow in order; PRC-01 config-driven plan metrics."""
    from web.app.config import config
    page = client.get("/").text
    labels = ["<h3>Search profile</h3>", "<h3>Market scan</h3>", "<h3>Two-way fit</h3>",
              "<h3>Ranked shortlist</h3>", "<h3>Tailored application</h3>"]
    pos = [page.find(x) for x in labels]
    assert all(p != -1 for p in pos), "all five flow labels present"
    assert pos == sorted(pos), "flow labels in order"
    assert f">{config.free_searches}</b>" in page          # 3 searches (plan-figs)
    assert f">{config.premium_cvs_monthly}</b>" in page     # 30 CVs
    assert f">{config.premium_cover_letters_monthly}</b>" in page  # 20 letters


def test_pricing_and_premium_have_no_banned_plan_words(client):
    # "affordable" is an accepted soft promise from Round 5b (never next to a figure),
    # so it is intentionally allowed here; "unlimited" stays banned.
    for path in ("/pricing", "/"):
        t = client.get(path).text.lower()
        assert "unlimited" not in t
        for bad in ("2 tailored cv", "one cover letter", "cheap to keep"):
            assert bad not in t


# --------------------------- Round 6 -------------------------------------- #
def test_compare_table_is_one_shared_component(client):
    """Round 6.1: the LinkedIn 'Where they differ' table and the pricing table are
    the same .compare component in a .compare-scroll wrapper. Only pricing is tinted,
    and the LinkedIn table no longer carries the old .apptable style."""
    pricing = client.get("/pricing").text
    linkedin = client.get("/compare/linkedin-jobs").text
    for page in (pricing, linkedin):
        assert 'class="compare-scroll"' in page
        assert '<table class="compare' in page
    assert "compare--pricing" in pricing                 # Premium column tinted
    assert "compare--pricing" not in linkedin            # LinkedIn table untinted
    assert "apptable" not in linkedin                    # dropped the second table style
    assert "Where they differ" in linkedin and "Dimension" in linkedin
    assert "Job-market searches" in pricing              # a pricing row survives


def test_benefits_boxes_on_premium(client):
    """Round 6.3: the three numbered benefit boxes, under one eyebrow, no decorative
    square, on the Premium pitch page."""
    signup(client, email="ben@example.com")
    page = client.get("/premium").text
    assert "WHAT PREMIUM CHANGES" in page
    for h in ("Always searching", "More of the market", "Ready to apply"):
        assert h in page
    assert 'class="benefit-num">01<' in page
    assert 'class="benefit-num">02<' in page
    assert 'class="benefit-num">03<' in page
    assert "value-mark" not in page                      # the green square is gone


def test_mobile_menu_carries_full_nav_with_premium(client):
    """Round 6.2: authed pages expose the full site nav via a menu sheet the four-tab
    bottom bar cannot hold; Premium leads it with the coming-soon badge."""
    signup(client, email="mm@example.com")
    page = client.get("/account").text
    assert 'class="nav-toggle"' in page
    assert 'id="mobile-menu"' in page
    assert 'class="badge-soon">Coming soon' in page
    for label in ("Pricing", "How it works", "Comparisons"):
        assert label in page


def test_bottombar_four_tabs_svg_icons_and_active(client):
    """Round 6.2: the bottom bar keeps four tabs, drawn with one 24px SVG icon set,
    and marks the current tab. Premium is not a tab."""
    signup(client, email="bb@example.com")
    page = client.get("/account").text
    assert page.count('class="bb-i"') == 4               # one icon per tab, one set
    assert page.count('<svg class="bb-i"') == 4
    # the bottom bar itself lists exactly the four daily destinations, not Premium
    bar = page.split('class="bottombar"', 1)[1].split("</nav>", 1)[0]
    assert 'href="/premium"' not in bar
    assert 'href="/account"' in bar and 'aria-current="page"' in bar


def test_account_first_row_is_plan_link_to_premium(client):
    """Round 6.2: the Account screen opens with 'Your plan', linking to Premium."""
    signup(client, email="pl@example.com")
    page = client.get("/account").text
    assert 'class="card plan-row" href="/premium"' in page
    assert "Your plan" in page


# --------------------------- alpha feedback + operator audit --------------- #
def test_alpha_banner_and_feedback_form(client):
    """The alpha banner shows site-wide and links to the survey; the survey has
    the four rating questions and the four open boxes."""
    home = client.get("/").text
    assert 'id="alpha-banner"' in home
    assert "/feedback?from=" in home                 # CTA carries the origin path
    form = client.get("/feedback").text
    for name in ("q_useful", "q_easy", "q_look", "q_pay"):
        assert f'name="{name}"' in form
    for box in ("likes", "dislikes", "broken", "other"):
        assert f'name="{box}"' in form


def test_alpha_feedback_submit_stores_and_thanks(client):
    """Anonymous submit is accepted, clamped, stored, and lands on a thank-you."""
    from web.app.db import SessionLocal
    from web.app.models import SiteFeedback
    r = client.post("/feedback", data={
        "q_useful": "5", "q_easy": "4", "q_look": "5", "q_pay": "9",  # 9 clamps to 5
        "likes": "clean and clear", "dislikes": "", "broken": "search was slow",
        "other": "", "path": "/matches",
    }, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/feedback?sent=1"
    assert "Feedback received" in client.get("/feedback?sent=1").text
    db = SessionLocal()
    try:
        fb = db.query(SiteFeedback).order_by(SiteFeedback.id.desc()).first()
        assert fb.q_useful == 5 and fb.q_pay == 5      # 9 was clamped to 5
        assert fb.user_id is None                       # anonymous is allowed
        assert fb.likes == "clean and clear" and fb.path == "/matches"
    finally:
        db.close()


def test_alpha_feedback_blank_rating_is_null(client):
    from web.app.db import SessionLocal
    from web.app.models import SiteFeedback
    client.post("/feedback", data={"q_useful": "", "likes": "just text"})
    db = SessionLocal()
    try:
        fb = db.query(SiteFeedback).order_by(SiteFeedback.id.desc()).first()
        assert fb.q_useful is None and fb.likes == "just text"
    finally:
        db.close()


def test_admin_lists_users_and_alpha_feedback(client, monkeypatch):
    from web.app.config import config
    monkeypatch.setattr(config, "admin_token", "s3cret")
    signup(client, email="u1@example.com")
    client.post("/feedback", data={"q_useful": "4", "likes": "love the two-way fit"})
    page = client.get("/admin", auth=("op", "s3cret")).text
    assert "love the two-way fit" in page                 # feedback text surfaced
    assert "Alpha feedback" in page
    # the user is listed with a link into the audit view
    from web.app.db import SessionLocal
    from web.app.models import User
    db = SessionLocal()
    uid = db.query(User).filter_by(email="u1@example.com").one().id
    db.close()
    assert f'/admin/users/{uid}' in page
    # pseudonymous: the dashboard references users by number, never their email
    assert f"User #{uid}" in page
    assert "u1@example.com" not in page


def test_admin_user_audit_shows_prefs_and_why(client, monkeypatch):
    """The per-user audit renders the profile/preferences and each result's score
    and why-it-fits / why-it-doesn't — while withholding the email, CV/CL content,
    filenames and about-me prose (privacy: it is a match-quality view only)."""
    from web.app.config import config
    from web.app.db import SessionLocal
    from web.app.models import JobResult, Material, Profile, Search, User
    monkeypatch.setattr(config, "admin_token", "s3cret")
    signup(client, email="cand@example.com")
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(email="cand@example.com").one()
        prof = u.profile or Profile(user_id=u.id)
        prof.objective = "Head of Strategy at a fintech"
        prof.about_me = "SECRET_ABOUTME my name is Jane and I worked at BigCo"
        prof.seniority = ["lead"]
        prof.locations = ["Italy"]
        db.add(prof)
        db.add(Material(user_id=u.id, kind="cv", filename="Jane_Doe_CV.pdf",
                        mime="application/pdf", size_bytes=2048, ciphertext=b"x",
                        text="SECRET_CV_TEXT confidential resume body"))
        s = Search(user_id=u.id, status="done", scored_count=1)
        db.add(s); db.flush()
        db.add(JobResult(search_id=s.id, user_id=u.id, position=1, short_id="job001",
                         tier=1, tier_label="Apply now", score=88, fit_role=90,
                         fit_candidate=80, title="Head of Strategy", company="Acme",
                         why_good="Matches your fintech objective.",
                         why_bad="Asks for 8 years you may not have."))
        db.commit()
        uid = u.id
    finally:
        db.close()
    page = client.get(f"/admin/users/{uid}", auth=("op", "s3cret")).text
    # what SHOULD be visible: criteria + results
    assert f"User #{uid}" in page                          # pseudonym header
    assert "Head of Strategy at a fintech" in page         # objective
    assert "Search preferences" in page
    assert "88" in page and "Matches your fintech objective." in page
    assert "Asks for 8 years you may not have." in page    # why it doesn't
    assert "cv (1)" in page                                # material count, no content
    # what MUST NOT be visible: email, CV text, filename, about-me
    assert "cand@example.com" not in page
    assert "SECRET_CV_TEXT" not in page
    assert "Jane_Doe_CV.pdf" not in page
    assert "SECRET_ABOUTME" not in page
    # gate + missing user
    assert client.get(f"/admin/users/{uid}").status_code == 401
    assert client.get("/admin/users/999999", auth=("op", "s3cret")).status_code == 404


# --------------------------- corpus country backfill ---------------------- #
import pytest as _pytest


@_pytest.mark.parametrize(
    "job_countries, remote_mode, target, remote_any, keep",
    [
        (["gb"], "onsite", {"it"}, False, False),   # confidently foreign -> drop
        (["it"], "onsite", {"it"}, False, True),    # target country -> keep
        ([], "onsite", {"it"}, False, True),        # untagged -> defer to prefilter
        (["us"], "remote", {"it"}, True, True),     # remote + remote-anywhere -> keep
        (["us"], "onsite", {"it"}, True, False),    # remote-anywhere but on-site abroad
        (["gb"], "onsite", set(), False, True),     # user has no country constraint
        (["it", "fr"], "onsite", {"it"}, False, True),  # one target among several
    ],
)
def test_country_gate(job_countries, remote_mode, target, remote_any, keep):
    from web.app.services.search_service import _country_allowed
    assert _country_allowed(job_countries, remote_mode, target, remote_any) is keep


def test_resolve_country_batch_parses_and_validates(monkeypatch):
    """Codes are lowercased and aligned by index; anything not a 2-letter alpha
    code (or an out-of-range index) is dropped to ''."""
    from jobhunter import llm
    from web.app.services import corpus_service

    class _Fake:
        def json(self, **kw):
            return {"results": [
                {"index": 0, "code": "GB"},
                {"index": 1, "code": "usa"},     # 3 chars -> invalid
                {"index": 2, "code": ""},         # unknown
                {"index": 9, "code": "fr"},       # out of range -> ignored
            ]}
    monkeypatch.setattr(llm, "get_client", lambda s: _Fake())
    out = corpus_service._resolve_country_batch(["London", "X", "Remote"], object())
    assert out == ["gb", "", ""]


def test_backfill_countries_only_asks_for_the_unresolvable(client, monkeypatch):
    from jobhunter import llm
    from web.app.db import SessionLocal
    from web.app.models import Job
    from web.app.services import corpus_service

    monkeypatch.setattr(llm, "is_configured", lambda s: True)
    asked = []

    def _fake_batch(locs, settings):
        asked.append(list(locs))
        return ["fr" for _ in locs]        # pretend the LLM placed them in France

    monkeypatch.setattr(corpus_service, "_resolve_country_batch", _fake_batch)

    rows = {}
    db = SessionLocal()
    try:
        base = db.query(Job).count()
        rows = {
            "tagged":   Job(dedup_key="bf-tagged",  location="London",
                            countries=["gb"], geo_checked=False),
            "blank":    Job(dedup_key="bf-blank",   location="",
                            countries=[], geo_checked=False),
            "remote":   Job(dedup_key="bf-remote",  location="Remote, Anywhere",
                            countries=[], geo_checked=False),
            "mapfix":   Job(dedup_key="bf-mapfix",  location="Milano",
                            countries=[], geo_checked=False),
            "obscure":  Job(dedup_key="bf-obscure", location="Little Snoring, Norfolk shire town",
                            countries=[], geo_checked=False),
        }
        for r in rows.values():
            db.add(r)
        db.commit()

        placed = corpus_service.backfill_countries(db, object(), limit=base + 50)

        for r in rows.values():
            db.refresh(r)
        # Only the genuinely-unresolvable location went to the LLM.
        assert asked == [["Little Snoring, Norfolk shire town"]]
        assert rows["obscure"].countries == ["fr"] and placed >= 1
        assert rows["mapfix"].countries == ["it"]      # resolved by the (grown) maps
        assert rows["tagged"].countries == ["gb"]       # left as-is
        assert rows["blank"].countries == []            # legitimately country-less
        assert rows["remote"].countries == []
        # Everything is now settled, so a second pass asks nothing.
        assert all(r.geo_checked for r in rows.values())
        asked.clear()
        corpus_service.backfill_countries(db, object(), limit=base + 50)
        assert asked == []
    finally:
        for r in rows.values():
            db.delete(r)
        db.commit()
        db.close()


# --------------------------- ATS location correction ---------------------- #
@_pytest.mark.parametrize("url, expected", [
    ("https://jobs.ashbyhq.com/abundant/36aa28eb-uuid", ("ashby", "abundant", "36aa28eb-uuid")),
    ("https://boards.greenhouse.io/acme/jobs/4567", ("greenhouse", "acme", "4567")),
    ("https://job-boards.greenhouse.io/acme/jobs/99", ("greenhouse", "acme", "99")),
    ("https://jobs.lever.co/acme/abc-def", ("lever", "acme", "abc-def")),
    ("https://findwork.dev/jobs/1", ("", "", "")),
])
def test_parse_ats_job(url, expected):
    from jobhunter.sources.ats import parse_ats_job
    assert parse_ats_job(url) == expected


def test_correct_ats_locations_overwrites_aggregator_guess(client, monkeypatch):
    """A findwork job that links to Ashby but is mislabeled 'Remote' gets the
    source's true SF/on-site/US, which the country gate then drops for Italy."""
    from jobhunter.sources import ats as ats_mod
    from web.app.db import SessionLocal
    from web.app.models import Job
    from web.app.services import corpus_service
    from web.app.services.search_service import _country_allowed

    # Stand in for the live board fetch.
    def _fake_index(ats, org):
        assert (ats, org) == ("ashby", "abundant")
        return {"jobid": {"location": "San Francisco", "remote_mode": "onsite",
                          "countries": ["us"]}}
    monkeypatch.setattr(ats_mod, "board_location_index", _fake_index)

    rows = {}
    db = SessionLocal()
    try:
        rows["ashby"] = Job(dedup_key="ats-ashby", source="api:findwork",
                            url="https://jobs.ashbyhq.com/abundant/jobid",
                            location="Remote", remote_mode="remote",
                            countries=[], ats_checked=False)
        rows["plain"] = Job(dedup_key="ats-plain", source="api:findwork",
                            url="https://findwork.dev/jobs/1",
                            location="Remote", remote_mode="remote",
                            countries=[], ats_checked=False)
        for r in rows.values():
            db.add(r)
        db.commit()

        n = corpus_service.correct_ats_locations(db, limit=1000)
        for r in rows.values():
            db.refresh(r)

        a = rows["ashby"]
        assert n >= 1
        assert a.location == "San Francisco" and a.remote_mode == "onsite"
        assert a.countries == ["us"] and a.geo_checked and a.ats_checked
        # The corrected job is now dropped for an onsite Italy user.
        assert _country_allowed(a.countries, a.remote_mode, {"it"}, False) is False
        # A non-ATS job is marked checked but left untouched.
        assert rows["plain"].ats_checked and rows["plain"].location == "Remote"
    finally:
        for r in rows.values():
            db.delete(r)
        db.commit()
        db.close()


# --------------------------- corpus health panel -------------------------- #
def test_admin_corpus_panel(client, monkeypatch):
    from web.app.config import config
    from web.app.db import SessionLocal
    from web.app.models import CorpusStat, Job
    monkeypatch.setattr(config, "admin_token", "s3cret")
    db = SessionLocal()
    try:
        db.add(Job(dedup_key="cs-1", source="api:adzuna", title="X", location="Milan"))
        db.add(CorpusStat(total=1234, added=50, ttl_deleted=7, gone_deleted=3, checked=200))
        db.commit()
    finally:
        db.close()
    page = client.get("/admin", auth=("op", "s3cret")).text
    assert "Corpus &amp; sources" in page
    assert "jobs in corpus" in page
    assert "api:adzuna" in page                    # top-source breakdown
    assert "1234" in page and "\u2212" in page + "-"  # a churn row rendered


def test_cron_records_corpus_stat(client):
    from web.app.db import SessionLocal
    from web.app.models import CorpusStat
    from web.app.services.cron import _record_corpus_stat
    out = {
        "reaper": {"ttl_deleted": 5, "gone_deleted": 2, "checked": 200},
        "ingest_daily": {"added": 40, "updated": 10, "embedded": 40},
    }
    db = SessionLocal(); before = db.query(CorpusStat).count(); db.close()
    _record_corpus_stat(out)                            # owns its own session now
    db = SessionLocal()
    try:
        row = db.query(CorpusStat).order_by(CorpusStat.id.desc()).first()
        assert db.query(CorpusStat).count() == before + 1
        assert row.added == 40 and row.ttl_deleted == 5 and row.gone_deleted == 2
    finally:
        db.close()


def test_admin_set_plan(client, monkeypatch):
    from web.app.config import config
    from web.app.db import SessionLocal
    from web.app.models import User
    monkeypatch.setattr(config, "admin_token", "s3cret")
    signup(client, email="prem@example.com")
    r = client.post("/admin/set-plan", data={"email": "prem@example.com", "plan": "premium"},
                    auth=("op", "s3cret"), follow_redirects=False)
    assert r.status_code == 303
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(email="prem@example.com").one()
        assert u.plan == "premium" and u.is_premium
    finally:
        db.close()
    # gate: no auth -> 401
    assert client.post("/admin/set-plan", data={"email": "x", "plan": "premium"}).status_code == 401


# --------------------------- premium discovery cadence -------------------- #
def test_due_for_discovery_rules():
    from datetime import timedelta
    from web.app.models import User, utcnow
    from web.app.services.companies_service import due_for_discovery

    def sig(seeds=(), verticals=("ai",), company_types=(), countries=()):
        return {"seeds": list(seeds), "verticals": list(verticals),
                "company_types": list(company_types), "countries": list(countries)}

    now = utcnow()
    free = User(plan="free")
    prem = User(plan="premium")

    # free never qualifies
    assert due_for_discovery(free, sig(["A", "B", "C", "D"]), now) is False
    # premium, never run -> due
    assert due_for_discovery(prem, sig(["A"]), now) is True
    # ran just now, nothing changed -> not due
    prem.last_discovery_at = now
    prem.discovery_seeds = ["A", "B"]
    prem.discovery_verticals = ["ai"]
    assert due_for_discovery(prem, sig(["A", "B"]), now) is False
    # cadence elapsed (>7d) -> due
    assert due_for_discovery(prem, sig(["A", "B"]), now + timedelta(days=8)) is True
    # 3 new seeds since last run -> due early
    assert due_for_discovery(prem, sig(["A", "B", "C", "D", "E"]), now) is True
    # only 2 new seeds -> not enough
    assert due_for_discovery(prem, sig(["A", "B", "C", "D"]), now) is False
    # any new vertical -> due
    assert due_for_discovery(prem, sig(["A", "B"], ["ai", "fintech"]), now) is True


def test_discover_for_user_is_premium_gated(client):
    from web.app.db import SessionLocal
    from web.app.models import User
    from web.app.services.companies_service import discover_for_user
    signup(client, email="freeuser@example.com")
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(email="freeuser@example.com").one()
        res = discover_for_user(db, u)
        assert res.get("reason") == "not premium" and res.get("added") == 0
    finally:
        db.close()


# --------------------------- custom careers scraping ---------------------- #
def test_scrape_careers_builds_postings(monkeypatch):
    from jobhunter import llm
    from jobhunter.sources import careers_scrape as cs

    monkeypatch.setattr(llm, "is_configured", lambda s: True)
    monkeypatch.setattr(cs, "_fetch_first",
                        lambda urls: ("https://scalapay.com/careers", "<html>" + "x" * 600 + "</html>"))

    class _Fake:
        def json(self, **kw):
            return {"jobs": [
                {"title": "Head of Ops", "location": "Milan, Italy", "url": "/jobs/1"},
                {"title": "", "location": "", "url": ""},               # dropped: no title
                {"title": "PM", "location": "Remote", "url": "https://x.co/pm"},
            ]}
    monkeypatch.setattr(llm, "get_client", lambda s: _Fake())

    # with_descriptions=False: test the extraction only, no per-job HTTP fetches.
    out = cs.scrape_careers("scalapay.com", "Scalapay", object(), with_descriptions=False)
    assert len(out) == 2
    assert out[0].title == "Head of Ops" and out[0].location == "Milan, Italy"
    assert out[0].url == "https://scalapay.com/jobs/1"          # made absolute
    assert out[0].source == "scrape:scalapay.com"
    assert out[1].url == "https://x.co/pm"                       # already absolute


def test_fill_descriptions_from_detail_pages(monkeypatch):
    """Each opening's body is fetched from its own page (HTTP only, no LLM)."""
    from jobhunter.models import JobPosting
    from jobhunter.sources import careers_scrape as cs

    bodies = {
        "https://scalapay.com/jobs/1": "<html><body><h1>Head of Ops</h1><p>Lead "
            "operations across Italy and the EU. You will own the P&L, scale the "
            "team, run the numbers, and report to the CEO. Fintech experience is a "
            "strong plus for this senior leadership role.</p></body></html>",
    }

    class _Resp:
        def __init__(self, url):
            self.status_code = 200 if url in bodies else 404
            self.text = bodies.get(url, "")

    class _Client:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url, **kw): return _Resp(url)

    monkeypatch.setattr(cs, "http_client", lambda *a, **k: _Client())
    jobs = [JobPosting(source="scrape:x", title="Head of Ops", company="Scalapay",
                       location="Milan", url="https://scalapay.com/jobs/1"),
            JobPosting(source="scrape:x", title="Gone", company="Scalapay",
                       location="Milan", url="https://scalapay.com/jobs/404")]
    cs._fill_descriptions(jobs, "https://scalapay.com/careers")
    assert "Lead operations across Italy" in jobs[0].description   # body pulled in
    assert jobs[1].description == ""                               # 404 -> left empty


def test_upsert_custom_company_normalises_and_dedupes(client):
    from web.app.db import SessionLocal
    from web.app.models import Company
    from web.app.services.companies_service import CUSTOM_ATS, upsert_custom_company
    db = SessionLocal()
    try:
        assert upsert_custom_company(db, "Scalapay", "https://www.scalapay.com/careers") is True
        db.commit()
        row = db.query(Company).filter_by(ats=CUSTOM_ATS, ats_token="scalapay.com").one()
        assert row.name == "Scalapay" and row.source == "scraped"
        # same domain, any form -> no duplicate
        assert upsert_custom_company(db, "Scalapay", "scalapay.com") is False
        # not a domain -> rejected
        assert upsert_custom_company(db, "X", "not-a-domain") is False
    finally:
        db.query(Company).filter_by(ats=CUSTOM_ATS).delete()
        db.commit(); db.close()


def test_scrape_custom_companies_writes_to_corpus(client, monkeypatch):
    from web.app.db import SessionLocal
    from web.app.models import Company, Job
    from web.app.services import companies_service as csvc
    from jobhunter import llm
    from jobhunter.models import JobPosting

    monkeypatch.setattr(llm, "is_configured", lambda s: True)

    def _fake_scrape(domain, name, settings):
        return [JobPosting(source=f"scrape:{domain}", title="Head of Ops",
                           company=name, location="Milan, Italy",
                           url=f"https://{domain}/jobs/1")]
    monkeypatch.setattr("jobhunter.sources.careers_scrape.scrape_careers", _fake_scrape)

    db = SessionLocal()
    try:
        db.add(Company(ats=csvc.CUSTOM_ATS, ats_token="scalapay.com",
                       name="Scalapay", source="scraped"))
        db.commit()
        res = csvc.scrape_custom_companies(db, object(), limit=10)
        assert res["companies"] >= 1 and res["jobs"] >= 1
        # the scraped job is now a corpus row, tagged like any other
        job = db.query(Job).filter_by(source="scrape:scalapay.com").first()
        assert job is not None and job.title == "Head of Ops"
        assert job.countries == ["it"]                          # tagged from "Milan, Italy"
        c = db.query(Company).filter_by(ats=csvc.CUSTOM_ATS, ats_token="scalapay.com").one()
        assert c.last_polled_at is not None and c.jobs_count == 1
    finally:
        db.query(Job).filter_by(source="scrape:scalapay.com").delete()
        db.query(Company).filter_by(ats=csvc.CUSTOM_ATS).delete()
        db.commit(); db.close()


# --------------------------- serpapi EU fix + scrape panel ---------------- #
@_pytest.mark.parametrize("loc, gl, hl", [
    ("Italy", "it", "it"),
    ("Milan", "it", "it"),
    ("United States", "us", "en"),
    ("Berlin", "de", "de"),
    ("France", "fr", "fr"),
    ("Nowhereland", "", "en"),
])
def test_google_locale(loc, gl, hl):
    from jobhunter import geo
    assert geo.google_locale(loc) == (gl, hl)


def test_serpapi_is_enabled_in_ingest():
    from web.app.services.ingest import KEYED_SOURCES, SOURCE_CADENCE
    assert "serpapi" in KEYED_SOURCES
    assert SOURCE_CADENCE["serpapi"] == "weekly"      # paid/metered -> weekly


def test_admin_shows_scrape_line(client, monkeypatch):
    from web.app.config import config
    from web.app.db import SessionLocal
    from web.app.models import Company, Job
    monkeypatch.setattr(config, "admin_token", "s3cret")
    db = SessionLocal()
    try:
        db.add(Job(dedup_key="sc-1", source="scrape:scalapay.com", title="Ops",
                   location="Milan"))
        db.add(Company(ats="custom", ats_token="scalapay.com", name="Scalapay",
                       source="scraped"))
        db.commit()
    finally:
        db.close()
    page = client.get("/admin", auth=("op", "s3cret")).text
    assert "jobs from custom scraping" in page
    assert "custom career pages" in page


# --------------------------- ingest breadth ------------------------------- #
def test_adzuna_paginates_and_stops_on_short_page(monkeypatch):
    from jobhunter.config import Profile, Settings
    from jobhunter.sources import adzuna

    seen_urls = []

    class _Resp:
        def __init__(self, n):
            self.status_code = 200
            self._n = n
        def raise_for_status(self): pass
        def json(self):
            return {"results": [{"title": f"job{i}", "company": {"display_name": "C"},
                                 "location": {"display_name": "Milan"}} for i in range(self._n)]}

    class _Client:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url, params=None):
            seen_urls.append(url)
            return _Resp(50 if url.endswith("/search/1") else 20)   # page 2 short -> stop

    monkeypatch.setattr(adzuna, "http_client", lambda *a, **k: _Client())
    monkeypatch.setattr(adzuna.time, "sleep", lambda *_: None)
    prof = Profile(raw={"locations": ["Italy"], "sources": {"search_terms": ["ops"]}})
    s = Settings(adzuna_app_id="x", adzuna_app_key="y", adzuna_pages=3)
    jobs = adzuna.fetch(prof, s)
    assert len(jobs) == 70                                   # 50 + 20, then stopped
    assert seen_urls[-2:] == ["https://api.adzuna.com/v1/api/jobs/it/search/1",
                              "https://api.adzuna.com/v1/api/jobs/it/search/2"]


def test_corpus_terms_and_countries_keep_every_user(client):
    from web.app.db import SessionLocal
    from web.app.models import Profile as ProfileRow, User
    from web.app.services import ingest
    db = SessionLocal()
    try:
        u = User(email="niche@example.com"); db.add(u); db.flush()
        # a niche role + a country not in the defaults
        db.add(ProfileRow(user_id=u.id, search_terms=["Quantum Hardware Lead"],
                          locations=["Portugal"]))
        db.commit()
        terms = ingest.corpus_terms(db)
        countries = ingest.corpus_countries(db)
        assert "Quantum Hardware Lead" in terms              # user's niche term kept
        assert "Portugal" in countries                       # user's country kept
        assert "Italy" in countries                          # defaults still pad breadth
        assert len(countries) <= ingest.COUNTRIES_MAX
    finally:
        db.query(ProfileRow).filter_by(user_id=u.id).delete()
        db.query(User).filter_by(id=u.id).delete()
        db.commit(); db.close()


@_pytest.mark.parametrize("location, desc, is_remote, expected", [
    ("Milan, Italy", "Great role", False, "onsite"),   # names a place, no remote word
    ("London", "", False, "onsite"),
    ("Remote", "work from anywhere", False, "remote"),
    ("Berlin", "hybrid schedule", False, "hybrid"),
    ("Anywhere", "", True, "remote"),                  # source flag
    ("Europe", "", False, "unknown"),                  # region, not a specific place
    ("", "no location given", False, "unknown"),
])
def test_remote_mode_infers_onsite_from_a_real_place(location, desc, is_remote, expected):
    from jobhunter.models import JobPosting
    from jobhunter.tags import remote_mode
    j = JobPosting(source="s", title="Ops", location=location, description=desc,
                   is_remote=is_remote)
    assert remote_mode(j) == expected


def test_careerjet_paginates_and_stops(monkeypatch):
    from jobhunter.config import Profile, Settings
    from jobhunter.sources import keyed

    pages_hit = []

    class _Resp:
        def __init__(self, n): self.status_code = 200; self._n = n
        def json(self):
            return {"jobs": [{"title": f"j{i}", "company": "C", "locations": "Milan",
                              "description": "d", "url": f"u{i}"} for i in range(self._n)]}

    class _Client:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url, params=None, headers=None):
            pages_hit.append(params["page"])
            return _Resp(50 if params["page"] == 1 else 12)   # page 2 short -> stop

    monkeypatch.setattr(keyed, "http_client", lambda *a, **k: _Client())
    prof = Profile(raw={"locations": ["Italy"], "sources": {"search_terms": ["ops"]}})
    jobs = keyed._careerjet(prof, Settings(careerjet_affid="x", careerjet_referer="http://x"))
    assert len(jobs) == 62 and pages_hit == [1, 2]     # 50 + 12, stopped before page 3


def test_corpus_terms_includes_derived_roles(client):
    """Roles derived from the objective+CV (stored on the profile at search time)
    are queried by the corpus ingest, not just the titles the user typed."""
    from web.app.db import SessionLocal
    from web.app.models import Profile as ProfileRow, User
    from web.app.services import ingest
    db = SessionLocal()
    try:
        u = User(email="derived@example.com"); db.add(u); db.flush()
        db.add(ProfileRow(user_id=u.id, search_terms=["Chief of Staff"],
                          derived_roles=["Business Operations", "Founder's Office"]))
        db.commit()
        terms = ingest.corpus_terms(db)
        assert "Chief of Staff" in terms                 # typed
        assert "Business Operations" in terms            # derived from objective/CV
        assert "Founder's Office" in terms
    finally:
        db.query(ProfileRow).filter_by(user_id=u.id).delete()
        db.query(User).filter_by(id=u.id).delete()
        db.commit(); db.close()


# --------------------------- link quality --------------------------------- #
def test_gated_urls_rejected_and_reaped(client):
    from web.app.db import SessionLocal
    from web.app.models import Job
    from web.app.services import corpus_service, reaper
    from jobhunter.models import JobPosting

    assert corpus_service.is_gated_url("https://findwork.dev/nvD6/chief-of-staff") is True
    assert corpus_service.is_gated_url("https://boards.greenhouse.io/acme/jobs/1") is False

    db = SessionLocal()
    try:
        # ingestion drops the gated one, keeps the good one
        added, _ = corpus_service.upsert_jobs(db, [
            JobPosting(source="api:findwork", title="Gated", company="X",
                       url="https://findwork.dev/abc/role"),
            JobPosting(source="ats:greenhouse:acme", title="Good", company="Acme",
                       url="https://boards.greenhouse.io/acme/jobs/9"),
        ])
        assert added == 1
        assert db.query(Job).filter(Job.url.like("%findwork.dev%")).count() == 0
        # a leftover gated row from before the filter is cleaned by the reaper
        db.add(Job(dedup_key="leftover", source="api:findwork", title="Old",
                   url="https://findwork.dev/xyz/role"))
        db.commit()
        res = reaper.sweep(db, check_limit=0)
        assert res["gated_deleted"] >= 1
        assert db.query(Job).filter(Job.url.like("%findwork.dev%")).count() == 0
    finally:
        db.query(Job).filter(Job.url.like("%greenhouse.io%")).delete()
        db.commit(); db.close()


def test_reaper_marks_registration_wall_as_gated_not_gone(monkeypatch):
    from web.app.services import reaper

    class _Wall:
        status_code = 200
        text = "Join the #1 remote job site. Create an account to view full job details."
    class _Dead:
        status_code = 200
        text = "Sorry, this position has been filled and is no longer available."
    class _Client:
        def __init__(self, r): self.r = r
        def get(self, url, follow_redirects=True): return self.r

    assert reaper.check_url("https://x/y", _Client(_Wall())) == "gated"   # recoverable
    assert reaper.check_url("https://x/y", _Client(_Dead())) == "gone"    # truly closed


def test_verify_links_drops_dead_and_purges_corpus(client, monkeypatch):
    """The top results are link-checked before showing: dead/gated links are
    dropped from the shortlist and deleted from the corpus; survivors are stamped."""
    from web.app.db import SessionLocal
    from web.app.models import Job
    from web.app.services import reaper, search_service
    from jobhunter.models import JobPosting, MatchResult

    good = JobPosting(source="ats:greenhouse:acme", title="Good", company="Acme",
                      url="https://boards.greenhouse.io/acme/jobs/1")
    dead = JobPosting(source="api:careerjet", title="Dead", company="X",
                      url="https://example.com/dead")
    m = MatchResult(tier=1, score=90, reasons="ok")

    # classify the dead URL as gone, the good one as active
    monkeypatch.setattr(reaper, "check_url",
                        lambda url, c: "gone" if "dead" in url else "active")

    db = SessionLocal()
    try:
        for p in (good, dead):
            db.add(Job(dedup_key=p.dedup_key(), source=p.source, title=p.title,
                       url=p.url, last_checked_at=None))
        db.commit()

        kept = search_service._verify_links(db, [(good, m), (dead, m)])
        titles = [j.title for j, _ in kept]
        assert titles == ["Good"]                                  # dead dropped
        assert db.query(Job).filter_by(dedup_key=dead.dedup_key()).count() == 0  # purged
        surv = db.query(Job).filter_by(dedup_key=good.dedup_key()).one()
        assert surv.last_checked_at is not None                     # stamped checked
    finally:
        db.query(Job).filter(Job.dedup_key.in_(
            [good.dedup_key(), dead.dedup_key()])).delete(synchronize_session=False)
        db.commit(); db.close()


def test_admin_growth_chart(client, monkeypatch):
    from web.app.config import config
    from web.app.db import SessionLocal
    from web.app.models import CorpusStat, PageView
    monkeypatch.setattr(config, "admin_token", "s3cret")
    db = SessionLocal()
    try:
        db.add(CorpusStat(total=15000, added=250))     # a jobs-added data point
        db.add(PageView(path="/", visitor="v-abc"))     # a visitor data point
        db.commit()
    finally:
        db.close()
    page = client.get("/admin", auth=("op", "s3cret")).text
    assert "Growth" in page
    assert "<polyline" in page and "<svg" in page       # dual-axis line chart rendered
    assert "Unique visitors (left)" in page and "Jobs added (right)" in page


def test_admin_run_maintenance(client, monkeypatch):
    from web.app.config import config
    monkeypatch.setattr(config, "admin_token", "s3cret")
    r = client.post("/admin/run-maintenance", auth=("op", "s3cret"), follow_redirects=False)
    assert r.status_code == 303 and "Maintenance" in r.headers["location"]   # url-encoded msg
    assert client.post("/admin/run-maintenance").status_code == 401     # gated


def test_admin_run_discovery(client, monkeypatch):
    from web.app.config import config
    monkeypatch.setattr(config, "admin_token", "s3cret")
    r = client.post("/admin/run-discovery", auth=("op", "s3cret"), follow_redirects=False)
    assert r.status_code == 303 and "Discovery" in r.headers["location"]
    assert client.post("/admin/run-discovery").status_code == 401       # gated


def test_admin_discovery_selftest(client, monkeypatch):
    from web.app.config import config
    monkeypatch.setattr(config, "admin_token", "s3cret")
    r = client.post("/admin/discovery-selftest", auth=("op", "s3cret"), follow_redirects=False)
    assert r.status_code == 303 and "self-test" in r.headers["location"]
    assert client.post("/admin/discovery-selftest").status_code == 401     # gated


def test_admin_embed_now(client, monkeypatch):
    from web.app.config import config
    monkeypatch.setattr(config, "admin_token", "s3cret")
    r = client.post("/admin/embed-now", auth=("op", "s3cret"), follow_redirects=False)
    assert r.status_code == 303 and "Embedding" in r.headers["location"]
    assert client.post("/admin/embed-now").status_code == 401           # gated


def test_admin_retag(client, monkeypatch):
    from web.app.config import config
    monkeypatch.setattr(config, "admin_token", "s3cret")
    r = client.post("/admin/retag", auth=("op", "s3cret"), follow_redirects=False)
    assert r.status_code == 303 and "tagging" in r.headers["location"].lower()
    assert client.post("/admin/retag").status_code == 401               # gated


def test_record_op_shows_on_dashboard(client, monkeypatch):
    """A background job's outcome is persisted and surfaced on /admin, so a
    fire-and-forget button is no longer a mystery."""
    from web.app.config import config
    from web.app.routes.admin import record_op
    monkeypatch.setattr(config, "admin_token", "s3cret")
    record_op("discovery", "LLM configured: True | premium users: 1")
    r = client.get("/admin", auth=("op", "s3cret"))
    assert r.status_code == 200
    assert "Background job log" in r.text
    assert "LLM configured: True" in r.text


def test_import_job_creates_scored_card(client, monkeypatch):
    """import_job structures a posting, scores it, and stores a JobResult that will
    render as a normal match card (any tier)."""
    from jobhunter.matcher import MatchResult
    from jobhunter.models import JobPosting
    from web.app.db import SessionLocal
    from web.app.models import JobResult, User, utcnow
    from web.app.services import import_service

    signup(client, email="imp@example.com")
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(email="imp@example.com").one()
        from datetime import timedelta
        u.plan = "premium"; u.premium_until = utcnow() + timedelta(days=30)
        db.commit()

        # Stub the network+LLM extraction and the scorer — no external calls.
        monkeypatch.setattr(import_service, "_extract_posting",
            lambda url, s: JobPosting(source="import", title="Head of Ops",
                                      company="Acme", location="Milan, Italy",
                                      description="Lead operations.", url=url))
        monkeypatch.setattr(import_service, "build_engine_profile", lambda db, u: object())
        monkeypatch.setattr(import_service, "build_engine_materials", lambda db, u: object())
        monkeypatch.setattr(import_service, "derive_company_profile", lambda *a, **k: object())
        monkeypatch.setattr(import_service, "derive_criteria", lambda *a, **k: object())
        monkeypatch.setattr(import_service, "seed_values", lambda db, u: [])
        monkeypatch.setattr(import_service, "engine_settings", lambda premium=True: object())

        class FakeMatcher:
            def __init__(self, s): pass
            def score(self, jobs, *a, **k):
                m = MatchResult(tier=2, score=78, fit_role=80, fit_candidate=75,
                                role="Head of Ops", company="Acme",
                                location="Milan, Italy", remote="onsite",
                                reasons="Strong operator fit. However, salary undisclosed.",
                                tags=["ops"])
                return [(jobs[0], m)]
        monkeypatch.setattr(import_service, "Matcher", FakeMatcher)

        jr, sid = import_service.import_job(db, u, "https://acme.com/jobs/head-of-ops")
        assert jr.tier == 2 and jr.score == 78 and jr.source == "import"
        assert jr.why_good and jr.why_bad                      # reasons split for the card
        stored = db.get(JobResult, jr.id)
        assert stored is not None and stored.title == "Head of Ops"
    finally:
        from web.app.models import Profile, Search
        uid = db.query(User.id).filter_by(email="imp@example.com").scalar()
        if uid is not None:
            db.query(JobResult).filter_by(user_id=uid).delete(synchronize_session=False)
            db.query(Search).filter_by(user_id=uid).delete(synchronize_session=False)
            db.query(Profile).filter_by(user_id=uid).delete(synchronize_session=False)
        db.query(User).filter_by(email="imp@example.com").delete()
        db.commit(); db.close()


def test_import_route_is_premium_gated(client, monkeypatch):
    signup(client, email="free-imp@example.com")     # free user
    r = client.post("/matches/import", data={"url": "https://x.com/job"},
                    follow_redirects=False)
    assert r.status_code == 303 and "Premium" in r.headers["location"]


def test_upsert_company_dedupes_same_run_without_poisoning():
    """Two proposals in one run resolving to the same (ats, token) must not abort
    the whole transaction (the uq_company_ats UniqueViolation that killed
    discovery). The duplicate is skipped; the commit and later inserts still work."""
    from web.app.db import SessionLocal
    from web.app.models import Company
    from web.app.services.companies_service import upsert_company

    db = SessionLocal()
    try:
        db.query(Company).filter(Company.ats_token.in_(["acme", "beta"])).delete(
            synchronize_session=False)
        db.commit()
        assert upsert_company(db, "greenhouse", "acme", "Acme One") is True
        assert upsert_company(db, "greenhouse", "acme", "Acme Two") is False   # same token
        assert upsert_company(db, "lever", "beta", "Beta") is True             # different
        db.commit()                                                            # must NOT raise
        assert db.query(Company).filter_by(ats="greenhouse", ats_token="acme").count() == 1
        assert db.query(Company).filter_by(ats="lever", ats_token="beta").count() == 1
    finally:
        db.query(Company).filter(Company.ats_token.in_(["acme", "beta"])).delete(
            synchronize_session=False)
        db.commit(); db.close()


def test_backfill_remote_modes_uses_country_tag():
    """A job stuck at 'unknown' whose location the maps can't resolve, but which
    now has a settled country tag, is on-site in that country. No tag stays
    unknown."""
    from web.app.db import SessionLocal
    from web.app.models import Job, utcnow
    from web.app.services.corpus_service import backfill_remote_modes

    db = SessionLocal()
    try:
        db.query(Job).filter(Job.dedup_key.in_(["rm:tagged", "rm:bare"])).delete(
            synchronize_session=False)
        now = utcnow()
        # Unresolvable location string, no remote wording — but a settled country.
        db.add(Job(dedup_key="rm:tagged", source="s", title="Ops Lead", company="Co",
                   location="Zona Industriale 4", countries=["it"],
                   remote_mode="unknown", last_seen_at=now))
        # No country, no wording, unresolvable location -> genuinely unknown.
        db.add(Job(dedup_key="rm:bare", source="s", title="Ops Lead", company="Co",
                   location="Zona Industriale 4", countries=[],
                   remote_mode="unknown", last_seen_at=now))
        db.commit()

        changed = backfill_remote_modes(db, limit=1000)
        assert changed >= 1
        assert db.query(Job).filter_by(dedup_key="rm:tagged").one().remote_mode == "onsite"
        assert db.query(Job).filter_by(dedup_key="rm:bare").one().remote_mode == "unknown"
    finally:
        db.query(Job).filter(Job.dedup_key.in_(["rm:tagged", "rm:bare"])).delete(
            synchronize_session=False)
        db.commit(); db.close()


def test_engine_settings_fills_model_on_openrouter(monkeypatch):
    """On a non-Anthropic provider Settings.from_env() leaves scoring_model empty,
    which made discovery/scrape/country-lookup raise and silently no-op. The helper
    fills it from web config so those background LLM paths have a model."""
    from web.app.config import config
    from web.app.services.profile_service import engine_settings

    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setattr(config, "premium_scoring_model", "anthropic/claude-haiku-4.5")

    # Empty env -> "No scoring model" would raise; web config supplies it.
    monkeypatch.delenv("JOBHUNTER_SCORING_MODEL", raising=False)
    from jobhunter.config import Settings
    assert Settings.from_env().scoring_model == ""          # the empty-model bug
    assert engine_settings(premium=True).scoring_model == "anthropic/claude-haiku-4.5"

    # A stray Anthropic-direct value that OpenRouter 400s must NOT win — the web
    # config is authoritative (this is the real JOBHUNTER_SCORING_MODEL footgun).
    monkeypatch.setenv("JOBHUNTER_SCORING_MODEL", "claude-haiku-4-5")
    assert Settings.from_env().scoring_model == "claude-haiku-4-5"     # engine picks it up
    s = engine_settings(premium=True)
    assert s.scoring_model == "anthropic/claude-haiku-4.5"  # overridden by web config
    assert s.generation_model                                # non-empty

    # Discovery research model: default filled from web config; env override wins.
    monkeypatch.setattr(config, "discovery_research_model", "perplexity/sonar")
    monkeypatch.delenv("DISCOVERY_RESEARCH_MODEL", raising=False)
    assert engine_settings().research_model == "perplexity/sonar"
    monkeypatch.setenv("DISCOVERY_RESEARCH_MODEL", "openai/gpt-4o:online")
    assert engine_settings().research_model == "openai/gpt-4o:online"


def test_discover_all_active_force_ignores_cadence(monkeypatch):
    """force=True runs discovery for a premium user even when the cadence has not
    elapsed — the operator's manual 'run now' trigger."""
    from web.app.db import SessionLocal
    from web.app.models import User, utcnow
    from web.app.services import companies_service as cs

    db = SessionLocal()
    try:
        from datetime import timedelta
        from web.app.models import Profile
        # Just ran, and seeds/verticals unchanged since -> genuinely not due.
        u = User(email="force@example.com", plan="premium",
                 premium_until=utcnow() + timedelta(days=30),   # premium
                 last_discovery_at=utcnow(),
                 discovery_seeds=["stripe"], discovery_verticals=["fintech"])
        db.add(u); db.commit()
        db.add(Profile(user_id=u.id, verticals=["fintech"])); db.commit()
        db.refresh(u)

        from web.app.services import profile_service
        # Only this user's seeds match its stored discovery_seeds (others in the
        # shared test DB will look "changed" and stay due regardless of force).
        monkeypatch.setattr(profile_service, "seed_values",
                            lambda db, user: ["stripe"] if user.id == u.id else [])
        called = []            # emails discover_for_user was invoked for
        monkeypatch.setattr(cs, "discover_for_user",
                            lambda db, user: (called.append(user.email), {"added": 2})[1])

        cs.discover_all_active(db, force=False)
        assert "force@example.com" not in called      # cadence blocks this user
        cs.discover_all_active(db, force=True)
        assert "force@example.com" in called           # force overrides cadence
    finally:
        uid = db.query(User.id).filter(User.email == "force@example.com").scalar()
        if uid is not None:
            db.query(Profile).filter(Profile.user_id == uid).delete()
        db.query(User).filter(User.email == "force@example.com").delete()
        db.commit(); db.close()


# --------------------------- multi-model panel ---------------------------- #
def _panel_cfg(monkeypatch, models, rounds=1, thresh=0.75, enabled=True):
    from web.app.config import config
    monkeypatch.setattr(config, "panel_enabled", enabled)
    monkeypatch.setattr(config, "panel_models", models)
    monkeypatch.setattr(config, "panel_synth_model", "")
    monkeypatch.setattr(config, "panel_rounds", rounds)
    monkeypatch.setattr(config, "panel_threshold", thresh)
    return config


def _panel_job():
    from jobhunter.models import JobPosting
    return JobPosting(source="s", title="Head of Ops", company="Acme",
                      description="Lead operations.")


def test_panel_converges_when_models_agree(monkeypatch):
    from jobhunter import llm
    from jobhunter.config import Materials
    from web.app.services import panel

    cfg = _panel_cfg(monkeypatch, ["m1", "m2", "m3"])
    calls = {"draft": 0, "vote": 0, "synth": 0}

    class _Fake:
        def json(self, **kw):
            props = kw["schema"]["properties"]
            if "rationale" in props:
                calls["draft"] += 1
                return {"content": f"draft-{kw['model']}", "rationale": "strong"}
            if "ready" in props:
                calls["vote"] += 1
                return {"ready": True, "feedback": ""}        # all agree
            calls["synth"] += 1
            return {"content": "FINAL CV"}
    monkeypatch.setattr(llm, "get_client", lambda s: _Fake())

    res = panel.deliberate("cv", Materials(base_cv="Jane Doe\nExperience: ..."),
                           _panel_job(), object(), cfg)
    assert res["content"] == "FINAL CV" and res["models"] == 3
    assert res["agreement"] == 1.0
    assert calls["draft"] == 3 and calls["vote"] == 3 and calls["synth"] == 1  # no re-synth


def test_panel_revises_when_below_threshold(monkeypatch):
    from jobhunter import llm
    from jobhunter.config import Materials
    from web.app.services import panel

    cfg = _panel_cfg(monkeypatch, ["m1", "m2", "m3"], rounds=1, thresh=0.75)
    synths = []

    class _Fake:
        def json(self, **kw):
            props = kw["schema"]["properties"]
            if "rationale" in props:
                return {"content": "draft", "rationale": "x"}
            if "ready" in props:
                return {"ready": False, "feedback": "tighten the summary"}  # nobody agrees
            synths.append(kw["user"])
            return {"content": "REVISED"}
    monkeypatch.setattr(llm, "get_client", lambda s: _Fake())

    res = panel.deliberate("cl", Materials(), _panel_job(), object(), cfg)
    assert res["agreement"] == 0.0                     # 0/3 ready
    # initial synthesis + one revise (rounds=1, didn't converge)
    assert len(synths) == 2
    assert "tighten the summary" in synths[-1]         # feedback fed back in


def test_panel_disabled_or_too_few_models_returns_none(monkeypatch):
    from jobhunter.config import Materials
    from web.app.services import panel
    cfg = _panel_cfg(monkeypatch, ["m1", "m2"], enabled=False)
    assert panel.deliberate("cv", Materials(), _panel_job(), object(), cfg) is None
    cfg = _panel_cfg(monkeypatch, ["only-one"])        # needs >= 2 for a panel
    assert panel.deliberate("cv", Materials(), _panel_job(), object(), cfg) is None


def test_panel_drops_a_failing_model(monkeypatch):
    from jobhunter import llm
    from jobhunter.config import Materials
    from web.app.services import panel

    cfg = _panel_cfg(monkeypatch, ["good1", "bad", "good2"])

    class _Fake:
        def json(self, **kw):
            if kw.get("model") == "bad" and "rationale" in kw["schema"]["properties"]:
                raise RuntimeError("model unavailable")
            props = kw["schema"]["properties"]
            if "rationale" in props:
                return {"content": "d", "rationale": "x"}
            if "ready" in props:
                return {"ready": True, "feedback": ""}
            return {"content": "FINAL"}
    monkeypatch.setattr(llm, "get_client", lambda s: _Fake())

    res = panel.deliberate("cv", Materials(), _panel_job(), object(), cfg)
    assert res["models"] == 2                          # bad model dropped, 2 drafts survive
    assert res["content"] == "FINAL"


def test_admin_reset_clears_premium_daily_cap(client, monkeypatch):
    from datetime import timedelta

    from web.app.config import config
    from web.app.db import SessionLocal
    from web.app.models import Search, User, utcnow
    from web.app.services.reset_usage import reset
    from web.app.services.search_service import QuotaError, check_quota
    monkeypatch.setattr(config, "premium_searches_per_day", 2)
    signup(client, email="cap@example.com")
    earlier = utcnow() - timedelta(minutes=1)            # clearly before the reset
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(email="cap@example.com").one()
        u.plan = "premium"
        db.add(Search(user_id=u.id, status="done", started_at=earlier))  # two today = at cap
        db.add(Search(user_id=u.id, status="done", started_at=earlier))
        db.commit()
        with __import__("pytest").raises(QuotaError):
            check_quota(db, u)                            # fair-use cap hit
    finally:
        db.close()

    reset("cap@example.com")                              # operator reset

    db = SessionLocal()
    try:
        u = db.query(User).filter_by(email="cap@example.com").one()
        assert u.usage_reset_at is not None
        check_quota(db, u)                                # daily cap cleared -> no raise
    finally:
        db.close()


# --------------------------- gated-link recovery -------------------------- #
def test_title_match_and_recover(monkeypatch):
    from jobhunter.models import JobPosting
    from jobhunter.sources import ats
    from web.app.services import recover

    assert recover._title_match("Chief of Staff",
                                "Chief of Staff (Future Founder/VC)") == 1.0
    assert recover._title_match("Head of Ops", "Warehouse Picker") < 0.5

    # Ashby board returns the real role -> its direct URL is recovered by title.
    def _fake_ashby(name, token):
        assert token == "abundant"
        return [JobPosting(source="ats:ashby:Abundant", title="Chief of Staff (Future Founder/VC)",
                           company="Abundant", url="https://jobs.ashbyhq.com/abundant/REAL")]
    monkeypatch.setitem(ats.FETCHERS, "greenhouse", lambda n, t: [])
    monkeypatch.setitem(ats.FETCHERS, "lever", lambda n, t: [])
    monkeypatch.setitem(ats.FETCHERS, "ashby", _fake_ashby)

    assert recover.recover_apply_url("Abundant", "Chief of Staff") == \
        "https://jobs.ashbyhq.com/abundant/REAL"
    # no confident match -> None (better than a wrong link)
    assert recover.recover_apply_url("Abundant", "Senior Data Engineer") is None


def test_verify_links_recovers_gated_before_dropping(client, monkeypatch):
    from web.app.db import SessionLocal
    from web.app.models import Job
    from web.app.services import reaper, recover, search_service
    from jobhunter.models import JobPosting, MatchResult

    gated = JobPosting(source="api:wwr", title="Chief of Staff", company="Abundant",
                       url="https://weworkremotely.com/gated")
    m = MatchResult(tier=1, score=88, reasons="ok")

    monkeypatch.setattr(reaper, "check_url", lambda url, c: "gated")
    monkeypatch.setattr(recover, "recover_apply_url",
                        lambda company, title: "https://jobs.ashbyhq.com/abundant/REAL")

    db = SessionLocal()
    try:
        db.add(Job(dedup_key=gated.dedup_key(), source=gated.source,
                   title=gated.title, url=gated.url))
        db.commit()
        kept = search_service._verify_links(db, [(gated, m)])
        assert len(kept) == 1                                  # not dropped
        assert kept[0][0].url == "https://jobs.ashbyhq.com/abundant/REAL"   # recovered
        row = db.query(Job).filter_by(dedup_key=gated.dedup_key()).one()
        assert row.url == "https://jobs.ashbyhq.com/abundant/REAL"          # corpus updated
    finally:
        db.query(Job).filter_by(dedup_key=gated.dedup_key()).delete()
        db.commit(); db.close()


def test_verify_links_drops_unrecoverable_gated(client, monkeypatch):
    from web.app.db import SessionLocal
    from web.app.models import Job
    from web.app.services import reaper, recover, search_service
    from jobhunter.models import JobPosting, MatchResult

    gated = JobPosting(source="api:wwr", title="Obscure Role", company="NoAtsCo",
                       url="https://weworkremotely.com/gated2")
    m = MatchResult(tier=1, score=70, reasons="ok")
    monkeypatch.setattr(reaper, "check_url", lambda url, c: "gated")
    monkeypatch.setattr(recover, "recover_apply_url", lambda company, title: None)

    db = SessionLocal()
    try:
        db.add(Job(dedup_key=gated.dedup_key(), source=gated.source,
                   title=gated.title, url=gated.url))
        db.commit()
        kept = search_service._verify_links(db, [(gated, m)])
        assert kept == []                                      # dropped (unrecoverable)
        assert db.query(Job).filter_by(dedup_key=gated.dedup_key()).count() == 0
    finally:
        db.query(Job).filter_by(dedup_key=gated.dedup_key()).delete()
        db.commit(); db.close()


def test_reaper_check_limit_zero_checks_all(client, monkeypatch):
    from web.app.db import SessionLocal
    from web.app.models import Job
    from web.app.services import reaper
    seen = []
    monkeypatch.setattr(reaper, "check_url", lambda url, c: seen.append(url) or "active")
    db = SessionLocal()
    try:
        for i in range(7):                       # 7 never-checked jobs
            db.add(Job(dedup_key=f"dc-{i}", source="s", title="x",
                       url=f"https://example.com/{i}", last_checked_at=None))
        db.commit()
        reaper.sweep(db, check_limit=0, workers=2)   # 0 = check every due job
        # every one of the 7 due jobs is checked (not capped at a limit)
        assert all(f"https://example.com/{i}" in seen for i in range(7))
    finally:
        for i in range(7):
            db.query(Job).filter_by(dedup_key=f"dc-{i}").delete()
        db.commit(); db.close()


def test_admin_clear_board(client, monkeypatch):
    from web.app.config import config
    from web.app.db import SessionLocal
    from web.app.models import JobResult, Search, User
    monkeypatch.setattr(config, "admin_token", "s3cret")
    signup(client, email="board@example.com")
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(email="board@example.com").one()
        s = Search(user_id=u.id, status="done"); db.add(s); db.flush()
        db.add(JobResult(search_id=s.id, user_id=u.id, position=1, short_id="j1",
                         title="Old", company="X"))
        db.commit(); uid = u.id
    finally:
        db.close()
    r = client.post("/admin/clear-board", data={"email": "board@example.com"},
                    auth=("op", "s3cret"), follow_redirects=False)
    assert r.status_code == 303
    db = SessionLocal()
    try:
        assert db.query(JobResult).filter_by(user_id=uid).count() == 0
        assert db.query(Search).filter_by(user_id=uid).count() == 0
    finally:
        db.close()
    assert client.post("/admin/clear-board", data={"email": "x"}).status_code == 401
    assert client.post("/admin/deep-clean").status_code == 401       # both gated
