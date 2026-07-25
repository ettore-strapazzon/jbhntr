"""Find companies worth watching, then verify they really are hiring.

This is the "inverted funnel": instead of scraping the whole world and
filtering, we first shortlist companies that match your search, then poll only
those career pages.

    python -m jobhunter.discover                    # propose 100, verify, show
    python -m jobhunter.discover --write            # ...and save them
    python -m jobhunter.discover -n 1000 --write    # grow toward a big list

How it works:

1. **Seeds steer the search.** Any company already in `companies.yaml`, plus any
   name under a `seeds:` list there, is shown to Claude as an example of "the
   kind of company I want". Discovery then asks for *more like these* — which
   gives far better targeting than abstract criteria alone.
2. Claude proposes companies; already-known ones are excluded so each round
   brings new names.
3. Every proposal is **verified against a real ATS board** and dropped unless a
   board answers with real jobs. That is what makes step 1 safe: an invented or
   no-longer-hiring company simply fails and never reaches your config.
4. For big targets it runs in **rounds**, stopping early when rounds stop
   yielding new verified companies.

Probe results are cached in `data/company_probes.json`, so re-running is fast
and doesn't re-hammer the same boards.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import llm
from . import seeds as seeds_mod
from .config import (
    CONFIG_DIR,
    DATA_DIR,
    Profile,
    Settings,
    load_companies,
    load_profile,
    load_seeds,
)
from .sources import ats as ats_mod
from .sources.ats import FETCHERS

log = logging.getLogger("jobhunter.discover")

# ATS platforms whose board token we can guess from a company slug.
GUESSABLE = ["greenhouse", "lever", "ashby", "recruitee", "smartrecruiters", "bamboohr"]

PROBE_CACHE = DATA_DIR / "company_probes.json"

ROUND_SIZE = 100        # companies requested per LLM round
MAX_EXEMPLARS = 40      # seed names shown to Claude as "more like this"
MAX_EXCLUSIONS = 400    # known names sent to Claude to avoid repeats
STOP_AFTER_DRY_ROUNDS = 2  # consecutive rounds adding nothing new -> stop

SUGGEST_SCHEMA = {
    "type": "object",
    "properties": {
        "companies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "slug": {
                        "type": "string",
                        "description": "lowercase no-spaces handle, e.g. 'nvidia'",
                    },
                    "domain": {
                        "type": "string",
                        "description": "company website domain, e.g. 'nvidia.com'; "
                                       "empty string if unknown",
                    },
                    "why": {"type": "string"},
                },
                "required": ["name", "slug", "domain", "why"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["companies"],
    "additionalProperties": False,
}

# Live web research is provided by the LLM backend (see jobhunter/llm.py):
# native server-side search on Anthropic, ':online' models on OpenRouter.


# --------------------------------------------------------------------------- #
# Probe cache
# --------------------------------------------------------------------------- #
def _load_cache() -> dict:
    if not PROBE_CACHE.exists():
        return {}
    try:
        return json.loads(PROBE_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    PROBE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    PROBE_CACHE.write_text(json.dumps(cache, indent=0), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Step 1: propose
# --------------------------------------------------------------------------- #
def research(
    profile: Profile, settings: Settings, n: int, exemplars: list[str], criteria=None
) -> str:
    """Search the live web for companies matching the profile. Returns notes."""
    client = llm.get_client(settings)
    locations = ", ".join(profile.locations) or "anywhere"
    verticals = ", ".join(profile.verticals) or "any sector"

    prompt = "\n".join(
        [
            f"Research and list about {n} real companies that a candidate with "
            "this job search should watch. Use web search — do not rely on "
            "memory alone. Prioritise CURRENT information.",
            "",
            f"Objective: {profile.objective or '(unspecified)'}",
            f"Locations: {locations}",
            f"Sectors: {verticals}",
            f"Company types: {', '.join(profile.company_type) or 'any'}",
            "",
            "Search across several angles, for example:",
            f"- startups in {locations} that raised funding in the last 24 months",
            f"- {verticals} companies in {locations} that are actively hiring engineers",
            "- recent tech-press coverage, funding announcements and PR",
            "- local/regional startup ecosystem lists and accelerator portfolios",
            "- companies expanding or opening offices in those locations",
            "",
        ]
        + (
            [
                "The candidate already rates these companies — find companies of "
                "the same character (size, stage, sector, engineering culture):",
                "; ".join(exemplars[:MAX_EXEMPLARS]),
                "",
            ]
            if exemplars
            else []
        )
        + [
            "Favour small and mid-size companies and recent funding rounds over "
            "household names — those are exactly what a generic list would miss.",
            "",
            "For each company, give: the company name, its website domain, and a "
            "one-line reason it fits (mention the funding round or news if that "
            "is why you picked it).",
        ]
        + (
            [
                "",
                "## Target the following criteria",
                criteria.as_prompt_block(),
                "",
                f"A company qualifies if it meets at least {profile.min_must} "
                f"MUST-HAVE and {profile.min_nice} NICE-TO-HAVE criteria. Say "
                "which criteria each company meets. Search for the criteria "
                "themselves — e.g. look for companies at the right stage, in the "
                "right sector and geography — rather than only for companies "
                "resembling the examples.",
            ]
            if criteria is not None and not criteria.is_empty()
            else []
        )
    )
    return client.text(user=prompt, tier=llm.SCORING, web_search=True)


def extract_companies(notes: str, settings: Settings, exclude: list[str]) -> list[dict]:
    """Turn free-text research notes into a structured company list.

    Kept as a separate, tool-free call because structured outputs cannot be
    combined with the citations that web search returns.
    """
    prompt = [
        "Extract every distinct company mentioned in these research notes.",
        "For each: name, `slug` (lowercase no-spaces handle used in careers URLs),",
        "`domain` (website domain, or empty string if not stated), and `why`.",
        "Include only real companies. Do not invent any that aren't in the notes.",
    ]
    if exclude:
        prompt += ["", "Skip these, already known:", ", ".join(exclude[:MAX_EXCLUSIONS])]
    prompt += ["", "## Research notes", notes[:60000]]

    data = llm.get_client(settings).json(
        system="You extract structured company lists from research notes.",
        user="\n".join(prompt),
        schema=SUGGEST_SCHEMA,
        tier=llm.SCORING,
        max_tokens=16000,
        cache_system=False,
    )
    return data.get("companies", [])


def suggest(
    profile: Profile,
    settings: Settings,
    n: int,
    exemplars: list[str],
    exclude: list[str],
    web_search: bool = True,
    criteria=None,
) -> list[dict]:
    """Propose companies matching the profile. Unverified at this point.

    With `web_search` we research the live web first (much better for small,
    recent or country-specific companies); otherwise we fall back to the
    model's own knowledge.
    """
    if web_search:
        if not llm.get_client(settings).supports_web_search:
            log.info(
                "Provider has no web search; using model knowledge. "
                "(On OpenRouter, live search works via ':online' models.)"
            )
        else:
            try:
                notes = research(profile, settings, n, exemplars, criteria)
                if notes.strip():
                    found = extract_companies(notes, settings, exclude)
                    if found:
                        return found
                log.warning("Web research returned nothing usable; using model knowledge.")
            except Exception as exc:
                log.warning("Web search unavailable (%s); using model knowledge.", exc)

    parts = [
        f"List {n} real companies a candidate with this job search should watch.",
        "",
        f"Objective: {profile.objective or '(unspecified)'}",
        f"Company types: {', '.join(profile.company_type) or 'any'}",
        f"Verticals: {', '.join(profile.verticals) or 'any'}",
        f"Locations: {', '.join(profile.locations) or 'any'}",
        f"Relevant skills: {', '.join(profile.keywords_nice) or 'any'}",
    ]

    if exemplars:
        parts += [
            "",
            "## Companies the candidate already values — find MORE LIKE THESE",
            ", ".join(exemplars[:MAX_EXEMPLARS]),
            "Match their character: similar size, stage, domain, engineering "
            "culture and hiring profile. This is the strongest signal you have — "
            "weight it above the abstract criteria above.",
        ]

    if exclude:
        parts += [
            "",
            "## Already on the list — do NOT propose any of these again",
            ", ".join(exclude[:MAX_EXCLUSIONS]),
        ]

    parts += [
        "",
        "Rules:",
        "- Only real, currently-operating companies.",
        "- Prefer ones that actually hire this profile in these locations.",
        "- `slug` = the handle in their careers URL (lowercase, no spaces).",
        "- Favour companies that run a public job board.",
        "- Never repeat a company, within this list or from the exclusions.",
    ]

    data = llm.get_client(settings).json(
        system="You suggest real companies matching a candidate's job search.",
        user="\n".join(parts),
        schema=SUGGEST_SCHEMA,
        tier=llm.SCORING,
        max_tokens=16000,
        cache_system=False,
    )
    return data.get("companies", [])


# --------------------------------------------------------------------------- #
# Step 2: verify
# --------------------------------------------------------------------------- #
def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def verify(name: str, slug: str, domain: str = "") -> tuple[str, str, int] | None:
    """Probe each guessable ATS for this company. Returns (ats, token, n_jobs).

    A website domain is the strongest hint for the board handle, so try it
    first when we have one.
    """
    guesses = []
    if domain:
        guesses.append(_slugify(domain.split(".")[0]))
    guesses += [slug, _slugify(name)]
    candidates = [c for c in dict.fromkeys(guesses) if c]

    for ats in GUESSABLE:
        fetch = FETCHERS[ats]
        for token in candidates:
            try:
                jobs = fetch(name, token)
            except Exception:
                continue
            if jobs:
                return (ats, token, len(jobs))

    # Guessing only works when the board handle resembles the company name.
    # Plenty of companies use an unrelated handle, or host the careers page on
    # their own domain and embed the board — Kraken and Scalapay both did, and
    # both were being written off as "no public job board". Read the page.
    return _verify_via_careers_page(name, domain)


CAREERS_PATHS = ("careers", "jobs", "careers/open-positions", "company/careers")


def _verify_via_careers_page(name: str, domain: str) -> tuple[str, str, int] | None:
    """Last resort: find the board a company's own careers page points at."""
    if not domain:
        return None
    urls = [f"https://{domain}/{p}" for p in CAREERS_PATHS]
    urls += [f"https://careers.{domain}", f"https://jobs.{domain}"]
    for url in urls:
        try:
            ats, token = ats_mod.detect(url)
        except Exception:
            continue
        if not (ats and token) or ats not in FETCHERS:
            continue
        try:
            jobs = FETCHERS[ats](name, token)
        except Exception:
            continue
        if jobs:
            log.info("%s: found %s:%s via %s", name, ats, token, url)
            return (ats, token, len(jobs))
    return None


