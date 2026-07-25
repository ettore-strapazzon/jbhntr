# JBHNTR, Ingestion Engine (daily-ingest + search-against-corpus)

The design for turning JBHNTR from *fetch-and-score-on-every-search* into a
*continuously-ingested corpus that searches read from*. This is the real
product engine. Written before code, same as the rest of `docs/`.

Prereqs already built: the `jobs` corpus + deterministic tags (write-through,
slice 1), the reaper (freshness), per-user geo, and `discover.py` /
`sources/ats.py` (company discovery + public ATS feeds, CLI today).

---

## 1. Why

Today every search fetches ~2,600 jobs live from 25+ sources, then AI-scores
them, slow (minutes) and costly, and it repeats that work for every user and
every re-search. Two users in the same niche pay twice for the same jobs.

Target: **fetch once for everyone on a schedule; make each search read a local,
tagged, embedded corpus.** Searches become fast (no live fetch) and cheap
(fetch cost amortised across all users and all searches, not per-search).

Trade accepted: jobs are up to one ingest-cycle stale (~a day). Fine for job
hunting, and the reaper + re-ingest keep it honest.

---

## 2. Shape

```
        ┌─────────────────── INGESTION (scheduled, daily) ──────────────────┐
        │  Lane A: global feeds      remote boards, Muse, Arbeitnow …        │
        │  Lane B: keyword aggregators  Adzuna/Careerjet/Jooble × corpus     │
        │                               terms × country  (quota-bounded)     │
        │  Lane C: company ATS boards   shared company registry (below)      │
        │            │                                                        │
        │            ▼   dedup → deterministic tags → embed → upsert          │
        └────────────┼────────────────────────────────────────────────────── ┘
                     ▼
                ┌─────────┐        ┌──────────────┐
                │  jobs   │◄───────│   reaper     │ TTL + link-check (built)
                │ corpus  │        └──────────────┘
                └────┬────┘
                     │  SEARCH (per user, fast, no live fetch)
                     ▼
   SQL hard-filter (geo/remote/fresh)  →  embedding cosine rank  →  top-K
                     │                                                 │
                     └──────────────► LLM score (cached per input) ────┘
                                              │
                                     rank → tier 1-3 + long shots
```

Jobs in the corpus are **global**; *relevance is per-user*, applied at search
time by geo/remote SQL filters + the profile-vs-job embedding similarity. One
corpus serves everyone; no per-user copies.

---

## 3. Ingestion, the three lanes

A scheduled job (Railway cron) runs all three, then dedup → tag → embed →
upsert. Each lane fails soft and independently.

### Lane A, global feeds (no query needed)
Remote boards and no-key aggregators whose feeds return *everything* (RSS/JSON):
RemoteOK, Remotive, Jobicy, WeWorkRemotely, Himalayas, NoDesk, WorkingNomads,
4DayWeek, RealWorkFromAnywhere, The Muse, Arbeitnow, Bundesagentur, LandingJobs,
CryptocurrencyJobs, BerlinStartupJobs. Fetch in full, once per cycle. Cheap,
no per-user anything.

### Lane B, keyword aggregators (query-driven, quota-bounded)
Adzuna, Careerjet, Jooble, Reed, Findwork, Web3career query by keyword, so the
corpus needs a **term set** and a **country set**:
- **Country set** = the distinct countries of all *active* users (via `geo`),
  capped. Cold-start: a seed list (us, gb, it, de, …).
- **Term set** = the union of active users' derived `target_roles` + typed
  search terms, de-duplicated and **capped hard** (e.g. 25 terms) to respect
  metered quotas (Jooble = 500 req/mo total!). Terms are ranked by how many
  users want them, so popular roles are always covered.
- Requests/cycle = terms × countries × sources, must stay inside the smallest
  free quota. This is the main tuning knob; see §8.

### Lane C, company ATS boards (public, unmetered) ⭐
The shared **company registry** (below). Every company in it is polled via its
public ATS feed (`sources/ats.py`) each cycle. No keys, no quotas, direct from
the employer, and the answer to most of the "LinkedIn-exclusive" gap, since
companies post to their own ATS too.

---

## 4. Per-user discovery → shared company registry

The mechanism that grows Lane C and personalises coverage without per-user
scraping.

```
user completes profile ──► discover.py (web search + LLM)
      seeds ──► ~100 similar companies ──► detect ATS ──► companies registry
                                                 │
                              ingestion Lane C polls ALL registry companies
```

- **Trigger:** on profile completion / first search, and refreshed on a slow
  cadence (weekly–monthly, not daily, discovery uses web search + LLM and is
  the pricey part). Cache aggressively.
- **Output shared, not per-user:** discovered companies land in one
  `companies` table, deduped by domain/ATS-token. Two fintech-seeking users
  contribute overlapping companies; **everyone's corpus benefits.**
