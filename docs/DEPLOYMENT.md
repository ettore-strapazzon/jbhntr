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

Add **four cron services** in the same project. In Railway: **New → Empty
Service → connect the same repo**, then set **Settings → Cron Schedule** and
**Settings → Custom Start Command**. Each runs then exits. Give each the **same
environment variables** as the web service (Railway "shared variables" is the
easy way), so they see the same `DATABASE_URL`, keys, and `EMBEDDING_*`.

| Service | Cron (UTC) | Start command |
|---|---|---|
| `reaper` | `0 2 * * *` | `python -c "from web.app.services.reaper import run; print(run())"` |
| `discover` | `0 3 * * 1` | `python -m web.app.services.ingest --cadence discover` |
| `ingest-weekly` | `0 4 * * 1` | `python -m web.app.services.ingest --cadence weekly` |
| `ingest-daily` | `0 5 * * *` | `python -m web.app.services.ingest --cadence daily` |

Order/timing rationale: reaper prunes dead jobs first; weekly discovery grows
the company registry (accumulates ~a few companies/run toward 100/user); the
daily ingest then fetches all lanes (incl. the freshly-discovered companies) and
embeds new jobs. Metered sources (Jooble, JSearch, Findwork) only run weekly,
see INGESTION_ENGINE.md §11b.

**First run:** trigger `ingest-daily` and `discover` manually (Railway "Run
now") so the corpus fills before you test searches.

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
