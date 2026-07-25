# JBHNTR, Architecture

Turning the personal `jobhunter` engine into a public service.

## Principles

1. **The engine is unchanged.** `jobhunter/` stays a library. The web app calls
   it; it never imports the web app. Everything already tested stays tested.
2. **Config moves from YAML to the database.** The one real refactor: build a
   `Profile` object from a user's DB rows instead of `config/profile.yaml`.
3. **Server-rendered.** FastAPI + Jinja2 + HTMX. No separate frontend, no build
   step, no API surface to secure twice. Fastest path to a working product.
4. **Nothing runs synchronously in a web request.** A search takes minutes, so
   it's a background job; the page polls for progress.

## Stack

| Layer | Choice | Why |
|---|---|---|
| Web | FastAPI + Jinja2 + HTMX | One language, no JS toolchain |
| DB | Postgres (SQLite locally) | Railway-managed |
| Queue | Redis + RQ | Simple; searches are minutes-long |
| Host | Railway | Already subscribed; managed Postgres/Redis, TLS, cron |
| DNS/TLS | Cloudflare | Free WAF + rate limiting in front of the app |
| Auth | Session cookie; password **or** Google OAuth | No JWT complexity for a server-rendered app |
| Payments | *Deferred*, "coming soon" | See DECISIONS |
| Analytics | Plausible + a `page_view` table | Cookieless, GDPR-friendly |

## Request flow

```
Browser ──► Cloudflare ──► Railway (FastAPI)
                               │
              ┌────────────────┼─────────────────┐
              ▼                ▼                 ▼
          Postgres          Redis            Encrypted
      users/profiles/     job queue         file storage
       jobs/feedback                        (CVs, ≤1 MB)
                               │
                               ▼
                        Worker process
                     imports `jobhunter`
                     → sources → dedup → triage → score
                     → writes JobResult rows
```

## Data model

```
users              id, email, password_hash?, google_sub?, created_at,
                   plan ('free'|'premium'), searches_used, deleted_at,
                   tos_accepted_at, marketing_opt_in
profiles           user_id, objective, about_me, seniority[], company_type[],
                   verticals[], locations[], job_type[], salary_floor,
                   search_terms[], completed_at
materials          id, user_id, kind ('cv'|'cover_letter'|'linkedin'),
                   filename, mime, size_bytes, ciphertext, created_at
seed_companies     id, user_id, name_or_url
searches           id, user_id, status, started_at, finished_at,
                   raw_count, scored_count, error
job_results        id, search_id, user_id, short_id, tier, score, title,
                   company, company_url, company_blurb, location, tags[],
                   why_good, why_bad, description, apply_url, source
feedback           id, job_result_id, user_id, vote ('up'|'down'), note(300)
documents          id, job_result_id, user_id, kind ('cv'|'cl'), content,
                   created_at            -- counts against the free allowance
page_views         id, path, referrer, country, created_at   -- no user id
```

All array fields are Postgres `ARRAY(TEXT)`; on SQLite they degrade to JSON.

## Profile completeness gate

A search is blocked until the profile is **complete**. Required:

| Field | Why required |
|---|---|
| ≥1 CV | Without it the matcher has no candidate context |
| About me | Carries the nuance the CV can't |
| Objective ("what I want") | The single strongest matching signal |
| Seniority | Filters the biggest source of false positives |
| Company type | Drives the company-shape judgement |
| Verticals | Sector targeting |
| Locations | The only free (non-AI) filter we have |
| Job type | Full-time vs contract |

Optional but scored for *quality*: cover letters, LinkedIn export, seed
companies, search terms, salary floor. The search page shows
**"Improve your profile for better results"** whenever the completeness score is
below ~70%, listing exactly what's missing. Rationale: thin input produces bad
matches, and users blame the product rather than the input.

## Search lifecycle

```
POST /search  →  quota check  →  profile-complete check
              →  enqueue job, status='queued'   (returns immediately)
Worker        →  build jobhunter Profile+Materials from DB
              →  sources.collect_all()   [LinkedIn disabled, see DECISIONS]
              →  dedup + prefilter
              →  triage (cheap model)  →  enrich descriptions
              →  score (tier 1-5, tags, why_good/why_bad)
              →  write job_results, status='done'
Page          →  HTMX polls /search/{id}/status every 3s
```

## Cost model

Per search, at OpenRouter prices:

| Stage | Model | ~Cost |
|---|---|---|
| Triage | Haiku 4.5 / Gemini Flash Lite | $0.01–0.10 |
| Scoring | Haiku 4.5 | $0.20–0.60 |
| CV/CL (on demand) | Sonnet 5 | $0.03 each |
| **Total per search** | | **$0.30–1.00** |

Implications:
- Free tier of 3 searches ≈ **$1–3 of spend per signup**. Free users are put on
  the cheaper scoring model.
- "Unlimited" premium carries a **fair-use ceiling** (default 2 searches/day,
  stated in the T&Cs), without it one user can cost more than they pay.
- Both limits live in `web/app/config.py`, not scattered through the code.

## Decisions taken

| Decision | Choice | Reason |
|---|---|---|
| LinkedIn | **Disabled in the public product** | Scraping it commercially is what LinkedIn sues over (it shut down Proxycurl). Replaced by a licensed provider (SerpApi/Bright Data) behind `LICENSED_SEARCH_PROVIDER`. The personal CLI keeps LinkedIn. |
| Payments | **"Coming soon"** | Ship and validate first; avoids MiCA/VAT/AML work on day one. Stripe is the intended path. |
| Free tier | 3 searches, cheap model | Bounds acquisition cost |
| Premium | Unlimited + fair use | Bounds worst case |
| Frontend | Server-rendered | One less system to build and secure |

## Scaling: the shared job corpus (Phase 2)

