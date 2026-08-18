"""Write-through cache into the shared job corpus (Phase 2, slice 1).

Every search upserts the jobs it fetched here, tagged once. Nothing reads this
for matching yet — later slices (SQL pre-filter, embeddings, score cache) build
on it. Because it only writes to a new table, it cannot change search results;
and it fails soft, so a corpus error never breaks a user's search.

See docs/ARCHITECTURE.md → "Scaling: the shared job corpus".
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from sqlalchemy.orm import Session as DbSession

from jobhunter.models import JobPosting
from jobhunter.tags import deterministic_tags

from ..models import Job, aware, utcnow

log = logging.getLogger("jbhntr.corpus")

_FRESH_DAYS = 30   # match the search-time freshness window

# Hosts that never lead to a usable application page: they gate the posting
# behind a login/registration wall and/or serve an ephemeral page that 404s once
# the listing rotates. A job whose apply URL is one of these is dropped at
# ingestion and cleaned from the corpus (see reaper), so we never send a user
# to a dead end.
GATED_HOSTS = ("findwork.dev",)


def is_gated_url(url: str) -> bool:
    host = urlparse(url or "").netloc.lower()
    return any(host == h or host.endswith("." + h) for h in GATED_HOSTS)


def count_matching(db: DbSession, profile) -> int:
    """How many fresh corpus postings match this profile's geography (§11.3).

    Counts jobs in any selected country, plus fully-remote roles when
    'Remote-Anywhere' is on. A signal, not a guarantee — it reads the shared
    corpus, which grows nightly. Bounded to fresh rows and scanned in Python so
    it stays dialect-agnostic (JSON overlap isn't portable SQL); revisit if the
    corpus outgrows that.
    """
    from datetime import timedelta

    from jobhunter import geo

    codes = {c for c in (geo._country_of(n) for n in (profile.countries or [])) if c}
    remote_any = "Remote-Anywhere" in (profile.locations or [])
    if not codes and not remote_any:
        return 0

    cutoff = utcnow() - timedelta(days=_FRESH_DAYS)
    rows = (db.query(Job.countries, Job.remote_mode)
              .filter(Job.last_seen_at >= aware(cutoff)).all())
    n = 0
    for countries, remote_mode in rows:
        if codes and countries and codes.intersection(countries):
            n += 1
        elif remote_any and remote_mode == "remote":
            n += 1
    return n

_DESC_CAP = 8000
_IN_CHUNK = 400          # keep SQLite's 999-variable IN() limit clear
_EMBED_CHUNK = 64        # small batches: lower peak memory + granular progress logs


def _chunks(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def upsert_jobs(db: DbSession, postings: list[JobPosting]) -> tuple[int, int]:
    """Insert new postings, refresh last_seen_at on ones already stored.

    Deduped by JobPosting.dedup_key so the same role from several sources is one
    row. Returns (added, updated). Never raises — logs and returns (0, 0).
    """
    try:
        by_key: dict[str, JobPosting] = {}
        for p in postings:
            if is_gated_url(p.url):               # never store a walled/dead-end link
                continue
            by_key.setdefault(p.dedup_key(), p)   # collapse within-batch dups
        if not by_key:
            return (0, 0)

        keys = list(by_key)
        existing: dict[str, Job] = {}
        for chunk in _chunks(keys, _IN_CHUNK):
            for row in db.query(Job).filter(Job.dedup_key.in_(chunk)):
                existing[row.dedup_key] = row

        now = utcnow()
        added = updated = 0
        for key, p in by_key.items():
            tags = deterministic_tags(p)
            row = existing.get(key)
            if row is None:
                db.add(_new_row(key, p, tags, now))
                added += 1
            else:
                row.last_seen_at = now
                # A later fetch may carry a fuller description (post-enrichment);
                # upgrade the row and re-tag from the richer text.
                if len(p.description or "") > len(row.description or ""):
                    row.description = (p.description or "")[:_DESC_CAP]
                    row.location = (p.location or row.location)[:200]
                    _apply_tags(row, tags)
                updated += 1

        db.commit()
        log.info("Corpus: +%d new, %d refreshed (%d unique)", added, updated, len(by_key))
        return (added, updated)
    except Exception as exc:          # a cache write must never break a search
        log.warning("Corpus upsert skipped: %s", exc)
        db.rollback()
        return (0, 0)


def _new_row(key: str, p: JobPosting, tags: dict, now) -> Job:
    row = Job(
        dedup_key=key,
        source=p.source, title=(p.title or "")[:300],
        company=(p.company or "")[:200], location=(p.location or "")[:200],
        description=(p.description or "")[:_DESC_CAP], url=(p.url or "")[:1000],
        posted_date=str(p.posted_date or ""),
        first_seen_at=now, last_seen_at=now,
    )
    _apply_tags(row, tags)
    return row


def job_embed_text(row: Job) -> str:
    """The text we embed for a corpus job — enough signal, not the whole ad."""
    parts = [row.title or "", row.company or "", (row.description or "")[:2000]]
    return " — ".join(p for p in parts if p)


def embed_new_jobs(db: DbSession, settings, limit: int = 1000) -> int:
    """Embed corpus jobs that have no (current-model) embedding yet. Batched.

    No-op when embeddings are unconfigured. Returns how many were embedded.
    Only touches rows missing an embedding or embedded by a different model,
    so a model switch re-embeds cleanly.
    """
    from jobhunter import embeddings

    if not embeddings.is_configured(settings):
        return 0
    model = embeddings.model_name(settings)
    rows = (db.query(Job)
              .filter((Job.embedding.is_(None)) | (Job.embedding_model != model))
              .limit(limit).all())
    if not rows:
        return 0
    # Commit in chunks so a mid-run stall keeps the progress made and the next
    # call resumes where this left off (rows without a current vector). Logged
    # per chunk: local embedding is otherwise a silent multi-minute black box,
    # which makes a crash here impossible to tell from a slow run.
    log.info("Embedding %d new corpus jobs (%s)…", len(rows), model)
    done = 0
    for i in range(0, len(rows), _EMBED_CHUNK):
        chunk = rows[i : i + _EMBED_CHUNK]
        try:
            vectors = embeddings.embed([job_embed_text(r) for r in chunk], settings)
        except Exception:
            log.exception("Embedding failed at %d/%d — corpus keeps the jobs, "
                          "just without vectors this run", done, len(rows))
            break
        if len(vectors) != len(chunk):
            log.warning("Embedding stopped at %d/%d (provider limit?)", done, len(rows))
            break
        for row, vec in zip(chunk, vectors):
            row.embedding = vec
            row.embedding_model = model
        db.commit()
        done += len(chunk)
        log.info("  embedded %d/%d", done, len(rows))
    log.info("Embedded %d corpus jobs (%s)", done, model)
    return done


def _apply_tags(row: Job, tags: dict) -> None:
    row.countries = tags["countries"]
    row.remote_mode = tags["remote_mode"]
    row.salary_min = tags["salary_min"]
    row.salary_max = tags["salary_max"]
    row.has_salary = tags["has_salary"]


# --------------------------------------------------------------------------- #
# One-time country resolution for the long tail (a location the alias maps can't
# place, e.g. an obscure town with no country marker). Done once per posting at
# ingestion, cached on Job.countries + Job.geo_checked, shared by every user.
_GEO_BATCH = 50

_COUNTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "code": {
                        "type": "string",
                        "description": "ISO 3166-1 alpha-2 country code, lowercase "
                                       "(e.g. 'gb', 'it', 'us'). Empty string if the "
                                       "location is remote/global/anywhere or names "
                                       "no identifiable country.",
                    },
                },
                "required": ["index", "code"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}

_GEO_SYS = (
    "You map job-posting location strings to a single country. For each numbered "
    "location return its ISO 3166-1 alpha-2 code in lowercase. If the location is "
    "remote/global/anywhere, or names no identifiable country, return an empty "
    "string. Judge only the place named — do not guess from anything else. Return "
    "exactly one result per input index."
)


def _resolve_country_batch(locations: list[str], settings) -> list[str]:
    """LLM: location strings -> ISO alpha-2 codes (aligned to input order).

    Returns "" for any it can't place. Never raises — a failed batch just yields
    all-empty, so those rows are marked checked and simply carry no country tag.
    """
    from jobhunter import llm

    listing = "\n".join(f"{i}. {loc}" for i, loc in enumerate(locations))
    try:
        data = llm.get_client(settings).json(
            system=_GEO_SYS, user="Locations:\n" + listing,
            schema=_COUNTRY_SCHEMA, tier=llm.SCORING, max_tokens=1500)
    except Exception as exc:
        log.warning("Country-resolve batch failed (%d locations): %s", len(locations), exc)
        return ["" for _ in locations]

    out = ["" for _ in locations]
    for item in data.get("results", []):
        i = item.get("index")
        code = (item.get("code") or "").strip().lower()
        if isinstance(i, int) and 0 <= i < len(out) and len(code) == 2 and code.isalpha():
            out[i] = code
    return out


def correct_ats_locations(db: DbSession, limit: int = 400) -> int:
    """Overwrite aggregator-supplied locations with the true one from the source
    ATS, for corpus jobs whose link is Ashby / Greenhouse / Lever.

    Aggregators (findwork, jooble…) frequently mislabel these — e.g. an on-site SF
    role tagged "Remote" — which then sails past a country filter. The ATS has the
    structured truth, so one call per board corrects every one of that board's
    postings. Grouped by board so a company with many roles costs a single fetch.
    Marks `ats_checked` either way, so it never re-processes the same posting.
    """
    from collections import defaultdict

    from jobhunter.sources.ats import board_location_index, parse_ats_job

    rows = db.query(Job).filter(Job.ats_checked.is_(False)).limit(limit).all()
    if not rows:
        return 0

    groups: dict[tuple, list] = defaultdict(list)
    for r in rows:
        ats, org, jid = parse_ats_job(r.url or "")
        if ats and org and jid:
            groups[(ats, org)].append((r, jid))
        else:
            r.ats_checked = True         # not an ATS link — nothing to correct
    db.commit()

    corrected = 0
    for (ats, org), items in groups.items():
        index = board_location_index(ats, org)
        for r, jid in items:
            info = index.get(jid) or index.get(str(jid))
            if info and info.get("location"):
                r.location = info["location"]
                r.remote_mode = info["remote_mode"]
                if info["countries"]:
                    r.countries = info["countries"]
                    r.geo_checked = True     # country settled from the source
                corrected += 1
            r.ats_checked = True
        db.commit()
    log.info("ATS location correction: %d checked, %d corrected", len(rows), corrected)
    return corrected


def backfill_countries(db: DbSession, settings, limit: int = 500) -> int:
    """Settle the country of corpus jobs not yet geo-checked. Returns how many
    got a country from the LLM lookup.

    Order of resolution, cheapest first: the deterministic tagger already placed
    most jobs at ingestion; blank/remote locations legitimately have no country;
    only a genuinely-unresolvable real place costs an LLM call, batched. No-op
    when no LLM is configured (the tag just stays empty, as before).
    """
    from jobhunter import geo, llm
    from jobhunter.dedup import _is_generic_remote

    if not llm.is_configured(settings):
        return 0
    rows = db.query(Job).filter(Job.geo_checked.is_(False)).limit(limit).all()
    if not rows:
        return 0

    to_ask: list[Job] = []
    for r in rows:
        if r.countries:                       # deterministic tagger already placed it
            r.geo_checked = True
            continue
        loc = (r.location or "").strip()
        if not loc or _is_generic_remote(loc.lower()):
            r.geo_checked = True              # legitimately country-less
            continue
        code = geo.country_of(loc)            # maps may have grown since ingestion
        if code:
            r.countries = [code]
            r.geo_checked = True
            continue
        to_ask.append(r)
    db.commit()

    resolved = 0
    for chunk in _chunks(to_ask, _GEO_BATCH):
        codes = _resolve_country_batch([r.location for r in chunk], settings)
        for r, code in zip(chunk, codes):
            r.countries = [code] if code else []
            r.geo_checked = True
            resolved += 1 if code else 0
        db.commit()
    log.info("Geo backfill: %d checked, %d placed by lookup (%d asked)",
             len(rows), resolved, len(to_ask))
    return resolved


def backfill_remote_modes(db: DbSession, limit: int = 20000,
                          include_onsite: bool = False) -> int:
    """Recompute remote_mode with the current (now multilingual) tagger. Returns
    how many rows were reclassified.

    The mode is set once at ingestion, so a job ingested with a blank/unresolvable
    location, before its description was enriched, or before a term the tagger now
    recognises (e.g. Italian 'smart working') was in the list, keeps its stale tag.

    Default: only re-check 'unknown' rows (cheap, run nightly). With
    ``include_onsite`` (a one-time reclassification via /admin/retag): also
    re-check 'onsite' rows and UPGRADE them to remote/hybrid when the tagger now
    finds an explicit signal — this rescues the many non-English hybrid/remote
    roles that defaulted to onsite. An onsite row is never downgraded.

    Batched by id so a full-corpus pass doesn't load every Job into memory.
    """
    from jobhunter.models import JobPosting
    from jobhunter.tags import remote_mode

    modes = ("unknown", "onsite") if include_onsite else ("unknown",)
    changed = processed = 0
    last_id = 0
    BATCH = 2000
    while processed < limit:
        rows = (db.query(Job)
                .filter(Job.remote_mode.in_(modes), Job.id > last_id)
                .order_by(Job.id)
                .limit(min(BATCH, limit - processed)).all())
        if not rows:
            break
        for r in rows:
            last_id = r.id
            processed += 1
            p = JobPosting(source=r.source or "", title=r.title or "",
                           company=r.company or "", location=r.location or "",
                           description=r.description or "", url=r.url or "")
            mode = remote_mode(p)
            if r.remote_mode == "onsite":
                # Only ever move OFF onsite, and only on an explicit remote/hybrid
                # signal — never re-onsite or blank an already-placed row.
                if mode in ("remote", "hybrid"):
                    r.remote_mode = mode
                    changed += 1
                continue
            # 'unknown' row: a settled country + no remote/hybrid wording is onsite.
            if mode == "unknown" and r.countries:
                mode = "onsite"
            if mode != "unknown":
                r.remote_mode = mode
                changed += 1
        db.commit()
    log.info("Remote-mode backfill: %d reclassified of %d scanned (include_onsite=%s)",
             changed, processed, include_onsite)
    return changed
