# Step-1 Share Artefacts — Build Spec

Owner: CPO · v1 (2026-10-25) · For the CTO to implement next cycle (BACKLOG R1-01/02/03).
Spec only — no code shipped this cycle. Stack: FastAPI + Jinja + HTMX, Postgres, Railway.

This spec is grounded in the live product, not hypothetical. Where it names a column,
helper or route, that thing exists today unless marked **NEW**.

---

## 0. What already exists (reuse, do not rebuild)

| Thing | Where | Use for |
|---|---|---|
| Two fit scores per result (`fit_role`, `fit_candidate`, 0-100) | `models.JobResult` | the card's two scores |
| Two-way verdict logic (Apply now / Worth a stretch / Watch out) | `partials/job_card.html` §0 | the card's headline verdict |
| `why_good` / `why_bad` text + `as_bullets()` helper | `JobResult`, template | fits / watch-out lines |
| Funnel stage counts per scan: `raw_count → located_count → ranked_count → scored_count` | `models.Search` | "my market read" stage counts |
| Referral code + invite URL | `services/referral.py` (`ensure_code`, `invite_url` → `/signup?ref={code}`) | the referral embed on every artefact |
| Referral rewards (friend 5cr on signup, inviter 15cr on friend's first scan) | `services/referral.py`, config `REFERRAL_*` | the /invite reward copy |
| Copy-to-clipboard JS (`[data-copy]` button) | `static/app.js:170` | one-click copy of link / message |
| Public-page SEO + OG meta context | `seo.public_seo()`, `base.html` OG block | per-page OG tags |
| Product events (allowlisted, PII-free, anon-safe) | `services/events.py`, `models.ProductEvent` | instrumentation |

**OG today is static:** `base.html` emits one `og:image` = `config.og_image_path`
(`/static/og-default.png`) for every page. There is **no** per-page/dynamic image
renderer anywhere. `/compare/linkedin-jobs` is a plain `_public_page()` — meta tags only,
default image. So the dynamic-PNG mechanism below is genuinely new; see §4.

---

## 1. Match card — `GET /m/{token}`

Public, no-auth. The shareable proof of one scored match.

### 1.1 Identifier (IMPORTANT — do not use `JobResult.short_id`)
`JobResult.short_id` is the first 8 chars of a hash of *company+title*
(`jobhunter/models.py:short_id`). It is **not unique per user** — the same posting
scored for two users produces the **same** `short_id` on two different rows — and it is
**deterministic/guessable**. Keying `/m/` on it would be ambiguous (whose card?) and an
enumeration leak.

**NEW:** add `JobResult.share_token: str | None` (unique, indexed, nullable). Mint
`secrets.token_urlsafe(9)` on the **first** "Share" click for that card (lazy — unshared
cards stay private, no public surface exists until the owner shares). `/m/{token}`
resolves that one row. The route path keeps the `{short_id}`-style shape the backlog
names; the value is this random token.

### 1.2 Fields / layout (render the existing card, stripped for public view)
Reuse the visual language of `job_card.html` so a shared card looks like the product:
- **Verdict** (Apply now / Worth a stretch / Watch out) + overall `score`/100.
- **Role title** (`JobResult.title`). **Employer company** (`JobResult.company`) —
  shown **only if** the sharer leaves "show employer" on (default **on**; a toggle lets
  them hide it for a stealth search). Location optional, same toggle.
- **Two fit bars**: "Fits what you want" (`fit_role`) · "You fit their requirements"
  (`fit_candidate`) — the existing `.fitbars` markup.
- **Fits / Watch out**: `as_bullets(why_good,3)` / `as_bullets(why_bad,2)`.
- **Never** the user's name unless chosen: **NEW** `JobResult`-owner opt-in — a
  "Show my first name" toggle on the share dialog, default **off**. When off, the card
  says "A JBHNTR match" / "Someone's shortlist"; when on, "{first_name}'s match".
  First name comes from the profile, never the email.
- **Must NOT expose**: `apply_url`, full `description`/JD, `company_blurb`, email, any CV
  text. Public card shows the verdict + reasons only — the honest-matching showcase, not
  the lead.
- **CTA** (cro: one primary, value copy, message-match): "Scan your first job match free"
  → `/signup?ref={owner_referral_code}` via `referral.invite_url()`. Secondary line:
  "See fit both ways — what you want and what they need. No card."

### 1.3 Share entry points (referrals: trigger at the aha moment, one click)
Add a **"Share"** control to:
- every **match card** on `/matches` (`job_card.html`, actions group),
- every **tracker card** in My Jobs (`/applications`).

Click → HTMX `POST /job/{id}/share` → mints `share_token` if absent, returns a small
share sheet (native `navigator.share` on mobile; copy-link + the per-channel messages of
§3.3 scoped to this card on desktop). Reuse the `[data-copy]` pattern.

### 1.4 Acceptance criteria
- Visiting `/m/{token}` with a valid token renders the card with both fit scores, verdict,
  fits/watch-out, role title, and company iff the employer toggle is on.
- No user name appears unless the name toggle is on; no `apply_url`/JD/email ever appears.
- An unknown/retired token → 404 (not a 500, not another user's card).
- The CTA links to `/signup?ref={code}` with the sharer's real code.
- `og:image` for the page is the card PNG (§4); `og:title` = the verdict + role.
- Sharing the same card twice reuses the same token (idempotent).
- Page is `noindex,nofollow` (per-user, thin) but OG unfurls on X/LinkedIn/WhatsApp.

---

## 2. "My market read" — `GET /r/{token}`

Public, no-auth. The repeatable "1,840 roles, 14 worth it" sentence — the artefact
auto-apply tools cannot make.

### 2.1 Identifier
**NEW:** add `Search.share_token: str | None` (unique, indexed, nullable), minted on first
"Share this read" click on a completed scan. Same rationale as §1.1 (Search has no public
id today, and the integer `Search.id` is enumerable).

### 2.2 Stage counts — available **today**, no engine change
Map directly from `models.Search`:
- `raw_count` → "roles scanned"
- `located_count` → "in your locations"
- `ranked_count` → "shortlisted to score in detail"
- `scored_count` → "worth a decision"

Render as a four-step funnel (big numbers + labels). Headline:
"{raw_count} roles scanned → {scored_count} worth your time."

### 2.3 Rejection-reason histogram — **does the triage model emit a reason? No.**
Checked the full pipeline (`services/search_service._run_search`,
`jobhunter/matcher.Matcher`): rejected postings are **counted, not reasoned**. Jobs are
dropped at prefilter/location, `cap_per_company`, `triage`, the post-score location gate,
and the tier≤3/4 cut — none persists a per-job reason, and rejected jobs are **not stored
at all** (only the ≤60 shown `JobResult` rows are). The only reason text in the DB is
`why_bad`, and that exists **only on shown matches**, not on the rejected majority.

So the histogram splits into two honest phases:
- **v1 (ship now, zero engine change):** the §2.2 **stage funnel** IS the market read.
  It already tells the true story ("most roles failed your location/seniority bar"). Build
  the artefact on this.
- **v2 (needs engine work — flag as R1-04-adjacent, see §5):** a true *reason* histogram
  ("wrong location 60%, under-levelled 20%, wrong function 15%…") needs the scorer to emit
  a small **reason enum** per rejected job and the pipeline to persist an aggregate. Spec:
  **NEW** `models.ScanRejectionStat(search_id, reason, count)` (or a JSON `reason_counts`
  column on `Search`), populated in `_run_search` from a new `match.reject_reason` field
  (controlled vocab: `location`, `seniority`, `function`, `comp`, `remote`, `thin_jd`,
  `other`). Until that lands, render the stage funnel and omit the reason bars — do not
  fake buckets.

### 2.4 "Share anonymised" toggle
Owner toggle, default **anonymised ON**. Anonymised = no first name, no employer names,
only aggregate counts + the user's target role/function label. Off = may include the
derived role title. Never the CV text or specific employer list regardless.

### 2.5 Fields / layout
- Headline sentence (§2.2) + the four-step funnel.
- One line of context: target role(s) + locations (from profile, respecting the toggle).
- v2: the reason bars under the funnel.
- **CTA**: "Get your own market read — first scan free" → `/signup?ref={code}`.

### 2.6 Acceptance criteria
- `/r/{token}` shows the four real stage counts from that `Search`.
- Anonymised toggle ON by default; no name/employer leaks when on.
- Unknown token → 404; a scan still running or failed → friendly "not ready" (not the funnel).
- CTA carries the sharer's ref code; OG image is the read PNG (§4); page `noindex`.
- v1 ships without the reason histogram; the histogram is gated on the §5 engine event.

---

## 3. `/invite` page — `GET /invite`

Authenticated. Turns an activated user into a referrer. (Reuses the code/link already
shown on `/credits`; this is the dedicated, shareable surface.)

### 3.1 Fields / layout
- **Code** (big, monospace) + **invite link** (`referral.invite_url(code)`), each with a
  one-click copy button (`[data-copy]`).
- **Reward framing** (referrals: double-sided, lead with the friend's benefit then yours):
  "Your friend gets their first scan free + {REFERRAL_FRIEND_CREDITS} credits. You get
  {REFERRAL_CREDITS} credits when they run their first scan." (Pull numbers from config —
  never hard-code; today 5 / 15.)
- **Live counter** (§3.2).
- **Pre-written per-channel messages** (§3.3).

### 3.2 Live counter — data source
Query by `User.referred_by_user_id == me.id`:
- **Invited & signed up** = count of such users.
- **Activated** = those with a `scan_completed` event (or, cheaper, a `referral_activated`
  credit-ledger row keyed `referral:{friend_id}`) — this is what pays out.
- **Credits earned from referrals** = SUM of `CreditLedger.delta WHERE reason='referral_activated'`.
Show "N signed up · M activated · {credits} credits earned". "Live" = recomputed on each
page load (no socket needed — ponytail: a DB count per load is fine at this scale).

### 3.3 Pre-written messages (one per channel, link pre-embedded)
Plain-text templates with `{invite_url}` filled server-side, each with a copy button and,
where it exists, a share-intent link:
- **LinkedIn / X / Bluesky**: "I've been testing JBHNTR — it scans every live role and
  tells you the ~15 worth your time, with the reasons for and against each. First scan's
  free: {invite_url}"
- **WhatsApp / iMessage**: shorter, 1 line + link (WhatsApp `https://wa.me/?text=`).
- **Email**: subject + 3-line body (`mailto:` with subject+body).
- **Reddit**: comment-safe phrasing (disclosed, answer-first) per GTM §4 posture.
Keep copy honest/plural-voice per CHARTER (no "I built"; "a tool I'm testing" is fine on a
personal share). GC clears external claim copy before launch — **REQUEST** (see §6).

### 3.4 Acceptance criteria
- `/invite` shows the user's real code + link; copy buttons work; numbers come from config.
- Live counter matches the DB (signed-up, activated, credits earned).
- Each channel message contains the correct `invite_url`; share-intent links open the right
  composer; mobile uses `navigator.share` where available.
- Landing: `/signup?ref={code}` attributes the signup (`attach_and_reward_friend` already
  wires this) and the referred user's first scan pays the inviter
  (`reward_inviter_if_activated`, already wired).

---

## 4. OG / PNG rendering (shared by §1 and §2)

Requirement: social scrapers (X, LinkedIn, Facebook, WhatsApp) need a **raster** image at
`og:image` (1200×630). They do **not** reliably render SVG. Current `og:image` is one
static PNG for all pages.

**Climbing the ladder with what's installed:**
- Pillow — not installed (new dep + hand-laid text; avoid).
- WeasyPrint — installed, but dropped PNG output after v53 (we're on ≥61) → PDF only, no good.
- Playwright — **declared** (`requirements-web.txt`) but used only to drive Bright Data's
  **remote** browser over CDP; the comment notes **no local Chromium is downloaded**.

**Recommended (primary):** reuse Playwright with a **local headless Chromium** to screenshot
the `/m/{token}` and `/r/{token}` HTML themselves at 1200×630. This reuses an
already-declared dependency **and** the card HTML we're already building — zero duplicate
layout, correct brand fonts/colours for free. Cost: add `playwright install chromium` to
the Railway build (nixpacks), and render **lazily on first OG fetch, then cache** the PNG
(to `/static/og/{token}.png` on disk, or a `bytes` column) so Chromium runs once per
artefact, not per view. A dedicated minimal `/m/{token}/card` and `/r/{token}/card` render
target (fixed 1200×630, no nav/footer) is the screenshot source.

**Ceiling / `ponytail:` note for the CTO:** headless Chromium is ~150MB + memory on
Railway. If build size or web-process memory is a problem, the lower-footprint alternative
is a hand-authored Jinja **SVG** card template rasterised by `cairosvg` (new, lighter than
Chromium, needs the `cairo` system lib) → PNG. Pick screenshot for fidelity+reuse; pick
cairosvg if the box is tight. This is a CTO implementation call; either satisfies the
acceptance criteria.

**Wiring:** `base.html` already parameterises `og:image` via context — pass a per-page
`og_image` (absolute URL to the cached PNG) through `public_seo()` instead of the default.
**NEW:** `public_seo()` gains an optional `og_image` arg; when absent it falls back to
`config.og_image_path` (today's behaviour — no regression).

### Acceptance criteria
- `GET /m/{token}` and `/r/{token}` expose a 1200×630 PNG at `og:image`; pasting the link
  into X/LinkedIn/WhatsApp unfurls the card image + verdict title.
- The PNG renders once and is cached; a second fetch does not re-run the renderer.
- Pages with no custom image (all existing pages) keep the static default — no regression.

---

## 5. Biggest activation-funnel gap

**Activation = signup + profile ≥70% + ≥1 search** (CHARTER). The gate is enforced in code:
`start_search` raises `QuotaError` unless `completeness(db,user).can_search`, so an
incomplete profile literally cannot produce the first scan.

**The single biggest likely drop-off: signup → profile ≥70% (the profile/targets step),
not profile → first search.** Rationale: the free first scan is one click *once the gate
opens* and is strongly incentivised (free, no card), so profile-complete users almost all
scan. The profile step is the multi-field wall — CV upload *plus* objective, seniority,
locations, work modes, etc. — and it is the only thing standing between signup and
activation. The gate is also **invisible until you hit it**: a user discovers they can't
scan only when they try, which is the classic silent-drop pattern.

**Evidence I would confirm it with (ProductEvent):** per-user funnel of
`signup_completed → cv_uploaded → onboarding_completed → scan_started → scan_completed`
(distinct `user_id`). The largest step-down localises the gap. My prediction: the biggest
fall is **`cv_uploaded` → `onboarding_completed`** (or signup → cv_uploaded), i.e. inside
the profile step.

**But the instrumentation can't yet localise *which field* stalls people** — that's the
tracking gap (§5.1). `onboarding_completed` is a single once-event; there is no per-step
event and no event for hitting the completeness gate.

**The one change I'd test first (single KPI: first-scan rate = `scan_started`/`signup_completed`):**
Make the 70% bar **visible and rewarding** during onboarding — a live completeness meter
showing the exact remaining required fields and a persistent "Run my free scan — unlocks at
70%" CTA that activates the instant `can_search` flips true. Today the gate is discovered
only on a failed scan attempt; turning the invisible gate into a visible, closable goal with
the free-scan reward attached at each step is the highest-leverage, lowest-risk lever.
(cro: one primary CTA, value copy, remove the hidden-friction point.) A/B where traffic
allows; otherwise ship as the best-practice default and watch first-scan rate.

### 5.1 Tracking gaps → **R1-04 (CTO measurement plumbing)**

Events **missing** from `events.EVENT_NAMES` that this plan needs. All PII-free, fit the
existing `ProductEvent` model (anon `user_id=None` supported for public views):

**Activation localisation**
1. `onboarding_step_completed` — prop `step_name` (which profile step) — localise the §5 drop-off.
2. `profile_threshold_reached` — fired when `can_search` first flips true (the ≥70% sub-gate).
3. `scan_blocked_incomplete` — fired where `start_search` raises `QuotaError` (today a silent bounce).

**Share / referral loop (K-factor numerator — none exist today)**
4. `match_card_shared` / `market_read_shared` — owner clicks Share (prop `source` = where).
5. `shared_artifact_viewed` — a logged-out visitor opens `/m/` or `/r/` (anon event; prop `kind`=card|read).
6. `invite_page_viewed`.
7. `invite_link_copied` / `invite_message_copied` — prop `channel`.
8. `referred_signup` — a signup carrying `?ref=` (prop `source`=referral).
9. `referral_activated` as a **product event** — today it's only a credit-ledger row; mirror
   it into ProductEvent so the funnel/K-factor dashboard can read one table.

**Allowlist change (blocks 1,4,7 above):** `events.ALLOWED_PROPS` is
`{kind,tier,rating,source,count,n}` — **add `step_name` and `channel`**, or those props are
silently dropped by `_clean()`.

**Attribution:** pass `source` on `signup_completed` (organic | referral | channel) — the
prop is already allowed; it's just never set. Pair with the `/go/{channel}` + UTM plumbing
the PRD lists.

---

## 6. Requests for the Founder

**REQUEST (R-xxx):** GC to clear the external-claim copy in the pre-written share/invite
messages (§3.3) and the public card/read CTA copy before these artefacts go live
(CHARTER guardrail 5 — GC owns the compliance line; "71%/better" style stats must be real
per guardrail 8). No action needed until §1–3 are built; file alongside the build PR.

No connector/MCP authorisation is required for this spec — all data sources are in-product.

---

## 7. Model changes summary (for the CTO)

All additive, nullable — no backfill, no migration risk:
- `JobResult.share_token: str|None` (unique, indexed) — §1.1
- `JobResult` owner opt-ins for the card: show-name (default off), show-employer (default
  on). Store as two bools on `JobResult` or a small JSON `share_opts`; ponytail: two bools.
- `Search.share_token: str|None` (unique, indexed) — §2.1
- `Search` anonymised-share flag (default true) — §2.4
- **v2 only:** `ScanRejectionStat` (or `Search.reason_counts` JSON) + `match.reject_reason`
  from the scorer — §2.3 / §5.
- `seo.public_seo(og_image=...)` optional arg — §4
- `events.EVENT_NAMES` += the 9 events; `events.ALLOWED_PROPS` += `step_name`, `channel` — §5.1

---
Skills used: referrals (loop design, aha-moment trigger, one-click + pre-written messages,
double-sided reward framing), cro (single value-CTA, message-match on the share→signup
handoff, the visible-gate first test), analytics (object-action event naming, the missing-
event audit and allowlist gap, source attribution), task-observer (session-start).
Skills considered but not used: onboarding / signup (the §5 fix touches onboarding, but the
build is next cycle — applied their "make the gate visible / reduce required fields"
principle at spec level rather than loading the full build checklists); frontend-ui-
engineering / web-design-guidelines / apple-design (exact card markup/CSS is the CTO's
build step — this spec reuses the existing `job_card.html` visual language instead of
re-specifying pixels); ab-testing (named the single KPI + A/B-where-traffic-allows, full
test design belongs with the experiment when it's set up); paywalls / churn-prevention
(not relevant to Step-1 share artefacts).
