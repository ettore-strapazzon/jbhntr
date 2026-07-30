# JBHNTR, Deployment (Railway + Cloudflare)

How to run the **web product** in production: a web service, a Postgres
database, and four scheduled jobs that keep the corpus fresh. Secrets live in
Railway/GitHub, never in the repo (`.env` is gitignored).

> The `.github/workflows/daily.yml` action is separate, it runs the *personal
> CLI* (`jobhunter.pipeline` → Google Sheet) for one user. The web product does
> **not** use it; it uses the Railway cron jobs below.

---

## 0. Push to GitHub (secrets already excluded)

The repo is safe to push, `.env`, `service_account.json`, `config/profile.yaml`,
`data/*`, and `config/materials/*` are gitignored (verified with
`git check-ignore`). Set the repo **root** to this `job-hunter/` folder so
`.github/workflows/` and `railway.json` are found.

```bash
git add -A
git commit -m "JBHNTR web product + ingestion engine"
git branch -M main
git remote add origin git@github.com:<you>/jbhntr.git
git push -u origin main
```

---

## 1. Railway project

1. **New Project → Deploy from GitHub repo** → pick the repo. Railway reads
   `railway.json`: builds with `requirements-web.txt`, starts the web service
   (`uvicorn web.app.main:app`), health-checks `/health`.
2. **Add a Postgres plugin** (New → Database → PostgreSQL). Railway injects
   `DATABASE_URL`; the app uses it automatically (SQLite only locally).
3. **Set environment variables** on the service (Variables tab), see the
   checklist in §4. These replace your local `.env`.

The web service is now live at a `*.up.railway.app` URL.

---

## 2. Scheduled jobs (the ingestion engine)

Add **one** cron service. In Railway: **New → GitHub Repo → same repo**, then in
its **Settings** set:

- **Custom Start Command:** `python -m web.app.services.cron`
- **Cron Schedule:** `0 3 * * *`  (03:00 UTC nightly)

Give it the **same environment variables** as the web service (incl. a
`DATABASE_URL` reference to the Postgres service). `web/app/services/cron.py`
does the rest: every night it reaps dead jobs and runs the daily ingest; on
Mondays it also refreshes discovery and pulls the weekly metered sources
(Jooble/JSearch/Findwork). One service, one schedule, one set of vars.

**First run:** hit **Run now** on the cron service once so the corpus fills
before you test searches. (On a non-Monday this skips the weekly sources; that's
fine — the daily lanes already fill most of the corpus.)

**Embeddings:** with `EMBEDDING_BASE_URL=local`, the ingest service downloads
the fastembed model (~150 MB) on first run and embeds on-device, no key, no
cost. (Set a hosted `EMBEDDING_BASE_URL`+`EMBEDDING_API_KEY` instead if you'd
rather not embed on the box.)

---

## 3. Cloudflare (jbhntr.app)

1. Railway service → **Settings → Networking → Custom Domain** → add
   `jbhntr.app` (and/or `www`). Railway shows a `CNAME` target.
2. In Cloudflare DNS, point `jbhntr.app` at that target (CNAME, proxied). This
   replaces the placeholder Pages site.
3. TLS is automatic (Railway + Cloudflare). Keep Cloudflare's proxy on for the
   free WAF/rate-limiting in front of the app.

---

## 4. Environment variable checklist (set in Railway)

**Required**
- `LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL=https://openrouter.ai/api/v1`,
  `LLM_API_KEY=…` (or `ANTHROPIC_API_KEY` for Anthropic direct)
- `JOBHUNTER_SCORING_MODEL`, `JOBHUNTER_GENERATION_MODEL`
- `SECRET_KEY`, `FILE_ENCRYPTION_KEY` (generate fresh, do **not** reuse the
  local ones; see .env.example for the one-liners)
- `BASE_URL=https://jbhntr.app`, `DEBUG=false`
- `EMBEDDING_BASE_URL=local` (or a hosted URL + `EMBEDDING_API_KEY`)

**Sources** (each free key you have): `ADZUNA_APP_ID/KEY/COUNTRY`,
`CAREERJET_AFFID` (+`REFERER=https://jbhntr.app`), `JOOBLE_API_KEY`,
`REED_API_KEY`, `FINDWORK_API_KEY`, `WEB3CAREER_API_KEY`, `USAJOBS_KEY/EMAIL`.

**Plan limits**: `FREE_SEARCHES`, `PREMIUM_SEARCHES_PER_DAY`, `FREE_SCORING_MODEL`,
`PREMIUM_SCORING_MODEL`.

**Optional**: `GOOGLE_CLIENT_ID/SECRET` (Google login), `PLAUSIBLE_DOMAIN`,
`SUPPORT_EMAIL`.

`DATABASE_URL` is injected by the Postgres plugin, don't set it by hand.

---

## 5. After deploy, sanity checks

- `GET https://jbhntr.app/health` → ok.
- Sign up, complete the profile, run a search, first search may fall back to a
  live fetch until the corpus has embedded jobs; after `ingest-daily` runs it
  switches to fast corpus mode.
- Watch the cron logs: `ingest-daily` should report `fetched/added/embedded`,
  `reaper` its prune counts, `discover` companies added.
- Rotate any key that was ever pasted into chat or a committed file before going
  public.

## Troubleshooting: the cron ("nightly") deploy crashes

The cron service runs `python -m web.app.services.cron` once per schedule and
exits. A "Deploy Crashed" email means that run exited non-zero. Check the cron
service's deploy logs:

- **A Python traceback** — a code bug in one stage. As of the resilience change,
  each stage (reaper, ingest, digests, page-view prune) is isolated, so one
  stage's exception is logged and the run still exits 0. If you still see a
  traceback, it is at import/startup, not inside a stage.
- **Exit code 137 / "killed" / no traceback** — an **out-of-memory kill**. The
  heaviest thing the cron does is embed newly-ingested jobs with the local
  `fastembed` model (a ~150MB ONNX model). The web service survives because it
  only embeds a few query texts per search; the cron embeds the whole new corpus.
  `_embed_local` now processes in 32-text chunks to bound the working set. If it
  still OOMs:
  1. **Raise the cron service's memory** in Railway (Settings → resource limits).
  2. Or **switch embeddings to a hosted endpoint**: set `EMBEDDING_BASE_URL` to an
     OpenAI-compatible `/embeddings` API and `EMBEDDING_API_KEY`. This removes the
     local model from the cron entirely (matching quality is unchanged).
  3. If `EMBEDDING_BASE_URL` is unset/empty, embedding is a no-op — then the crash
     is not embedding, look for a traceback instead.
