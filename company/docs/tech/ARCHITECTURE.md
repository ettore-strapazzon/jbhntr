# ARCHITECTURE — JBHNTR (current state)

Owner: CTO · Updated 2026-10-25 · Living reference, not an essay. Update in place when a component, host, or cost changes.

Live at **jbhntr.app** (Railway, deploys on push to `main`). Stack: FastAPI + Jinja + HTMX, Postgres, Anthropic LLM, on-device embeddings, Resend email. One monorepo today (`web/` shell + `jobhunter/` engine); the open-core split is planned in [REPO_SPLIT_EXECUTION_PLAN.md](REPO_SPLIT_EXECUTION_PLAN.md).

## Component map

| Component | What it does | Code location | Host | Cost |
|---|---|---|---|---|
| **Web app** | FastAPI + Jinja + HTMX; all routes, auth, sessions, CSP, server-side render | `web/app/main.py`, `web/app/routes/` | Railway `web` service (uvicorn, `Procfile`/`railway.json`) | Railway usage (shared budget) |
| **Product DB** | Users, profiles, searches, matches, jobs, credits, events, corpus | `web/app/models.py`, `web/app/db.py` | Railway Postgres plugin | Railway usage |
| **In-app scan** | User-triggered market scan; runs in a **daemon thread** inside the web process; writes a `Search` row + matches | `web/app/services/search_service.py`, `matches_service.py`, `job_state.py` | Railway `web` (same process) | LLM + metered-source calls per scan |
| **Scan recovery** | On boot, fails + refunds any `Search` stuck `running` from a killed process | `main.py` lifespan → `search_service.fail_stuck_searches` | Railway `web` | — |
| **Ingestion / cron** | Nightly: prune dead jobs + daily ingest; weekly (Mon UTC): discovery refresh + metered sources | `web/app/services/cron.py` → `ingest.py`, `reaper.py` | Railway `cron` service (`railway.cron.json`, `python -m web.app.services.cron`) | LLM + metered-source calls |
| **Reaper** | Marks postings dead/stale, calibrates aggregators, keeps the corpus fresh | `web/app/services/reaper.py`, `aggregator_calibrate.py` | Railway `cron` | — |
| **Corpus** | Shared pool of ingested postings (tags, embeddings, geo) scans read from | `web/app/services/corpus_service.py`, `enrich_service.py` | Railway Postgres | storage |
| **Matching engine** | Two-way fit scoring + reasons (cheap model, cached system prompt), triage, tags, dedup, criteria | `jobhunter/matcher.py`, `criteria.py`, `tags.py`, `dedup.py`, `candidate.py` | in-process (web + cron) | Anthropic `scoring` tier |
| **Sources / connectors** | 25+ endpoints: Adzuna, Careerjet/Jooble/JSearch/Findwork, Arbeitnow/RemoteOK/Remotive, Exa, ATS (Greenhouse/Lever/Ashby…), careers-page scrape | `jobhunter/sources/` | in-process | metered APIs + Bright Data |
| **Discovery** | "Find more companies like these"; verifies they're hiring | `jobhunter/discover.py`, `seeds.py` | Railway `cron` | LLM + fetches |
| **LLM** | One interface, two backends (Anthropic default / OpenAI-compatible). `scoring` = cheap/high-volume, `generation` = stronger | `jobhunter/llm.py` | Anthropic API | per-token; provider is a `.env` switch |
| **Embeddings** | Semantic ranking; on-device ONNX (`fastembed`), no key/quota | `jobhunter/embeddings.py` | in-process (downloads ~150MB model once) | **free** |
| **Doc generation + export** | Tailored CV + cover letter (stronger model), HTML/CSS → PDF (WeasyPrint, fpdf2 fallback) + DOCX | `jobhunter/generator.py`, `web/app/services/cv_*.py`, `export.py` | in-process; WeasyPrint needs system libs (`nixpacks.toml`) | Anthropic `generation` tier |
| **Credits** | First scan free; priced scans + CV/CL drafts; idempotent grants; referral bonuses | `web/app/services/credits.py`, `referral.py` | Railway Postgres | — |
| **Email** | Transactional (welcome, reset, digest) via Resend HTTPS API | `web/app/services/email.py`, `digest.py` | Resend | free tier → metered |
| **Auth** | Email+password (bcrypt via passlib) + Google OAuth (Authlib); signed session cookie, `.jbhntr.app` scoped | `web/app/auth.py`, `routes/auth_routes.py` | Railway `web` | — |
| **Google integration** | Service account for Drive/Docs/Sheets (CV export, legacy sheet flow) | `jobhunter/gdrive.py`, `web/app/services/gdocs.py` | Google APIs | free tier |
| **Analytics** | Privacy-preserving `PageView` (daily-rotating one-way visitor hash, no IP/email, 24-mo retention); optional Plausible | `web/app/services/analytics.py`, `main.py` middleware | Railway Postgres (+ Plausible if set) | free / Plausible metered |
| **Measurement (R1-04)** | `ProductEvent` funnel (allowlisted names + non-identifying props, never raises) + `JobEvent` | `web/app/services/events.py`, `job_events.py`, `models.py` | Railway Postgres | — |
| **BI dashboard (R1-05)** | Operator metrics incl. the activation funnel from `ProductEvent` | `web/app/routes/admin.py` (`/admin`) | Railway `web` | — |
| **Secrets / config** | All secrets from env / `.env`; `config.validate()` **refuses to boot in prod** on weak secrets | `web/app/config.py`, `jobhunter/config.py`, `.env.example` | Railway env vars | — |
| **CDN / TLS** | Cloudflare in front of Railway; app trusts `X-Forwarded-*` (ProxyHeaders) | — | Cloudflare | free tier |

