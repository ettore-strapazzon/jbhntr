"""Write a tailored CV and cover letter for a job you actually chose.

The daily run no longer writes documents for every top match — that spent money
on jobs you were never going to apply to. Instead, pick the ones you want from
the sheet or the digest and run:

    python -m jobhunter.apply 3f9a21c4              # one job
    python -m jobhunter.apply 3f9a21c4 8b02de17     # several
    python -m jobhunter.apply --list                # recent jobs and their IDs

The ID is the `ID` column in the Google Sheet. Documents are uploaded to your
Drive folder and the links written back to the sheet row.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import Settings, load_materials, load_profile
from .dedup import SeenStore
from .models import MatchResult, RankedJob

log = logging.getLogger("jobhunter.apply")


def _print_recent(store: SeenStore, limit: int) -> None:
    rows = store.list_details(limit)
    if not rows:
        print("No jobs stored yet — run `python -m jobhunter.pipeline` first.")
        return
    print(f"\n{len(rows)} most recent jobs:\n")
    for short_id, job in rows:
        print(f"  {short_id}  {job.title[:46]:46} {job.company[:22]:22} {job.location[:20]}")
    print("\nGenerate documents with:  python -m jobhunter.apply <ID>")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Generate a tailored CV + cover letter for chosen jobs"
    )
    ap.add_argument("job_ids", nargs="*", help="Job IDs from the sheet's ID column.")
    ap.add_argument("--list", action="store_true", help="List recent jobs and their IDs.")
    ap.add_argument("--limit", type=int, default=30, help="How many to list.")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    settings = Settings.from_env()
    store = SeenStore()

    if args.list or not args.job_ids:
        _print_recent(store, args.limit)
        store.close()
        return 0 if args.list else 1

    from . import llm

    if not llm.is_configured(settings):
        log.error("No AI provider configured — set ANTHROPIC_API_KEY or LLM_API_KEY.")
        store.close()
        return 2

    profile, materials = load_profile(), load_materials()

    jobs = []
    for job_id in args.job_ids:
        job = store.get_detail(job_id)
        if job is None:
            log.error("Unknown job id %r. Run `--list` to see stored jobs.", job_id)
            continue
        jobs.append(job)

    if not jobs:
        store.close()
        return 1

    # Drive is optional: without it we still generate and print the documents.
    drive = None
    if settings.google_drive_folder_id:
        try:
            from .gdrive import Drive

            drive = Drive(settings)
        except Exception as exc:
            log.warning("Drive unavailable (%s) — will print documents instead.", exc)

    from .generator import Generator

    gen = Generator(settings, drive)
    ranked = [
        RankedJob(job=j, match=MatchResult(tier=1, score=100, reasons="chosen by you"))
        for j in jobs
    ]
    # tailor_top() caps by profile.top_n_tailored; here you asked explicitly, so
    # honour every id you passed.
    gen.tailor_top(ranked, profile, materials, limit=len(ranked))

    sheet = None
    if settings.google_sheet_id:
        try:
            from .sheets import Sheet

            sheet = Sheet(settings)
        except Exception as exc:
            log.warning("Sheet unavailable (%s) — links not written back.", exc)

    for r in ranked:
        print(f"\n=== {r.job.title} @ {r.job.company} ({r.job.short_id()}) ===")
        if r.cv_link or r.cl_link:
            print(f"  CV:           {r.cv_link or '(not created)'}")
            print(f"  Cover letter: {r.cl_link or '(not created)'}")
            if sheet:
                if sheet.update_document_links(r.job.short_id(), r.cv_link, r.cl_link):
                    print("  (links written to your sheet)")
        elif r.documents:
            print("\n--- CV ---\n" + r.documents.get("cv", ""))
            print("\n--- COVER LETTER ---\n" + r.documents.get("cover_letter", ""))
        else:
            print("  Generation failed — see the log above.")

    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
