# JBHNTR, Step-by-step implementation guide

From the code as it stands to a live private beta. Follow in order; each step is
verifiable before you move on.

---

## Step 1, Run it locally (15 min)

```powershell
cd job-hunter
.\.venv\Scripts\Activate.ps1
pip install -r requirements-web.txt
```

Generate the two secrets the web app needs and add them to `.env`:

```powershell
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print('FILE_ENCRYPTION_KEY=' + Fernet.generate_key().decode())"
```

Add to `.env`:

```
SECRET_KEY=<paste>
FILE_ENCRYPTION_KEY=<paste>
DEBUG=true
BASE_URL=http://localhost:8000
```

Start it:

```powershell
uvicorn web.app.main:app --reload
```

**Verify:** open <http://localhost:8000> → sign up → walk the 9 onboarding steps →
land on `/search`. Until the required steps are done the search button stays
disabled and the page says *"Finalise your profile first"*.

> Locally it uses SQLite (`data/web.sqlite`). No database to install.

---

## Step 2, Buy the domain (10 min)

1. Go to **Cloudflare Registrar** (`dash.cloudflare.com` → Domain Registration).
   It sells at wholesale cost with free WHOIS privacy.
2. Register **`jbhntr.app`** (~$14/yr). `.com` is taken; `.app` also forces HTTPS
   at the browser level, which is a genuine security win.
3. Leave DNS on Cloudflare, you'll point it at Railway in step 4.

---

## Step 3, Deploy to Railway (30 min)

1. Push this repo to GitHub (**private**).
2. In Railway: **New Project → Deploy from GitHub repo**.
3. Add a **PostgreSQL** database to the project. Railway injects `DATABASE_URL`
   automatically, the app rewrites the `postgres://` prefix itself.
4. Under **Variables**, set:

   | Variable | Value |
   |---|---|
   | `SECRET_KEY` | a *new* one, not your local one |
   | `FILE_ENCRYPTION_KEY` | a *new* Fernet key |
   | `DEBUG` | `false` |
   | `BASE_URL` | `https://jbhntr.app` |
   | `LLM_PROVIDER` | `openai_compatible` |
   | `LLM_BASE_URL` | `https://openrouter.ai/api/v1` |
   | `LLM_API_KEY` | your OpenRouter key |
   | `JOBHUNTER_SCORING_MODEL` | `anthropic/claude-haiku-4.5` |
   | `JOBHUNTER_GENERATION_MODEL` | `anthropic/claude-sonnet-5` |
   | `FREE_SCORING_MODEL` | `google/gemini-2.5-flash-lite` |
   | `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | your Adzuna keys |
   | `SUPPORT_EMAIL` | your support address |

5. Deploy. Check the logs for `CONFIG:` warnings, with `DEBUG=false` the app
   **refuses to boot** on weak secrets, which is deliberate.

**Verify:** `https://<your-app>.up.railway.app/health` returns `{"status":"ok"}`.

---

## Step 4, Point the domain at Railway (15 min)

1. Railway → your service → **Settings → Networking → Custom Domain** → add
   `jbhntr.app`. It gives you a CNAME target.
2. In Cloudflare DNS add a **CNAME** for `@` (or `www`) to that target,
   **proxy ON** (orange cloud).
3. Cloudflare **SSL/TLS → Overview → Full (strict)**.

**Verify:** `https://jbhntr.app` loads with a valid certificate.

---

## Step 5, Google sign-in (20 min, optional)

1. Google Cloud Console → **APIs & Services → Credentials → Create OAuth client
   ID → Web application**.
2. Authorised redirect URI: `https://jbhntr.app/auth/google/callback`.
3. Put `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` into Railway variables.
4. Complete the OAuth consent screen (you'll need the Privacy Policy URL,
   `https://jbhntr.app/privacy` already exists).

The "Continue with Google" button appears automatically once the ID is set.

---

## Step 6, Analytics (10 min)

1. Create a site on **Plausible** (`jbhntr.app`).
2. Set `PLAUSIBLE_DOMAIN=jbhntr.app` in Railway.

Plausible is cookieless, so it needs no consent banner. The app *also* records
page views in its own `page_views` table (no IP, no user id) as a free fallback.

---

## Step 7, Pre-launch security pass (1 hour)

Work through **docs/SECURITY_AND_GDPR.md → Pre-launch checklist**. The
non-negotiables:

- [ ] `DEBUG=false` in production
- [ ] Different secrets in production than locally
- [ ] Railway Postgres **backups enabled, and a restore actually tested**
- [ ] Account deletion verified against the database (the row is really gone)
- [ ] Data export returns everything
- [ ] No secrets committed: `git log -p | Select-String "sk-or-|sk-ant-"`
- [ ] Cloudflare rate limiting on `/login` and `/signup`

---

## Step 8, Legal review (before charging anyone)

`/terms`, `/privacy` and `/cookies` are **templates**, and they say so. Before
you take money, have a lawyer check them, in particular:

- the sub-processor list (your CV text goes to a US AI provider, this must be
  disclosed and covered by SCCs),
- the liability cap (an outright exclusion is void for EU consumers),
- consumer withdrawal rights for digital services.

---

## Step 9, Private beta

1. Invite 5–10 people you can talk to directly.
2. Watch: how many finish onboarding? do they run a search? what's the average
   tier of results?
3. Watch cost: `searches_used` across users × ~$0.30–1.00 per search. If free
   users cost more than expected, lower `FREE_SEARCHES` or keep them on the
   cheap model.

**Useful queries:**

```sql
-- funnel
SELECT count(*) FILTER (WHERE p.objective <> '') AS onboarded,
       count(*)                                   AS signups
FROM users u LEFT JOIN profiles p ON p.user_id = u.id;

-- cost driver
SELECT sum(searches_used) FROM users;

-- match quality
SELECT tier, count(*) FROM job_results GROUP BY tier ORDER BY tier;
```

---

## Step 10, What comes next (deliberately not built yet)

| Feature | Trigger to build it |
|---|---|
| **Stripe checkout** | When people ask to pay. ~1 day. Flip `PAYMENTS_ENABLED=true`. |
| **Redis + RQ worker** | When searches block the web process (threads are fine to ~20 concurrent users). |
| **Licensed job source** (SerpApi/Bright Data) | To replace LinkedIn coverage properly. Set `SERPAPI_KEY`; the source layer already supports it. |
| **Email digests** | When users want results without logging in. |
| **Alembic migrations** | Before the first schema change with real users. `create_all` is fine until then. |

---

## Known limitations of this beta, be honest with testers

1. **Searches run in a background thread**, not a separate worker. Fine for a
   small beta; move to Redis/RQ before real traffic.
2. **`create_all` instead of migrations**, schema changes need care once users
   have data.
3. **No LinkedIn** for web users, by design (legal). Coverage still comes from
   aggregators, niche boards and company career pages.
4. **Generated documents are plain text**, not formatted PDF/DOCX.
5. **Payments are a placeholder**, premium can only be granted manually
   (set `plan='premium'` on the user row).
