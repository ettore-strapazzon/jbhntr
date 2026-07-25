"""Orchestrator: fetch → dedup → score → rank → tailor → sheet → email.

Run once a day (locally or via GitHub Actions). Examples:

    python -m jobhunter.pipeline                 # full run
    python -m jobhunter.pipeline --dry-run       # score & print, write nothing
    python -m jobhunter.pipeline --dry-run --limit 10 --no-score   # sources only
"""

from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor

from . import feedback as feedback_mod
from . import llm
from . import seeds as seeds_mod
from . import sources
from .candidate import derive as derive_candidate
from .candidate import derive_company_profile
from .criteria import derive as derive_criteria
from .config import Settings, load_materials, load_profile, load_seeds
from .dedup import SeenStore, filter_new_and_relevant
from .matcher import Matcher
from .models import JobPosting, RankedJob

log = logging.getLogger("jobhunter")

# Below this many new jobs, the triage round-trip isn't worth its own overhead.
TRIAGE_THRESHOLD = 40
# Upper bound on description fetches per run, so one huge day can't stall it.
ENRICH_CAP = 200


def _enrich_descriptions(jobs: list[JobPosting]) -> None:
    """Fetch full descriptions for triage survivors that don't have one yet.

    Some feeds (Workday, SmartRecruiters) list jobs without a body. We only pay
    to fetch those bodies for jobs that already passed the cheap first stage.
    """
    from .sources.ats import enrich_description

    missing = [j for j in jobs if not j.description][:ENRICH_CAP]
    if not missing:
        return
    filled = 0
    # Modest concurrency: several of these hit LinkedIn, which blocks eager clients.
    with ThreadPoolExecutor(max_workers=4) as pool:
        for ok in pool.map(enrich_description, missing):
            filled += bool(ok)
    log.info(
        "Fetched %d/%d missing descriptions before scoring", filled, len(missing)
    )


def _interleave_by_source(jobs: list[JobPosting]) -> list[JobPosting]:
    """Round-robin jobs across their sources.

    Sources are fetched one after another, so the raw list is grouped by source.
    Taking `--limit N` off the front would then only ever sample the first
    source — which makes a small test run wildly unrepresentative. Interleaving
    means any prefix contains a fair spread of every source.
    """
    buckets: dict[str, list[JobPosting]] = {}
    for job in jobs:
        buckets.setdefault(job.source, []).append(job)

    out: list[JobPosting] = []
    while any(buckets.values()):
        for queue in buckets.values():
            if queue:
                out.append(queue.pop(0))
    return out


def _rank(scored, keep_tier_max: int) -> list[RankedJob]:
    kept = [
        RankedJob(job=job, match=match)
        for job, match in scored
        if match.tier <= keep_tier_max
    ]
    kept.sort(key=lambda r: (r.match.tier, -r.match.score))
    return kept