Today every search fetches from all sources and AI-scores its own jobs. Cost
grows with *users × jobs*, and two users in the same niche each pay to score
the same postings. The fix is to **decouple ingestion from matching**: store
every job once in a shared corpus, tag and embed it once, and let matching read
from the corpus instead of re-doing that work per user.

**This is built incrementally and does NOT change the free/paid product yet.**
Free users keep full fresh searches. The corpus is introduced first as a
*write-through cache*, then as a *pre-filter*, then as a *score cache*, each
slice independently shippable and safe.

### The one invariant: corpus = write-through cache, not a job source

A search still **fetches fresh from the live sources every time**, so results
are exactly as fresh as today. The corpus sits alongside: each fetched job is
deduped against it, its cached tags/embedding/score are reused if present, and
new jobs are written back. We do **not** serve other users' previously-stored
jobs into a result set, that would resurrect dead listings. Pulling from the
corpus as a discovery source is a later, separate decision gated on adding TTL
+ re-crawl (see freshness, below).

### Schema

```
jobs                 id, dedup_key (UNIQUE), source, title, company, location,
                     description, url, posted_date,
                     -- deterministic tags (no AI): computed at ingestion
                     countries[]  (ISO codes, from geo.py),
                     remote_mode  ('remote'|'hybrid'|'onsite'|'unknown'),
                     salary_min, salary_max, has_salary,
                     -- freshness
                     first_seen_at, last_seen_at
job_embeddings       job_id (FK, UNIQUE), model, dim, vector (bytes/pgvector),
                     created_at            -- Phase 2 slice 3
score_cache          id, job_id (FK), input_hash (see below), model,
                     prompt_version, tier, score, reasons, tags[], created_at
                     UNIQUE(job_id, input_hash)   -- Phase 2 slice 4
```

`dedup_key` is `JobPosting.dedup_key()` (company+title, URL fallback) so the
same role from three sources is one row. Deterministic tags come from
`jobhunter/tags.py`; they are the *reliable* dimensions and the only ones used
as hard filters.

### The cache-key rule (the part that must not be gotten wrong)

A cached score is only reusable if **every input that produced it is
unchanged**. `input_hash` is a hash of, in order:

1. the job's `dedup_key` + its description length (content changes ⇒ re-score)
2. the user's scoring-relevant profile: objective, about_me, seniority,
   company_type, verticals, locations, salary_floor
3. the derived candidate profile, company profile, and criteria
4. the concatenated materials (CV/cover-letter text)
5. the feedback examples in play
6. **the model id** and a **`PROMPT_VERSION` constant** bumped whenever the
   scoring prompt changes

Miss any of these and a prompt tweak or profile edit silently serves stale
matches, the worst failure mode because it looks correct. `PROMPT_VERSION`
lives next to the prompt builder; changing the prompt without bumping it is a
review-blocking bug.

### What each slice saves, and what it does NOT

| Slice | Change | Saves | Caveat |
|---|---|---|---|
| 1 ✅ | corpus table + deterministic tags + write-through upsert | nothing yet, pure plumbing | reads nothing; cannot change behaviour |
| 1b ✅ | reaper: TTL delete + link-check dead postings | keeps corpus fresh; prerequisite for corpus-as-source | wrong deletes self-heal (write-through re-adds); keep the unreachable |
| ~~2~~ | ~~SQL hard-filter (geo/remote) replaces triage~~ **dropped** | ~~nothing in practice~~ | **geo + remote are already hard-filtered for free by the per-search `prefilter` (location tokens + `looks_remote`). A corpus SQL filter only matters in corpus-as-source mode. Triage's real work is *semantic*, which tags can't do.** |
| 3 | embeddings (cached per job) → cosine rank → top-K into the LLM | shrinks/【replaces】the AI triage **and** the LLM scoring shortlist, the real per-search lever | embeddings **rank, never hard-cut**; start with a generous K, tighten only after measuring rank-vs-tier correlation |
| 4 | `score_cache` keyed on `input_hash` | repeat / near-identical searches ≈ free | **plumbing only at first**, do not rely on it until the scoring prompt stabilises, or you cache-and-invalidate constantly |

**Correction (found while building):** the original slice-2 (“SQL filter replaces
triage”) was wrong. The per-search `prefilter` already applies the geo and
remote hard cuts for free, so a tag-based SQL filter saves nothing while jobs
are matched from a fresh fetch. Embeddings (slice 3) are the genuine next lever.

**Honest magnitude.** The dominant cost is per-user LLM scoring of the
shortlist, and that is *per user*, the corpus does not eliminate it, because
two users rarely share a profile (cross-user score-cache hits are near zero).
The immediate wins from slices 1–3 are: triage removed, a ~50% smaller LLM
shortlist, and cheap repeat searches. The large cross-user savings only unlock
if/when free users are tiered to match against the cached corpus instead of
fetching fresh, a **deliberately deferred** product decision, because it trades
away freshness and needs TTL + re-crawl first.

### Freshness (the operational cost this buys)

Postings close within weeks. Before the corpus is ever used as a *source*
(not just a cache), it needs: a `last_seen_at` TTL (drop/of re-verify jobs older
than ~30–45 days) and a background re-crawl. Until then the write-through design
keeps freshness identical to today, so this is not yet on the critical path.

### Keywords stay out of hard filtering

Tag dimensions are geo, remote-mode, salary, deterministic and safe. Keyword
matching is **not** a hard-filter tag: it reintroduces the false-negative bug
that `keywords_must` was removed for. Keyword relevance is captured by the
embeddings (slice 3), used to rank, never to exclude.

## What is deliberately NOT in Phase 1

Payments, referrals, teams, an email digest for web users, a public API,
mobile apps. Each is easy to add later; none is needed to prove the product.
