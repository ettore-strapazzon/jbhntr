"""/invite page (R3-03) — the dedicated referral surface.

  GET  /invite          signed-in user's referral code + link, the live counter
                        (signed up / credited / pending / credits earned) and the
                        six per-channel pre-written messages. Emits
                        invite_page_viewed (one per load). Logged out -> /login.
                        noindex (meta + X-Robots-Tag).
  POST /invite/copied   fire-and-forget beacon from static/invite.js when a copy
                        button or share-intent button is used. Emits
                        invite_link_copied with an allowlisted `channel`.

Gated by config.invite_page (env INVITE_PAGE, default OFF): both routes 404 while
off, whoever asks. GC launch gate (ARTEFACTS_SPEC §3.4): stays off until R3-11
(delayed / reviewed payout) is live, because the cleared copy describes it.

All visible copy is ARTEFACTS_SPEC §3.5 verbatim (CMO, GC-cleared 2026-11-13,
COMPLIANCE_CARD v1.2 §D). Numbers come from config. Every "first scan is free"
sentence — page and messages — renders only when config.first_scan_free (GC
conditional-rendering rule). Reuses services/referral for the code and link;
only READS payout results (ledger), never writes credits.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from ..auth import require_user
from ..config import config
from ..db import get_session
from ..models import CreditLedger, ProductEvent, User
from ..services import referral
from ..services.events import record
from ..templating import templates

router = APIRouter()

NOINDEX = {"X-Robots-Tag": "noindex, nofollow"}

# Final `channel` values (§3.5.6). Anything else is rejected, not stored.
CHANNELS = frozenset({"link", "code", "native", "whatsapp", "linkedin", "email",
                      "x", "bluesky", "slack_teams"})

# --- §3.5.6 messages, verbatim. [[...]] wraps a "first scan is free" sentence
# (with its trailing separator) that is dropped when config.first_scan_free is
# off; {link}/{friend_credits}/{inviter_credits} are filled server-side. --------
_MSG_WHATSAPP = (
    "Have you seen JBHNTR? It reads live job listings and gives you a short list of "
    "roles worth applying to, with reasons for and against each. [[First scan is free, "
    "and my link adds bonus credits. ]](Disclosure: I earn credits if you join.) {link}")
_MSG_LINKEDIN = (
    "Hi, thought of you as I've been looking at roles. I signed up to JBHNTR: it reads "
    "live job listings and returns a short list worth applying to, with a fit score in "
    "both directions and the reasons for and against each role. It doesn't apply for "
    "you, it helps you choose. [[Your first scan is free, and my link adds "
    "{friend_credits} bonus credits. ]]Full disclosure, I get credits too if you join. "
    "{link}")
_EMAIL_SUBJECT = "A job-search tool you might find useful"
_MSG_EMAIL = (
    "Hi,\n\n"
    "I signed up to JBHNTR and thought of you. It reads live job listings and gives "
    "you a short list of roles worth applying to, with a fit score in both directions "
    "and the reasons for and against each one. It doesn't apply for you; it helps you "
    "decide where your time goes.\n\n"
    "[[Your first scan is free, and signing up through my link adds {friend_credits} "
    "bonus credits:\n]]"
    "{link}\n\n"
    "Full disclosure: I get {inviter_credits} credits if you sign up and run a scan.")
_MSG_X = (
    "Apply to fewer roles, chosen better. JBHNTR reads live job listings and gives you "
    "a short list that fits both ways, with reasons for and against each. [[First scan "
    "is free. ]]Disclosure: I earn credits if you join via my link. {link}")
_MSG_SLACK = (
    "If anyone here is job hunting: JBHNTR reads live job listings and gives you a "
    "short list of roles worth applying to, with reasons for and against each. [[First "
    "scan is free. ]]My link adds bonus credits for you (disclosure: I earn credits too "
    "if you join): {link}")

_FREE = re.compile(r"\[\[(.*?)\]\]", re.S)


def _render(tpl: str, **fill) -> str:
    keep = config.first_scan_free
    return _FREE.sub(lambda m: m.group(1) if keep else "", tpl).format(**fill)


def _q(s: str) -> str:
    return quote(s, safe="")


def channel_messages(link: str) -> list[dict]:
    """The six §3.5.6 cards, in spec order, each with its filled message and (where
    one exists) the share-intent href with the message URL-encoded."""
    fill = dict(link=link, friend_credits=config.referral_friend_credits,
                inviter_credits=config.referral_credits)
    wa = _render(_MSG_WHATSAPP, **fill)
    li = _render(_MSG_LINKEDIN, **fill)
    em = _render(_MSG_EMAIL, **fill)
    xx = _render(_MSG_X, **fill)
    sl = _render(_MSG_SLACK, **fill)
    return [
        {"channel": "whatsapp", "name": "WhatsApp", "message": wa,
         "button": "Open WhatsApp", "href": f"https://wa.me/?text={_q(wa)}"},
        {"channel": "linkedin", "name": "LinkedIn DM", "message": li,
         "button": "Open LinkedIn messages",
         "href": "https://www.linkedin.com/messaging/"},
        {"channel": "email", "name": "Email", "message": em, "subject": _EMAIL_SUBJECT,
         "button": "Open email",
         "href": f"mailto:?subject={_q(_EMAIL_SUBJECT)}&body={_q(em)}"},
        {"channel": "x", "name": "X", "message": xx, "button": "Post on X",
         "href": f"https://twitter.com/intent/tweet?text={_q(xx)}"},
        {"channel": "bluesky", "name": "Bluesky", "message": xx,
         "button": "Post on Bluesky",
         "href": f"https://bsky.app/intent/compose?text={_q(xx)}"},
        {"channel": "slack_teams", "name": "Slack / Teams", "message": sl,
         "helper": ("For community, alumni or job-search channels. Check the channel "
                    "allows referral links first.")},
    ]


def counter(db: DbSession, user: User) -> dict:
    """§3.2 live counter, recomputed on every load. Counts only — never who (IN4).

    signed_up  users whose referred_by_user_id is me
    credited   my `referral_activated` ledger rows keyed referral:{friend_id}
               (invites that actually paid out)
    pending    referred friends who ran a first scan (scan_completed or the
               referral_activated event) but have no ledger row yet — inside the
               R3-11 delay, awaiting a triage action, or held for review
    earned     SUM of my `referral_activated` ledger deltas
    """
    friend_ids = [fid for (fid,) in db.query(User.id)
                  .filter(User.referred_by_user_id == user.id)]
    rows = (db.query(CreditLedger.idempotency_key, CreditLedger.delta)
            .filter(CreditLedger.user_id == user.id,
                    CreditLedger.reason == "referral_activated").all())
    earned = sum(d for _, d in rows)
    credited_keys = {k for k, _ in rows}
    pending = 0
    if friend_ids:
        scanned = {uid for (uid,) in db.query(ProductEvent.user_id).filter(
            ProductEvent.user_id.in_(friend_ids),
            ProductEvent.name.in_(("scan_completed", "referral_activated"))).distinct()}
        pending = sum(1 for fid in scanned if f"referral:{fid}" not in credited_keys)
    return {"signed_up": len(friend_ids), "credited": len(rows),
            "pending": pending, "earned": int(earned)}


@router.get("/invite", response_class=HTMLResponse)
def invite_page(request: Request, db: DbSession = Depends(get_session)):
    if not config.invite_page:
        return HTMLResponse("Not found", status_code=404, headers=NOINDEX)
    user = require_user(request, db)          # logged out -> 303 /login
    code = referral.ensure_code(db, user)     # legacy account still missing one
    db.commit()
    link = referral.invite_url(code)
    messages = channel_messages(link)
    ctx = {
        "request": request, "user": user,
        "meta_title": "Invite friends · JBHNTR",
        "meta_robots": "noindex,nofollow",
        "code": code, "link": link,
        # §3.5.2 helper: "jbhntr.app/signup?ref={code}" = the link without scheme.
        "typed_link": link.split("://", 1)[-1],
        "first_scan_free": config.first_scan_free,
        "friend_credits": config.referral_friend_credits,
        "inviter_credits": config.referral_credits,
        "counts": counter(db, user),
        "messages": messages,
        # Mobile "Share…" sends the WhatsApp text with url={link}; the link goes
        # in `url`, so it is not repeated in `text`.
        "native_text": messages[0]["message"][: -len(link)].rstrip(),
    }
    record(db, "invite_page_viewed", user_id=user.id)
    return templates.TemplateResponse(request, "invite.html", ctx, headers=NOINDEX)


@router.post("/invite/copied")
def invite_copied(request: Request, channel: str = Form(""), source: str = Form("copy"),
                  db: DbSession = Depends(get_session)):
    if not config.invite_page:
        return Response(status_code=404)
    user = require_user(request, db)
    if channel not in CHANNELS:
        return Response(status_code=422)
    record(db, "invite_link_copied", user_id=user.id, channel=channel,
           source="intent" if source == "intent" else "copy")
    return Response(status_code=204)