def run(dry_run: bool = False, limit: int = 0, score: bool = True) -> int:
    settings = Settings.from_env()
    profile = load_profile()
    materials = load_materials()

    # 1. Feedback read-back (from the sheet) → persisted store → examples.
    feedback_examples: list[dict] = []
    if not dry_run and settings.google_sheet_id:
        try:
            from .sheets import Sheet

            sheet = Sheet(settings)
            feedback_examples = feedback_mod.merge(sheet.read_feedback())
        except Exception as exc:
            log.warning("Feedback read-back skipped: %s", exc)
            feedback_examples = feedback_mod.load()
    else:
        feedback_examples = feedback_mod.load()

    # 2. Fetch from all sources (fail-soft).
    raw = sources.collect_all(profile, settings)

    # 3. Dedup + cheap pre-filter.
    store = SeenStore()
    new_jobs = filter_new_and_relevant(raw, profile, store)
    if limit:
        # Sample fairly across sources so a small test run is representative.
        new_jobs = _interleave_by_source(new_jobs)[:limit]
        log.info("Limited to %d jobs, sampled across all sources", len(new_jobs))

    if not score:
        print(f"\n{len(new_jobs)} new relevant postings (scoring skipped):\n")
        for j in new_jobs:
            print(f"  [{j.source}] {j.title} @ {j.company} — {j.location}")
        store.close()
        return 0

    if not llm.is_configured(settings):
        log.error(
            "No AI provider configured — cannot score. Set ANTHROPIC_API_KEY, or "
            "LLM_PROVIDER=openai_compatible with LLM_API_KEY. "
            "Use --no-score to list jobs without any AI."
        )
        store.close()
        return 2

    # 4. Score, in two stages so a big company list stays affordable.
    #    The derived candidate profile (from the CV/about-me) gives triage a
    #    real understanding of the candidate rather than a keyword list.
    candidate = derive_candidate(profile, materials, settings)
    seed_labels = [
        s.label() for s in seeds_mod.resolve(load_seeds(), guess_domains=True)
    ]
    # What the companies you admire have in common — used to judge the EMPLOYER,
    # not just the job title.
    company_profile = derive_company_profile(seed_labels, settings)
    # Checkable criteria, which also form the tag vocabulary shown in the sheet.
    criteria = derive_criteria(profile, seed_labels, settings)

    matcher = Matcher(settings)
    to_score = new_jobs
    if profile.two_stage_triage and len(new_jobs) > TRIAGE_THRESHOLD:
        to_score = matcher.triage(new_jobs, profile, candidate, company_profile)
    # Always fetch missing descriptions before full scoring — a job judged with
    # no description gets marked down for lack of information, not on merit.
    _enrich_descriptions(to_score)
    scored = matcher.score(
        to_score, profile, materials, feedback_examples, company_profile, criteria
    )

    # 5. Rank + keep.
    ranked = _rank(scored, profile.keep_tier_max)
    log.info("Kept %d matches (tier <= %d)", len(ranked), profile.keep_tier_max)

    if dry_run:
        _print_ranked(ranked, profile)
        store.close()
        return 0

    # 6. CV/cover letters are NOT generated here — they're produced on demand
    #    for the jobs you actually choose:
    #        python -m jobhunter.apply <job-id>
    #    Writing them for every top match daily wasted money on jobs you'd never
    #    apply to, and buried the ones you would.

    # 7. Write to sheet.
    if settings.google_sheet_id:
        try:
            from .sheets import Sheet

            Sheet(settings).append_ranked(ranked)
        except Exception as exc:
            log.warning("Sheet write failed: %s", exc)

    # 8. Email digest.
    try:
        from .notify import send_digest

        send_digest(ranked, settings)
    except Exception as exc:
        log.warning("Email step failed: %s", exc)

    # 9. Mark everything we scored as seen so it won't reappear tomorrow, and
    #    keep the full posting for the ones we surfaced so `apply` can use it.
    for job in new_jobs:
        store.mark(job)
    for r in ranked:
        store.save_detail(r.job)
    store.commit()
    store.close()
    return 0


def _print_ranked(ranked: list[RankedJob], profile) -> None:
    print(f"\n=== {len(ranked)} matches (dry run — nothing written) ===\n")
    for r in ranked:
        m, j = r.match, r.job
        would = " [would tailor CV+CL]" if m.tier == 1 else ""
        print(f"[tier {m.tier} | {m.score}] {m.role or j.title} @ {m.company or j.company}{would}")
        print(f"    {m.location or j.location} | {j.source}")
        print(f"    {m.reasons}")
        if j.url:
            print(f"    {j.url}")
        print()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Daily job-search assistant")
    parser.add_argument("--once", action="store_true", help="Run one cycle (default).")
    parser.add_argument("--dry-run", action="store_true", help="Score & print; write nothing external.")
    parser.add_argument("--limit", type=int, default=0, help="Cap postings scored (testing).")
    parser.add_argument("--no-score", action="store_true", help="List sources only, no API calls.")
    # CV/cover letters are on demand now: python -m jobhunter.apply <job-id>
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    return run(
        dry_run=args.dry_run,
        limit=args.limit,
        score=not args.no_score,
    )


if __name__ == "__main__":
    sys.exit(main())