def _verify_cached(name: str, slug: str, cache: dict, domain: str = ""):
    key = f"{_slugify(name)}|{slug}|{domain}"
    if key in cache:
        hit = cache[key]
        return tuple(hit) if hit else None
    result = verify(name, slug, domain)
    cache[key] = list(result) if result else None
    return result


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def discover(
    profile: Profile,
    settings: Settings,
    target: int,
    workers: int = 16,
    use_cache: bool = True,
    web_search: bool = True,
    seeds: list[str] | None = None,
    max_rounds: int | None = None,
    exclude: list[str] | None = None,
):
    """Run rounds of propose+verify until `target` verified companies or stall.

    `seeds` overrides the config seed list — the web product passes a specific
    user's seeds so discovery is personalised. Defaults to the config file so
    the CLI is unchanged.

    `max_rounds` caps how many propose+verify rounds run in one call, so a
    scheduled job stays short and *accumulates* across runs (results persist in
    the caller's registry) instead of blocking for many minutes. `exclude`
    names companies already known to the caller, so repeated runs propose new
    ones rather than re-finding the same set.
    """
    cache = _load_cache() if use_cache else {}

    tracked = load_companies()
    seed_objs = seeds_mod.resolve(seeds if seeds is not None else load_seeds())
    # Seeds (described from their websites where possible) plus already-tracked
    # companies steer the search; both are also excluded from results.
    exemplars = [s.label() for s in seed_objs]
    exemplars += [c.get("name") or c.get("token", "") for c in tracked]
    exemplars = [e for e in exemplars if e]

    known = {_slugify(s.name) for s in seed_objs}
    known |= {_slugify(c.get("name") or c.get("token", "")) for c in tracked}
    known |= {_slugify(n) for n in (exclude or [])}   # already in caller's registry
    known.discard("")

    # The criteria give discovery concrete targets to search for, instead of
    # only "companies resembling these examples".
    from .criteria import derive as derive_criteria

    criteria = derive_criteria(profile, [s.label() for s in seed_objs], settings)

    verified: list[dict] = []
    rejected: list[str] = []
    dry_rounds = 0
    round_no = 0

    while len(verified) < target and dry_rounds < STOP_AFTER_DRY_ROUNDS:
        if max_rounds is not None and round_no >= max_rounds:
            log.info("Discovery hit max_rounds=%d — banking %d and stopping",
                     max_rounds, len(verified))
            break
        round_no += 1
        want = min(ROUND_SIZE, max(20, (target - len(verified)) * 2))
        log.info(
            "Round %d: asking for %d candidates (%d/%d verified so far)",
            round_no, want, len(verified), target,
        )
        try:
            proposed = suggest(
                profile, settings, want,
                exemplars=exemplars,
                exclude=[e for e in exemplars][-MAX_EXCLUSIONS:],
                web_search=web_search,
                criteria=criteria,
            )
        except Exception as exc:
            log.error("Suggestion round failed: %s", exc)
            break

        fresh = [c for c in proposed if _slugify(c.get("name", "")) not in known]
        for c in fresh:
            known.add(_slugify(c.get("name", "")))
        if not fresh:
            dry_rounds += 1
            continue

        log.info("  verifying %d new candidates...", len(fresh))
        found_this_round = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _verify_cached,
                    c.get("name", ""), c.get("slug", ""), cache, c.get("domain", ""),
                ): c
                for c in fresh
            }
            for fut in as_completed(futures):
                c = futures[fut]
                try:
                    hit = fut.result()
                except Exception:
                    hit = None
                if hit:
                    ats, token, count = hit
                    verified.append({
                        "name": c["name"], "ats": ats, "token": token,
                        "jobs": count, "why": c.get("why", ""),
                    })
                    exemplars.append(c["name"])  # successes steer later rounds
                    found_this_round += 1
                else:
                    rejected.append(c.get("name", "?"))

        log.info("  round %d added %d verified companies", round_no, found_this_round)
        dry_rounds = dry_rounds + 1 if found_this_round == 0 else 0

    if use_cache:
        _save_cache(cache)

    verified.sort(key=lambda v: -v["jobs"])
    return verified[:target], rejected