## Request / data flow (scan)

`signup → onboarding (CV upload + targets) → profile ≥70% → POST /search` → `search_service` spawns a daemon thread → derive candidate + criteria + company profile (`jobhunter.candidate`/`criteria`) → read corpus + fetch metered sources (`jobhunter.sources`) → prefilter + dedup (`jobhunter.dedup`) → score two-way fit (`jobhunter.matcher`, cheap model, cached system prompt, `PROMPT_VERSION`) → write `Search` + `Match` rows → `ProductEvent(scan_completed)` → `referral.reward_inviter_if_activated` → "my market read" + Matches UI. Score cache keyed on `PROMPT_VERSION` + job (`score_cache.py`) avoids re-scoring.

## Two data stores (note)

- **Product DB = Postgres** (web + corpus + events). Authoritative for the product.
- The CLI pipeline's dedup `seen`-store is **SQLite-backed** (`jobhunter/dedup.py`) — a legacy of the standalone engine. In the hosted product the corpus lives in Postgres; the SQLite store matters only for the `python -m jobhunter.pipeline` path.

## Security posture (standing duty)

Strict CSP (no inline handlers; one pinned sha256 for the no-flash theme script), HSTS/X-Frame/X-Content-Type/Referrer/Permissions headers on every response (`main.py` middleware). Session cookie `httpOnly`+`secure`+`sameSite=lax`, bounded `maxAge`. Passwords bcrypt. OAuth state in a separate short-lived cookie. Uploads Fernet-encrypted. Analytics stores no IP/email. `config.validate()` hard-fails prod boot on weak secrets — **the model the demo-fallback boot guard will reuse** (see split plan §c). Gaps tracked by the CTO: shared-store rate limiting on auth, referral anti-abuse heuristics (not yet built — land in the private engine post-split).

## Where R1-04 / R1-05 plug in

Measurement plumbing (R1-04) extends `events.py`'s `ProductEvent` vocabulary + `/go/{channel}` + UTM capture; it is **already partially built** (funnel events + privacy-safe PageView). The BI dashboard (R1-05) extends the existing `/admin` funnel view (read-only metrics) — **no new infra**, per the CTO mandate. `KPIS.md` stays the authoritative snapshot; `/admin` is the live view.

## External dependencies (fail-open where possible)

Anthropic (LLM) · Adzuna + metered job APIs · Bright Data remote Scraping Browser (careers scrape; only imported when `BROWSER_AUTH` set) · Exa · Resend (email) · Google (OAuth + Drive/Docs/Sheets SA) · Cloudflare · optional Plausible. WeasyPrint degrades to fpdf2 if system libs absent; analytics and events never break a request.

---
Skills used: engineering:architecture, task-observer.
