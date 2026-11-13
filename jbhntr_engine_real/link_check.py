"""Posting link-health classification (PRIVATE engine side).

Carved out of ``web/app/services/reaper.py`` (R3-16): the multilingual
dead-posting phrases, closed-job redirect markers, captcha/bot-wall and
login-wall markers, and the verdict order that turns one fetch of an apply URL
into 'active' / 'gone' / 'gated' / 'blocked' / 'unknown'. The shell's reaper
keeps the sweep (TTL, DB, tombstones) and calls this through the
``jbhntr_engine`` façade (``classify_link``).
"""

from __future__ import annotations

# A 200 page containing any of these is a genuinely closed/removed posting.
# Multi-word phrases only: a soft-404 landing page says these outright, whereas a
# single word like "expired"/"scaduta" can appear inside a live JD, so we never
# match on those alone (a false match here deletes a real job).
DEAD_MARKERS = (
    # English
    "no longer available", "no longer accepting", "no longer open",
    "position has been filled", "has been filled", "this position is closed",
    "posting is closed", "vacancy is closed", "applications are closed",
    "job is no longer", "position is no longer", "job has expired",
    "this job has expired", "job not found", "page not found",
    "the job you are looking for", "not currently accepting",
    "this vacancy is no longer", "advert has expired", "advertisement has expired",
    # Italian (the agency tail — Manpower/Adecco/Synergie et al. soft-404s). Both
    # the "non più" and the "non è più" phrasings, always qualified by offerta/
    # annuncio/posizione so a stray "non è più disponibile" in a JD can't match.
    "offerta non più disponibile", "offerta non è più disponibile",
    "annuncio non più disponibile", "annuncio non è più disponibile",
    "posizione non più disponibile", "posizione non è più disponibile",
    "offerta di lavoro non più disponibile", "offerta non più attiva",
    "annuncio non più attivo", "annuncio scaduto", "offerta scaduta",
    "candidature chiuse", "selezione chiusa", "ricerca chiusa",
    "posizione ricoperta", "annuncio non trovato", "pagina non trovata",
    # German / French / Spanish (multi-country coverage)
    "nicht mehr verfügbar", "stellenangebot nicht mehr", "anzeige ist nicht mehr",
    "offre n'est plus disponible", "cette offre a expiré", "offre expirée",
    "annonce n'est plus disponible", "poste n'est plus disponible", "offre pourvue",
    "oferta ya no está disponible", "esta oferta ha caducado", "oferta caducada",
    "vacante cubierta", "proceso de selección cerrado",
)

# A closed posting often SERVER-SIDE redirects to a URL that flags it, even when
# the landing page is a bot-check/captcha or a generic search page our fetch can't
# read (jooble sends closed jobs to its search page with ?closedJob=True). Match
# the FINAL redirected URL so these are caught regardless of body content.
GONE_URL_MARKERS = (
    "closedjob=true",                       # jooble
    "no-longer-available", "nolongeravailable",
    "job-expired", "jobexpired", "expired-job",
    "position-filled", "positionfilled",
    "joblisting/expired", "jobs/expired",
)

# A bot-check / captcha page returns 200 but is NOT the posting — we cannot read
# whether the job is live. Distinct from 'gone': the job may well still exist, so
# this is 'blocked' (try to recover the real link elsewhere, else flag it).
CAPTCHA_MARKERS = (
    "recaptcha", "hcaptcha", "px-captcha", "captcha-delivery",
    "verify you are human", "are you a human", "please verify you are",
    "cf-browser-verification", "checking your browser before", "just a moment...",
    "unusual traffic from your", "enable javascript and cookies to continue",
    "ddos protection by", "verify you are not a robot",
)

# A login/registration wall hides the real posting. Unlike a 404, the job is
# usually still live — so this is 'gated' (recoverable), not 'gone'.
WALL_MARKERS = (
    "create an account to view", "sign in to view the full",
    "log in to view this job", "register to see the full",
    "sign up to view full", "account to view full job",
    "create an account to see", "sign up to see the full",
)


def classify_link(url: str, client) -> str:
    """Classify a posting URL as 'active', 'gone', 'gated', or 'unknown'.

    Conservative: only 404/410 or an explicit closed-posting page count as gone;
    a registration/login wall is 'gated' (the job likely still exists, so the
    caller can try to recover the real link). Anything ambiguous (timeout, 403,
    redirect) is 'unknown' — kept.
    """
    if not url:
        return "unknown"
    try:
        r = client.get(url, follow_redirects=True)
    except Exception:
        return "unknown"
    # The URL we actually landed on (after redirects) can flag a closed job even
    # when the page body is a captcha/search page we can't parse.
    final_url = str(getattr(r, "url", "") or "").lower()
    if any(m in final_url for m in GONE_URL_MARKERS):
        return "gone"
    if r.status_code in (404, 410):
        return "gone"
    if r.status_code != 200:
        return "unknown"
    body = r.text.lower()
    if any(m in body for m in DEAD_MARKERS):
        return "gone"
    if any(m in body for m in WALL_MARKERS):
        return "gated"
    if any(m in body for m in CAPTCHA_MARKERS):
        return "blocked"        # a bot-wall — we couldn't actually read the posting
    return "active"