# --------------------------------------------------------------------------- #
def adopt_seeds(workers: int = 12, use_cache: bool = True):
    """Check which of your seed companies have a live job board.

    Seeds normally only steer discovery, but a company you listed as one you'd
    love to work for is obviously worth watching directly — if it publishes
    jobs somewhere we can read.
    """
    cache = _load_cache() if use_cache else {}
    seed_objs = seeds_mod.resolve(load_seeds(), guess_domains=True)
    if not seed_objs:
        return [], []

    verified, rejected = [], []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_verify_cached, s.name, s.slug(), cache, s.domain): s
            for s in seed_objs
        }
        for fut in as_completed(futures):
            s = futures[fut]
            try:
                hit = fut.result()
            except Exception:
                hit = None
            if hit:
                ats, token, count = hit
                verified.append({
                    "name": s.name, "ats": ats, "token": token,
                    "jobs": count, "why": "seed company",
                })
            else:
                rejected.append(s.name)

    if use_cache:
        _save_cache(cache)
    verified.sort(key=lambda v: -v["jobs"])
    return verified, rejected


def write_companies_yaml(verified: list[dict], path: Path, merge: bool = True) -> int:
    """Append verified companies to companies.yaml, skipping ones already there."""
    existing = load_companies(path) if merge else []
    have = {(e.get("ats"), e.get("token")) for e in existing}

    new = [v for v in verified if (v["ats"], v["token"]) not in have]
    if not new:
        return 0

    body: list[str] = []
    for v in new:
        body.append(f"  - name: {v['name']}")
        body.append(f"    ats: {v['ats']}")
        body.append(f"    token: {v['token']}")
        if v.get("why"):
            body.append(f"    # {v['why'][:100]}")

    if path.exists():
        text = path.read_text(encoding="utf-8").rstrip("\n")
        # `companies: []` must become a real list before we can append to it.
        text = re.sub(r"^companies:\s*\[\s*\]\s*$", "companies:", text, flags=re.M)
        if not re.search(r"^companies:", text, flags=re.M):
            text += "\ncompanies:"
        path.write_text(text + "\n" + "\n".join(body) + "\n", encoding="utf-8")
    else:
        header = [
            "# Company career pages to watch.",
            "# Generated by `python -m jobhunter.discover --write`.",
            "# Every entry below was verified to return real job postings.",
            "companies:",
        ]
        path.write_text("\n".join(header + body) + "\n", encoding="utf-8")
    return len(new)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Shortlist and verify companies to watch")
    ap.add_argument("-n", "--count", type=int, default=100,
                    help="How many verified companies to aim for (default 100).")
    ap.add_argument("--write", action="store_true",
                    help="Append verified companies to config/companies.yaml.")
    ap.add_argument("--no-cache", action="store_true",
                    help="Ignore cached probe results and re-check every company.")
    ap.add_argument("--adopt-seeds", action="store_true",
                    help="Check which of your seed companies have a live job board "
                         "and watch those directly. No AI needed.")
    ap.add_argument("--no-web-search", action="store_true",
                    help="Skip live web research; use the model's own knowledge only "
                         "(cheaper, but worse for small/new/local companies).")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    settings = Settings.from_env()

    # Adopting seeds is pure board-probing — no AI, so it runs before the
    # provider check and works even with no API key configured.
    if args.adopt_seeds:
        verified, rejected = adopt_seeds(use_cache=not args.no_cache)
        print(f"\n=== {len(verified)} of your seed companies are hiring ===\n")
        for v in verified:
            print(f"  {v['jobs']:5d} jobs  {v['name'][:32]:32} {v['ats']}:{v['token']}")
        if rejected:
            print(f"\n{len(rejected)} have no public job board we can read "
                  f"(they may still be hiring — check their site):")
            print("  " + ", ".join(rejected))
        if args.write and verified:
            added = write_companies_yaml(verified, CONFIG_DIR / "companies.yaml")
            print(f"\nAdded {added} companies to config/companies.yaml")
        elif verified:
            print("\n(Nothing saved. Re-run with --write to watch these.)")
        return 0

    if not llm.is_configured(settings):
        log.error(
            "No AI provider configured — discovery needs one to suggest companies. "
            "Set ANTHROPIC_API_KEY, or LLM_PROVIDER=openai_compatible with LLM_API_KEY."
        )
        return 2

    profile = load_profile()
    raw_seeds, tracked = load_seeds(), load_companies()
    use_search = profile.discovery_web_search and not args.no_web_search

    if raw_seeds or tracked:
        print(f"Steering search with {len(raw_seeds)} seed(s) and "
              f"{len(tracked)} already-tracked company/ies.")
    else:
        print("No seeds yet — searching from your profile criteria alone.")
        print("Tip: add a `seeds:` list to config/companies.yaml — company "
              "WEBSITES work best (e.g. https://satispay.com).")
    print("Company sourcing: " + ("live web research" if use_search
                                  else "model knowledge only"))

    verified, rejected = discover(
        profile, settings, args.count,
        use_cache=not args.no_cache,
        web_search=use_search,
    )

    print(f"\n=== {len(verified)} companies verified as actively hiring ===\n")
    for v in verified:
        print(f"  {v['jobs']:5d} jobs  {v['name'][:32]:32} {v['ats']}:{v['token']}")
    if rejected:
        print(f"\n{len(rejected)} could not be verified (no public board found, or "
              f"not hiring) and were dropped:")
        print("  " + ", ".join(rejected[:25]) + (" ..." if len(rejected) > 25 else ""))

    total = sum(v["jobs"] for v in verified)
    print(f"\nThose companies expose ~{total:,} job postings in total.")

    if args.write:
        path = CONFIG_DIR / "companies.yaml"
        added = write_companies_yaml(verified, path)
        print(f"\nAdded {added} new companies to {path}")
        print("Next:")
        print("  python -m jobhunter.pipeline --dry-run --limit 20")
    else:
        print("\n(Nothing saved. Re-run with --write to add these to companies.yaml.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