- **Readable-ATS reality:** ~half of discovered companies expose a readable
  board (embedded/private widgets don't). Store the rejects with a reason so we
  don't re-probe them every cycle (as `discover.py` already does).
- **Relevance still per-user:** a discovered company's jobs are in the global
  corpus; whether they surface for a given user is decided at search time by
  geo + embedding similarity, not by who discovered them.

Optional later: a `user_companies` link so a user's *own* seed-discovered
companies get a small relevance boost in their ranking.

---

## 5. Search, rewired onto the corpus

Replaces live fetch + AI triage. Per user, per search:

1. **SQL hard-filter** the corpus: country ∈ user's countries (or remote-mode
   matches), `last_seen_at` within freshness window, not reaped. Free, instant.
   This is where the deterministic tags finally earn their keep.
2. **Embedding rank:** cosine(user profile embedding, candidate job embeddings)
   → take a **generous top-K** (start ~60, matching today's post-triage count).
   Replaces the AI triage stage with cached vector math.
3. **LLM score** the top-K (the existing scorer, now parallel), **cached per
   input-hash** (§7) so repeats and cross-search overlaps are ~free.
4. Rank → tier 1-3 + tier-4 long shots (already built).

Fallback during migration: if the corpus is cold/empty for a user, fall back to
today's live-fetch path so search never returns nothing.

---

## 6. Embeddings

- **Per job (once, at ingestion):** embed `title + company + trimmed
  description`; store on the corpus row (or a `job_embeddings` table). ~$0.02
  per 1M tokens with a small model, negligible vs LLM scoring.
- **Per user:** embed `objective + about_me + target_roles + skills`; cache;
  re-embed only when those change.
- **Storage/search:** SQLite dev → vector as bytes/JSON, brute-force cosine in
  Python over the SQL-filtered subset (fine for thousands). Postgres prod →
  `pgvector` with an index.
- **Guardrail (your rule):** embeddings **rank, never hard-cut**. Start with a
  generous K; only tighten after measuring how well embedding rank predicts the
  LLM's tier on real runs. No good job is dropped before the LLM sees it.

---

## 7. Score cache

- **Table:** `score_cache(job_id, input_hash, model, prompt_version, tier,
  score, reasons, tags, created_at)`, UNIQUE(job_id, input_hash).
- **`input_hash`** = hash of, in order: job `dedup_key` + description length;
  user scoring-relevant profile (objective, about_me, seniority, company_type,
  verticals, locations, salary_floor); derived candidate/company-profile/
  criteria; materials text; feedback examples; **model id**; **`PROMPT_VERSION`
  constant**. (Contract already written in ARCHITECTURE.md.)
- **Reliance deferred:** build the plumbing, but keep it conservative until the
  scoring prompt stabilises, we're still tuning it (bidirectional match,
  blockers). A prompt change bumps `PROMPT_VERSION` and invalidates cleanly.

---

## 8. Scheduling, quotas, infra

- **Railway cron** (already available): ingestion once daily (tune to 2–3×/day
  if freshness demands); reaper daily; discovery refresh weekly.
- **Entrypoints:** `python -m web.app.ingest` (the three lanes), reaper `run()`
  (built), a discovery refresh command.
- **Quota budget is the hard constraint.** Lane B must stay inside the smallest
  metered free tier. With Jooble at 500 req/mo: 25 terms × 1 country ×
  ~1 cycle/day already ≈ 750, over budget. So Lane B needs either per-source
  term caps, per-source cycle throttling (Jooble weekly, Adzuna daily), or a
  requested quota increase. **Design decision: per-source config for
  {terms cap, countries cap, cadence}.**
- **Idempotent:** ingestion only upserts; a re-run is safe.

---

## 9. Schema additions

```
companies          id, name, domain, ats ('greenhouse'|'lever'|…|'none'),
                   ats_token, source ('seed'|'discovered'), discovered_for?,
                   last_polled_at, reason_if_unreadable
job_embeddings     job_id (FK, UNIQUE), model, dim, vector, created_at
score_cache        (see §7)
jobs               + embedding cols or FK to job_embeddings; keep tags/freshness
```
`companies` promotes today's `config/companies.yaml` (CLI) into the DB, shared
across users. Additive-migration helper handles new columns; new tables via
`create_all` (both already in place).

---

## 10. Free vs paid tiering (design for it; ship later)

- **Free:** search reads the corpus only, no live fetch, no metered-source
  calls on their behalf. Fast, near-zero marginal cost.
- **Paid:** may trigger a **fresh fetch for their specific query**, adding new
  jobs to the corpus immediately and scoring them live.
This is both the monetisation lever and the quota shield: metered sources are
hit by the scheduled ingestion and paid fresh-fetches, never by every free
search.

