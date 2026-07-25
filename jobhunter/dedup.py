"""SQLite-backed 'seen' store so we only alert on genuinely new postings.

Also applies a cheap pre-filter (location + must-keywords) before the paid
matcher ever sees a posting, to keep API cost down.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional

from . import geo
from .config import DATA_DIR, Profile
from .models import JobPosting

log = logging.getLogger("jobhunter.dedup")

DB_PATH = DATA_DIR / "seen.sqlite"


class SeenStore:
    def __init__(self, db_path: Path = DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen (
                key TEXT PRIMARY KEY,
                title TEXT,
                company TEXT,
                url TEXT,
                first_seen TEXT
            )
            """
        )
        # Full postings for jobs we surfaced, so `jobhunter.apply <id>` can write
        # a tailored CV later without re-fetching the advert.
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS job_detail (
                short_id TEXT PRIMARY KEY,
                payload TEXT,
                saved_at TEXT
            )
            """
        )
        self.conn.commit()

    def save_detail(self, job: JobPosting) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO job_detail (short_id, payload, saved_at) "
            "VALUES (?, ?, ?)",
            (job.short_id(), job.model_dump_json(), date.today().isoformat()),
        )

    def get_detail(self, short_id: str) -> Optional[JobPosting]:
        row = self.conn.execute(
            "SELECT payload FROM job_detail WHERE short_id = ?", (short_id.strip().lower(),)
        ).fetchone()
        return JobPosting.model_validate_json(row[0]) if row else None

    def list_details(self, limit: int = 30) -> list[tuple[str, JobPosting]]:
        rows = self.conn.execute(
            "SELECT short_id, payload FROM job_detail ORDER BY saved_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [(r[0], JobPosting.model_validate_json(r[1])) for r in rows]

    def is_new(self, job: JobPosting) -> bool:
        cur = self.conn.execute("SELECT 1 FROM seen WHERE key = ?", (job.dedup_key(),))
        return cur.fetchone() is None

    def mark(self, job: JobPosting) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO seen (key, title, company, url, first_seen) "
            "VALUES (?, ?, ?, ?, ?)",
            (job.dedup_key(), job.title, job.company, job.url, date.today().isoformat()),
        )

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def prefilter(job: JobPosting, profile: Profile) -> bool:
    """Cheap gate before the paid matcher. True = worth scoring.

    Deliberately does NOT filter on keywords by default. Requiring a word to
    appear silently drops good jobs that use different wording ("Django" but
    never "Python", "server-side" but never "backend") — an invisible false
    negative. Relevance is judged semantically by the triage stage instead.

    `keywords_must` remains supported for anyone who explicitly wants a hard
    gate, but it is empty (inactive) by default.
    """
    hay = f"{job.title} {job.description} {job.company}".lower()

    # Opt-in hard keyword gate. Off unless the user configures it.
    if profile.keywords_must and not any(k in hay for k in profile.keywords_must):
        return False

    # Location gate. Judged on the posting's LOCATION field (not the whole
    # description) so a Brazil role that merely says "remote" in its body isn't
    # treated as EU-remote. Keep if: a target city matches; the role is remote
    # and a "remote-<region>" token's region is present (or the location is a
    # generic remote with no conflicting geo); or there's no location to judge.
    locs = [l.lower() for l in profile.locations]
    if locs:
        loc_hay = f"{job.location}".lower().strip()
        if not loc_hay:
            return True  # nothing to judge on — let the matcher decide

        is_remote = job.looks_remote()
        for token in locs:
            if token.startswith("remote"):
                # A "Remote-EU" preference means *a remote job I can do from the
                # EU* — NOT "any job anywhere in the EU". Without this check a
                # Berlin office role matched Remote-EU purely because Germany is
                # an EU country, which is how on-site Berlin/Lisbon/London jobs
                # were leaking through.
                if not is_remote:
                    continue
                region = token.replace("remote-", "").replace("remote", "").strip()
                if not region:
                    return True  # plain "Remote" — anywhere is fine
                # In-region if the location names a city/country of the region
                # ("Berlin" → Germany → EU), or a region word (europe/emea).
                if geo.location_in_countries(loc_hay, _region_codes(region)):
                    return True
                if any(a in loc_hay for a in REGION_ALIASES.get(region, [])):
                    return True
                # Otherwise keep only a location-agnostic remote job ("Remote",
                # "Anywhere", "Worldwide"). A remote job naming a specific place
                # NOT in the region — e.g. "Manhattan" for Remote-EU — is based
                # elsewhere, so it does not match.
                if _is_generic_remote(loc_hay):
                    return True
            else:
                if not token:
                    continue
                # Country/city aliases: "United States" also matches "Austin,
                # TX"; "Italy" matches "Torino, Italia". geo.match_aliases drops
                # short ambiguous tokens so "us" never matches "Houston".
                aliases = geo.match_aliases(token) + REGION_ALIASES.get(token, [])
                if any(a in loc_hay for a in aliases):
                    return True
                # Permissive fallback ONLY for a COUNTRY preference: keep an
                # unlisted city of that country ("Houston" for US) as long as no
                # other country is named. A CITY preference ("Milan") stays
                # strict — otherwise a global corpus leaks foreign cities in.
                if (geo.is_country_name(token)
                        and not geo.names_other_country(loc_hay, token)):
                    return True
        return False

    return True


GENERIC_REMOTE_WORDS = ("remote", "anywhere", "worldwide", "global")

# Words in a location that carry no specific geography. If, after removing
# these, nothing meaningful remains, the location is "remote from anywhere".
_GENERIC_LOC_WORDS = {
    "remote", "anywhere", "worldwide", "world", "global", "globally",
    "distributed", "home", "wfh", "flexible", "location", "independent",
    "fully", "first", "based", "work", "from", "the", "in", "of", "and", "or",
    "any", "everywhere", "nomad", "async", "timezone", "friendly",
}


def _is_generic_remote(loc_hay: str) -> bool:
    """True if the location names no specific place (e.g. 'Remote, Anywhere')."""
    words = re.findall(r"[a-z]+", loc_hay)
    return not any(len(w) > 1 and w not in _GENERIC_LOC_WORDS for w in words)


# European country codes, for resolving a "Remote-EU" preference.
_EUROPE_CODES = {
    "it", "de", "fr", "es", "nl", "be", "at", "ie", "pt", "pl", "se", "dk",
    "fi", "gr", "ro", "cz", "ch", "gb", "no",
}


def _region_codes(region: str) -> set[str]:
    """Country codes that satisfy a remote-region token ('eu' → all of Europe)."""
    r = region.lower()
    if r in ("eu", "europe", "emea", "eea"):
        return _EUROPE_CODES
    code = geo.country_of(r)
    return {code} if code else set()

# Region token -> substrings that indicate a posting is in that region.
REGION_ALIASES = {
    "eu": ["europe", "european", "emea", "eu ", "e.u.", "cet", "cest", "uk",
           "germany", "france", "spain", "italy", "netherlands", "poland",
           "portugal", "ireland", "sweden", "romania"],
    # Italian ads usually say "Italia", and often name the city instead.
    "italy": ["italy", "italia", "italian", "milan", "milano", "rome", "roma",
              "turin", "torino", "genoa", "genova", "bologna", "florence",
              "firenze", "naples", "napoli"],
    "emea": ["europe", "emea", "middle east", "africa"],
    "us": ["united states", "usa", "u.s.", "america", "est", "pst", "cst"],
    "usa": ["united states", "usa", "u.s.", "america"],
    "uk": ["united kingdom", "uk", "england", "london", "britain"],
    "apac": ["apac", "asia", "australia", "singapore", "pacific"],
}

# A small set of country/region names that clearly signal a non-EU location,
# used only to reject "generic remote" postings that also name such a place.
_OTHER_COUNTRY_HINTS = (
    "brazil", "mexico", "argentina", "uruguay", "colombia", "chile", "peru",
    "india", "philippines", "indonesia", "nigeria", "kenya", "south africa",
    "canada", "united states", "usa", "latam", "americas",
)


def _names_specific_country(loc_hay: str, in_region_aliases: list[str]) -> bool:
    """True if the location names a concrete country outside the target region."""
    if any(a in loc_hay for a in in_region_aliases):
        return False
    return any(h in loc_hay for h in _OTHER_COUNTRY_HINTS)


def title_relevance(job: JobPosting, terms: list[str]) -> float:
    """How well a job title matches the roles the candidate is after, 0-1.

    Deliberately cheap and lexical — this only has to RANK a single company's
    openings against each other, not judge them. The AI stages do that.
    """
    title = (job.title or "").lower()
    if not title or not terms:
        return 0.0
    best = 0.0
    for term in terms:
        words = [w for w in re.split(r"\W+", term.lower()) if len(w) > 2]
        if not words:
            continue
        hits = sum(1 for w in words if w in title)
        score = hits / len(words)
        if term.lower() in title:        # whole phrase present: much stronger
            score = 1.0
        best = max(best, score)
    return best


def cap_per_company(
    jobs: list[JobPosting], limit: int = 10, terms: Optional[list[str]] = None
) -> list[JobPosting]:
    """Stop one prolific employer from owning the shortlist.

    A handful of companies post hundreds of roles (Tether alone was 62 of 512
    on one run), so the AI stages end up reading mostly them and the results
    read like two firms' careers pages.

    Which `limit` we keep matters: sources return postings in arbitrary order,
    so keeping the first N is blind truncation that discards good openings. We
    rank each company's postings by how well the title matches the candidate's
    target roles and keep the best. Callers that have no target terms get the
    original order, so this is never worse than not capping.
    """
    by_company: dict[str, list[JobPosting]] = {}
    order = {id(j): i for i, j in enumerate(jobs)}
    keep: list[JobPosting] = []
    for job in jobs:
        name = (job.company or "").strip().lower()
        if not name:                     # unknown employer: can't be flooding
            keep.append(job)
        else:
            by_company.setdefault(name, []).append(job)

    dropped = 0
    for postings in by_company.values():
        if len(postings) <= limit:
            keep.extend(postings)
            continue
        ranked = sorted(
            postings,
            key=lambda j: (-title_relevance(j, terms or []), order[id(j)]),
        )
        keep.extend(ranked[:limit])
        dropped += len(postings) - limit

    if dropped:
        log.info(
            "Capped %d postings from over-represented companies (kept the %d "
            "best-matching titles each)", dropped, limit,
        )
    # Restore the caller's original ordering — sources are interleaved upstream.
    return sorted(keep, key=lambda j: order[id(j)])


def filter_new_and_relevant(
    jobs: list[JobPosting], profile: Profile, store: SeenStore
) -> list[JobPosting]:
    """Collapse duplicates within this run, drop already-seen, apply pre-filter."""
    out: list[JobPosting] = []
    seen_this_run: set[str] = set()
    for job in jobs:
        key = job.dedup_key()
        if key in seen_this_run:
            continue
        seen_this_run.add(key)
        if not store.is_new(job):
            continue
        if not prefilter(job, profile):
            continue
        out.append(job)
    out = cap_per_company(out, terms=profile.search_terms)
    log.info("After dedup + prefilter: %d new relevant postings", len(out))
    return out
