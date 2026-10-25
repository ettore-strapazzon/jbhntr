# QUOTAS — free-tier cliffs to watch

Owner: CFO · v1 (2026-10-25) · Pairs with `BUDGET.md`
The rule (Charter): prefer free tiers; this tracks where each one bites so we cut scope or pay *deliberately*, never by surprise. Figures marked **[CONFIRM]** need the real plan/bill from Founder/CTO (same list as `BUDGET.md` §6).

| # | Service | Free-tier limit | Bites at (usage) | What happens | First move when it bites |
|---|---|---|---|---|---|
| 1 | **LLM — OpenRouter** (Haiku scoring + CV/CL panel) | pay-as-you-go, no free tier; bounded only by account balance | Scoring fails silently when balance is exhausted — the app warns "incomplete, usually exhausted AI API balance". Burn scales with scans×60 jobs + panel CV/CL. | Partial/empty results; user-visible quality drop. | Keep a float on the OpenRouter account; **alert at low balance**. Cut `CORPUS_TOPK` 60→40 and/or panel→single-model (§BUDGET kill rule). [CONFIRM real $/scan] |
| 2 | **Railway** (app + worker) | trial/hobby credit then metered | When monthly compute exceeds the plan credit | Overage billed per-usage; can exceed infra cap | Downsize dynos; move background scans to off-peak. [CONFIRM current bill] |
| 3 | **Postgres** (Railway or managed) | storage + connection caps on free/hobby | Corpus growth: full-JD rows (desc up to 4k chars) + embeddings per job accumulate; nightly ingest adds thousands/day | Storage cap → writes fail; connection cap → scan errors | Prune corpus: `CORPUS_FRESH_DAYS`=30 already reaps stale rows; tighten if storage nears cap. [CONFIRM plan] |
| 4 | **Resend** (email: welcome, digest, day-14, nudges) | **3,000/mo, 100/day** (free) | ~100 emails/day = ~30 active users getting a daily digest, or any send-burst | Sends 429/drop past the daily cap → users miss digests/gate emails | Batch/throttle digest; move to paid Resend tier (model a ledger row) when daily sends approach 100. |
| 5 | **Job-source APIs — JSearch/RapidAPI** | free RapidAPI tier = few hundred calls/mo | Live-fetch fallback (corpus cold/thin) + corpus ingest querying many terms | 429 → thin corpus → empty searches | Lean on the shared corpus (most scans read it, no live fetch); budget a paid JSearch tier only if corpus can't cover. [CONFIRM quota] |
| 6 | **Embeddings provider** | depends on provider | Every new corpus job + every scan's profile embed | Cost/rate cap → embeddings off → scan falls back to live fetch (slower, hits #5) | [CONFIRM provider+rate]; keep embeddings on — they're what makes scans cheap (corpus read vs live fetch). |
| 7 | **Scraping/enrichment (ATS, link-check)** | HTTP-only, **no API $** — cost is politeness caps | `ENRICH_NIGHTLY_LIMIT`=6000, `CORPUS_RESOLVE_LIMIT`=500, `GEO_BACKFILL`=6000, `ATS_CORRECT`=4000/run | Host IP-blocks if fetched too fast (hurts link-checking too) | These are self-imposed, not billed — raise only if blocks don't appear; `ENRICH_ENABLED` is the kill switch. |

## Credit-economy "cliffs" (internal, not vendor — but they drive #1 spend)
- **Weekly earn cap = 30 cr/user** → a maxing user earns ~15 free scans/week ≈ **~$2/week compute per heavy earner**. At scale this is the free-tier burn in `BUDGET.md` §5. Watch earners × redemption rate.
- **Signup grant = 10 cr** one-time per account → abuse (fake signups) directly burns compute. Mitigated by the referral anti-abuse heuristics (GTM §5); CTO owns, CFO watches the cost signal.
- **First scan free** → every signup can cost one free scan (~$0.13) even without activating. Watch signup→activation rate: low activation = wasted free scans.

## Monitoring (what to put on the dashboard — R1-05, CTO)
1. OpenRouter balance + 7-day LLM burn (the only hard money cliff).
2. Daily email count vs 100 (Resend).
3. Scans/day × avg jobs-scored → projected monthly LLM $.
4. Credits issued vs redeemed (free-tier burn leading indicator).
5. Postgres storage % of plan.

---

Skills used: cost-guardian:cost-estimate (per-scan compute to size the LLM cliff).
Skills considered but not used: pricing (covered in BUDGET.md — not re-run here), statistical-analysis (no dataset; thresholds are config-derived, not inferred).