---

## 11. Build order (incremental; app keeps working throughout)

1. ✅ **Ingestion job, Lane A + B**, standalone `ingest` entrypoint on cron.
2. ✅ **Company registry + Lane C + per-user discovery**, companies in DB,
   `discover.py` wired into web (budgeted, accumulating), ATS polled in ingest.
3. ✅ **Embeddings**, local (fastembed) or hosted; embed at ingestion; cosine.
4. ✅ **Rewire search onto the corpus**, SQL geo-filter → cosine rank → score;
   live-fetch is the cold-start fallback. The flip that makes searches fast.
5. ✅ **Score cache**, keyed on `input_hash` (incl. `matcher.PROMPT_VERSION`);
   plus Anthropic prompt-caching on the scoring system block.
6. ⬜ **Tiering**, free = corpus-only; paid = fresh fetch. (Deferred.)

Also done: discovery runs on the cheaper scoring model (was Sonnet), and a
`PROMPT_VERSION` bump cleanly invalidates the score cache as matching is refined.

Each step is shippable and reversible. Steps 1–2 add coverage with zero search
risk (write-only, like slice 1 was). Step 4 is the one that changes the search
path, gated behind the cold-start fallback.

---

## 11b. Lane-B request budget (settled)

Requests per cycle per source, from the actual adapters:

| Source | req pattern | free quota | geo scope | notes |
|---|---|---|---|---|
| **Jooble** | terms × countries | **500 / month** (confirmed) | ~70 countries | **binding** |
| **JSearch** | terms × 1 | **~200 / month** (RapidAPI Basic) | US-effective (Google Jobs) | **binding**; EU-empty |
| Adzuna | countries × terms | generous (~hundreds/day), *confirm monthly cap* | ~20 countries | main multi-country |
| Careerjet | terms × countries | no fixed monthly cap; rate-limited | ~90 countries | throttle, don't burst |
| Reed | terms × 1 | generous; rate-limited | UK only | gate to `gb` |
| USAJOBS | terms × 1 | generous (gov) | US only | gate to `us` |
| Findwork | terms × 1 | freemium, *confirm limit* | tech, global | lower priority |
| Web3career | 1 (bulk 100) | freemium | crypto | trivial, 1 call |

Two sources bind the design: **Jooble (500/mo)** and **JSearch (~200/mo)**.
Everything else is either generous, single-country, or a single bulk call.

**Fitting the binding two:**
- Jooble @ 25 terms × 5 countries = 125 req/cycle. Daily (≈30×) = 3,750/mo, 7×
  over. **Weekly** (≈4.3×): 20 terms × 5 countries = 100/cycle ≈ **430/mo** ✓.
- JSearch @ US only, 1 req/term. **Weekly**, 40 terms ≈ **170/mo** ✓ (daily
  would need ≤6 terms, too thin).

**Recommended per-source config** (the `{terms, countries, cadence}` knob from §8):

```
adzuna:     terms 25, countries = active users' (cap 6), daily     # confirm monthly cap
careerjet:  terms 25, countries = active users' (cap 6), daily     # throttled
jooble:     terms 20, countries = top 5 by user demand,  WEEKLY    # 500/mo ceiling
reed:       terms 25, countries [gb],                    daily
usajobs:    terms 25, countries [us],                    daily
jsearch:    terms 40, countries [us],                    WEEKLY    # ~200/mo ceiling
findwork:   terms 25, (no country),                      WEEKLY    # 429s on daily load
web3career: 1 bulk call,                                 daily
```

Term set = union of active users' `target_roles` + typed terms, ranked by how
many users want each, capped per the table. Country set = distinct countries of
active users (via `geo`), capped at 6; Jooble takes the top 5 by demand.

**Today (1 user, Italy, ~8 terms):** every source is trivially inside quota,
Jooble ≈ 8 × 1 × 4 = 32/mo, JSearch skipped (no US). The caps only bind once
there are many users across many countries, and cadence is the release valve.

**To confirm in dashboards (not guesses):** Adzuna monthly cap, Findwork free
limit, Reed rate limits. If any is tighter than assumed, drop that source to
weekly, the config knob already supports it.

## 12. Open questions

- ~~Lane B budget~~ **settled in §11b** (per-source cadence; Jooble + JSearch
  weekly). Three quota numbers to *confirm in dashboards*: Adzuna monthly,
  Findwork free limit, Reed rate limits.
- **Embedding provider** (step 3, not step 1), reuse the OpenRouter key
  (OpenAI-compatible embeddings) or a dedicated provider? Cost and rate limits.
- **Discovery cost at N users** (step 2), cap discovered companies/user,
  refresh cadence.
- **Corpus growth**, TTL window + reaper cadence sizing as the corpus scales.
