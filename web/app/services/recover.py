"""Recover a real application link for a job whose URL is gated behind a
login/registration wall — the way a person would, by finding the company's own
job board.

Free path: guess the company's ATS handle from its name and probe the big three
(Greenhouse / Lever / Ashby — where most of these jobs actually live), then match
the role by title. Returns the direct apply URL only on a confident title match;
otherwise None, because a link to the wrong role is worse than none.
"""

from __future__ import annotations

import logging
import re

from jobhunter.sources.ats import FETCHERS

log = logging.getLogger("jbhntr.recover")

_ATS_TRY = ("greenhouse", "lever", "ashby")
_MATCH_MIN = 0.7          # required title overlap to trust a recovered link


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _words(t: str) -> list[str]:
    return [w for w in re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).split() if w]


def _title_match(query: str, cand: str) -> float:
    """How well `cand`'s title matches the `query` title, 0-1. A substring match
    scores 1; otherwise it's the share of the query's words present in cand."""
    q, c = " ".join(_words(query)), " ".join(_words(cand))
    if not q or not c:
        return 0.0
    if q in c or c in q:
        return 1.0
    wq, wc = set(q.split()), set(c.split())
    return len(wq & wc) / len(wq)


def recover_apply_url(company: str, title: str) -> str | None:
    """Direct apply URL for `title` at `company`, or None if not confidently found."""
    slug = _slug(company)
    if not slug or len(_words(title)) < 2:
        return None
    for ats in _ATS_TRY:
        fetch = FETCHERS.get(ats)
        if not fetch:
            continue
        try:
            jobs = fetch(company, slug)
        except Exception:
            continue
        best, best_score = None, 0.0
        for j in jobs or []:
            s = _title_match(title, j.title)
            if s > best_score:
                best, best_score = j, s
        if best and best_score >= _MATCH_MIN and best.url:
            log.info("Recovered %r @ %s via %s:%s", title, company, ats, slug)
            return best.url
    return None
