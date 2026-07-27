"""Write-through cache into the shared job corpus (Phase 2, slice 1).

Every search upserts the jobs it fetched here, tagged once. Nothing reads this
for matching yet — later slices (SQL pre-filter, embeddings, score cache) build
on it. Because it only writes to a new table, it cannot change search results;
and it fails soft, so a corpus error never breaks a user's search.

See docs/ARCHITECTURE.md → "Scaling: the shared job corpus".
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session as DbSession

from jobhunter.models import JobPosting
from jobhunter.tags import deterministic_tags

from ..models import Job, aware, utcnow

log = logging.getLogger("jbhntr.corpus")

_FRESH_DAYS = 30   # match the search-time freshness window


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
