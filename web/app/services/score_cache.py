"""Score cache — reuse an LLM verdict when nothing that produced it changed.

The cost lever for repeat and overlapping searches: a job the same user already
scored (or that another search scored under an identical context) is not
re-sent to the LLM. Correctness rests entirely on the key — `input_hash` folds
in every scoring input, so a change to the prompt (via matcher.PROMPT_VERSION),
the model, the profile, materials, criteria, company profile, feedback, or the
job's own text yields a new hash and a fresh score.

See docs/ARCHITECTURE.md → "The cache-key rule".
"""

from __future__ import annotations

import hashlib
import json
import logging

from sqlalchemy.orm import Session as DbSession

from jobhunter.matcher import PROMPT_VERSION
from jobhunter.models import JobPosting, MatchResult

from ..models import ScoreCache

log = logging.getLogger("jbhntr.scorecache")

_IN_CHUNK = 400
_DESC_CAP = 4000


def context_key(profile, materials, feedback, company_profile, criteria, model: str) -> str:
    """Hash of everything constant across a search that affects every score."""
    cp = (company_profile.as_prompt_block()
          if company_profile is not None and not company_profile.is_empty() else "")
    cr = (criteria.as_prompt_block()
          if criteria is not None and not criteria.is_empty() else "")
    parts = [
        str(PROMPT_VERSION), model,
        profile.objective or "",
        ",".join(profile.seniority), ",".join(profile.company_type),
        ",".join(profile.verticals), ",".join(profile.locations),
        str(profile.salary_floor_eur),
        materials.combined_context() or "",
        cp, cr,
        json.dumps(feedback or [], sort_keys=True, default=str),
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def job_hash(ctx: str, job: JobPosting) -> str:
    """Per-job hash: the search context plus this job's scored content."""
    blob = f"{ctx}\x1f{job.dedup_key()}\x1f{job.title}\x1f{(job.description or '')[:_DESC_CAP]}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def get_many(db: DbSession, hashes: list[str]) -> dict[str, MatchResult]:
    """Cached MatchResults keyed by input_hash, for the hashes we have."""
    out: dict[str, MatchResult] = {}
    for i in range(0, len(hashes), _IN_CHUNK):
        for row in db.query(ScoreCache).filter(
                ScoreCache.input_hash.in_(hashes[i : i + _IN_CHUNK])):
            out[row.input_hash] = MatchResult(
                tier=row.tier, score=row.score,
                fit_role=row.fit_role, fit_candidate=row.fit_candidate,
                reasons=row.reasons,
                role=row.role, company=row.company, location=row.location,
                vertical=row.vertical, seniority=row.seniority, remote=row.remote,
                tags=list(row.tags or []),
            )
    return out


def put_many(db: DbSession, items: list[tuple[str, JobPosting, MatchResult, str]]) -> int:
    """Store freshly-scored results. Skips hashes already present. Fails soft."""
    if not items:
        return 0
    try:
        have = set()
        keys = [h for h, _, _, _ in items]
        for i in range(0, len(keys), _IN_CHUNK):
            have.update(r.input_hash for r in db.query(ScoreCache.input_hash)
                        .filter(ScoreCache.input_hash.in_(keys[i : i + _IN_CHUNK])))
        added = 0
        for h, job, m, model in items:
            if h in have:
                continue
            have.add(h)
            db.add(ScoreCache(
                input_hash=h, dedup_key=job.dedup_key(),
                tier=m.tier, score=m.score,
                fit_role=m.fit_role, fit_candidate=m.fit_candidate,
                reasons=m.reasons,
                role=m.role, company=m.company, location=m.location,
                vertical=m.vertical, seniority=m.seniority, remote=m.remote,
                tags=list(m.tags), model=model,
            ))
            added += 1
        db.commit()
        return added
    except Exception as exc:
        log.warning("Score-cache write skipped: %s", exc)
        db.rollback()
        return 0
