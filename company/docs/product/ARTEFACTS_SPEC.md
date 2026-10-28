# Step-1 Share Artefacts — Build Spec

Owner: CPO · v1 (2026-10-25), build plan R3-01..04 (2026-10-26), live-code re-verify
(2026-10-28). Builds: **R3-01 match card this cycle (CTO+CPO); R3-02 market read /
R3-03 /invite / R3-04 meter next cycle.** The measurement foundation (R2-01) is shipped.
Spec only — no product code in this doc. Stack: FastAPI + Jinja + HTMX, Postgres, Railway.

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
Show **"M friends activated · +{credits} credits"** as the headline number — lead with
*activated* because that is what pays out and what the loop optimises — with "N signed up"
as a quieter secondary line. "Live" = recomputed on each page load (no socket needed —
ponytail: a DB count per load is fine at this scale).

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

## 8. Build plan — R3-01..04

Added 2026-10-26 (CPO); backlog IDs synced + live-code re-verified 2026-10-28 (CPO).
Foundation **R2-01** (measurement + `share_token` columns) is **shipped — done (c2), 597
green, pushed**, so everything below rests on live code, not a pending dependency.

**Who builds what, when:**
- **This cycle:** the **Match card — R3-01** (CTO+CPO). It is where the whole shared-artefact
  machine gets built once (see §8.1).
- **Next cycle:** **Market read — R3-02**, **/invite — R3-03**, **Activation meter — R3-04**.
  R3-02/03 reuse the R3-01 machine (do not rebuild it); R3-04 is independent of it.

(Historical note: §8 first drafted these as R2-02..05 before the backlog renumbered the
*builds* to R3-01..04. R2-01 remains the shipped measurement foundation they emit into.)

Each item below names *only* the events it emits, where the `share_token` is minted, and a
self-verify checklist.

### 8.0 Foundation (R2-01) — VERIFIED live 2026-10-28, not a pending gate

Re-checked against `web/app/services/events.py` and `web/app/models.py` — all present, so
the "props drop silently in `_clean()`" risk is **closed**:
- `events.EVENT_NAMES` contains all five loop events (`match_card_shared`,
  `market_read_shared`, `shared_artifact_viewed`, `invite_page_viewed`,
  `invite_link_copied`) and the three activation events (`onboarding_step_completed`,
  `profile_threshold_reached`, `scan_blocked_incomplete`). ✓
- `events.ALLOWED_PROPS` = `{kind, tier, rating, source, count, n, step_name, channel}` —
  `step_name` and `channel` are in. ✓
- `record(db, name, user_id=None, **props)` accepts `user_id=None` → the anon
  `shared_artifact_viewed` from a logged-out visitor is supported. ✓
- `Search.share_token` and `JobResult.share_token` both exist: `TEXT`, nullable, unique
  index (migration shipped; test `test_r2_share_token_columns_exist_nullable_and_unique`
  asserts it). ✓

**No confirm step remains for R3-02/03/04 on R2-01.** The one thing to confirm is the
R3-01 *build* (next section), because R3-02/03 reuse it.

### 8.0a Dependency to confirm with the CTO's R3-01 build (the live one)

R3-02 and R3-03 do **not** depend on R2-01 only — they depend on the **reusable machine
R3-01 builds this cycle**. Confirm these three R3-01 outputs are factored for reuse before
starting R3-02/03, so the next cycle is layout-only, not infrastructure-again:
1. **The lazy-mint + public-route pattern** — `POST /job/{id}/share` mints
   `secrets.token_urlsafe(9)` into `share_token` iff null, idempotent on re-share; `/m/{token}`
   resolves one row, 404 on unknown. R3-02 copies this verbatim onto `Search` /
   `/r/{token}`. *Confirm: the mint + resolve is a small shared helper, not inlined in the
   match-card handler.*
2. **The OG-PNG renderer (§4)** — the Playwright-local-Chromium screenshot of a minimal
   `/m/{token}/card` target at 1200×630, rendered-once-then-cached, wired through
   `public_seo(og_image=...)`. R3-02 adds only a second render target
   (`/r/{token}/card`); it must not re-solve rendering/caching. *Confirm: the
   screenshot+cache is parameterised by (route, token), reusable for the read card.*
3. **The `shared_artifact_viewed` anon-view wiring** — fired on the public GET with
   `user_id=None` and a `kind` prop. R3-02 passes `kind=read` instead of `kind=card`.
   *Confirm: the public-GET event emit is reusable, keyed by `kind`.*

If R3-01 inlines any of the three into the match-card path, that is the one-line follow-up
to raise on R3-01 review — flag it there, not next cycle when R3-02 starts.

### 8.1 Build order (match card → market read → invite)

Order is deliberate, not arbitrary:
1. **Match card (R3-01) first.** It is the atomic artefact (one scored match), reuses the
   most existing markup (`job_card.html`), and is where the whole shared-artefact machine
   gets built once: the lazy `share_token` mint, the public `/m/{token}` route, and the
   **OG-PNG renderer (§4)**. Everything downstream reuses these.
2. **Market read (R3-02) second.** Reuses the exact `share_token` pattern (on `Search`
   instead of `JobResult`) and the §4 PNG renderer the card just established — so this is
   mostly a second render target + the stage-funnel layout, not new infrastructure.
3. **`/invite` (R3-03) third.** Depends on no new artefact infra; it is the *destination*
   the first two drive traffic to, so it is only worth shipping once there are shared
   artefacts carrying referral codes into the wild. Referral reward wiring already exists
   (§3).

`R3-04` (the meter) is independent of the share machine — it blocks only on R2-01's three
activation events (shipped) — so it can be built in parallel with any of the above.

### 8.2 Events + `share_token` per artefact

| Build item | Emits (R2-01 event → when, props) | `share_token` minted |
|---|---|---|
| **R3-01 Match card** | `match_card_shared` → owner clicks **Share** on a match/tracker card (`POST /job/{id}/share`); prop `source` = `matches` \| `applications`. · `shared_artifact_viewed` → logged-out visitor opens `/m/{token}` (anon, `user_id=None`); prop `kind` = `card`. | **On the first Share click** for that card, inside `POST /job/{id}/share`: if `JobResult.share_token` is null, mint `secrets.token_urlsafe(9)` and persist, then return the share sheet. Idempotent — a second Share reuses it. |
| **R3-02 Market read** | `market_read_shared` → owner clicks **Share this read** on a completed scan; prop `source` = where the button sat (`matches` \| `read`). · `shared_artifact_viewed` → logged-out visitor opens `/r/{token}`; prop `kind` = `read`. | **On the first "Share this read" click**, same lazy pattern on `Search.share_token` (reuse the R3-01 mint helper — §8.0a.1). Unshared scans stay private. |
| **R3-03 /invite** | `invite_page_viewed` → `GET /invite` renders for the signed-in user (one per load). · `invite_link_copied` → user copies the link or a per-channel message; prop `channel` = `link` \| `linkedin` \| `x` \| `whatsapp` \| `email` \| `reddit` \| `imessage` \| `bluesky`. | None — `/invite` uses the user's existing referral code (`referral.ensure_code`), not a `share_token`. |

Rule for the two `_shared` events: **fire on the Share *action*, in the same handler that
mints/looks-up the token** — one event per click, including re-shares (we want raw share
volume, the K-factor numerator). `shared_artifact_viewed` fires on the **public GET**, not
on the share, so the two together give a share→view ratio.

### 8.3 Acceptance checklist — R3-01 / R3-02 / R3-03

**R3-01 Match card** (this cycle)
- [ ] First Share on a card with null `share_token` mints one; second Share returns the
      same token (assert idempotent in a test).
- [ ] `match_card_shared` lands in `ProductEvent` with `source` ∈ {matches, applications}.
- [ ] Opening `/m/{token}` while logged out writes one `shared_artifact_viewed`
      (`user_id=None`, `kind=card`); a reload writes another (view count, not unique).
- [ ] Spec §1.4 acceptance (token→card, no name/JD/email leak, 404 on bad token, CTA ref,
      OG PNG) all still hold.
- [ ] The mint/resolve, the PNG renderer, and the anon-view emit are factored for reuse
      (§8.0a) — not inlined in the match-card handler.

**R3-02 Market read** (next cycle — reuses R3-01 machine)
- [ ] `/r/{token}` renders the **four real stage counts** read straight off `Search`
      (`raw_count → located_count → ranked_count → scored_count`) as a four-step funnel with
      the headline "{raw_count} roles scanned → {scored_count} worth your time." **No engine
      change; no reason buckets** (reason histogram is v2, §2.3 — do not fake buckets).
- [ ] First "Share this read" mints `Search.share_token` via the R3-01 helper; idempotent
      on re-share; unshared scans have no public surface.
- [ ] Anonymise toggle defaults **ON** (§2.4): with it on, no first name and no employer
      names appear — only aggregate counts + the target role/function label; CV text and
      specific-employer list never appear regardless of the toggle.
- [ ] `market_read_shared` lands with a `source` prop; `/r/{token}` view writes
      `shared_artifact_viewed` with `kind=read` (anon, `user_id=None`).
- [ ] A scan still running or failed → friendly "not ready", not the funnel; unknown
      token → 404.
- [ ] CTA carries the sharer's ref code (`/signup?ref={code}`); OG image is the read PNG
      (second render target, §8.0a.2); page is `noindex,nofollow`.

**R3-03 /invite** (next cycle — no share_token, no PNG)
- [ ] `GET /invite` shows the user's real code + link (`referral.ensure_code` /
      `referral.invite_url`); copy buttons work; reward numbers come from config
      (`REFERRAL_FRIEND_CREDITS` / `REFERRAL_CREDITS`), never hard-coded.
- [ ] Live counter reads the DB on each load and shows **"N friends activated · +{credits}
      credits"** leading with *activated* (the thing that pays out), signed-up count
      secondary; numbers match `User.referred_by_user_id == me.id` + the
      `referral_activated` ledger rows (§3.2).
- [ ] Per-channel pre-written messages (LinkedIn / X / Bluesky, WhatsApp / iMessage, email,
      Reddit) each embed the correct `invite_url`; share-intent links open the right
      composer; mobile uses `navigator.share` where available. **Copy is GC-cleared before
      launch** (§6 / §8.5).
- [ ] `GET /invite` writes exactly one `invite_page_viewed` per load; each copy control
      writes `invite_link_copied` with the right `channel` value.
- [ ] `/signup?ref={code}` attribution + first-scan reward already wired
      (`attach_and_reward_friend`, `reward_inviter_if_activated`) — no new reward code.

### 8.4 R3-04 — Profile-completeness meter (the first activation test)

Ready to implement. Grounded in `services/profile_service.py` **re-verified 2026-10-28**.

**What the gate actually is (read this first — it is not `score >= 70`).**
`completeness(db,user)` returns a `Completeness` with `score` (0–100) and
`can_search` (`@property` → `not self.missing_required`, line ~61). Confirmed live:
`score = round(req_hit*70 + opt_hit*30)` — the 8 **required** fields carry 70% of the score,
the 5 optional fields the other 30%. So the score hits 70 **exactly** when all required
fields are in — the same instant `can_search` flips true, *if the user filled requireds
first*. But a user who front-loads optional fields can read **~79–91% and still be locked**
(one required field missing → `can_search` False). **Therefore the CTA's enabled/disabled
state and the `profile_threshold_reached` event MUST key off `can_search`, never off
`score >= 70`.** The % is the friendly progress number; the unlock is the required-field set.

**⚠ Gotcha — there are TWO `can_search` in `profile_service.py`; use the right one.**
`Completeness.can_search` (≈ line 61, `not missing_required`) is the gate — it is what
`start_search` actually enforces before raising `QuotaError`, so it is what the meter's CTA
must mirror. There is a **second, unrelated** `can_search` further down (≈ line 189,
`band != "thin"`, on the match-readiness/band class). Do **not** wire the CTA to the band
one — bind strictly to `completeness(db, user).can_search`. The fixture test below also
pins this (an ~85% optional-heavy user is `Completeness.can_search == False`).

**What counts toward the %** (from `FIELDS`, do not re-list by hand — read it from the dict):
- **Required (70% of the bar, all 8 needed to unlock):** At least one CV · About you ·
  What you're looking for · Seniority · Company type · Sectors · Locations · Job type.
- **Optional (remaining 30%, improve match quality, never gate search):** A cover letter ·
  LinkedIn export · Companies you'd work for · Job titles to search · Salary floor.
- Render the "70" in the copy from the required-field weight constant, **not** a hard-coded
  string — if `FIELDS` weighting changes, the copy must track it.

**Where it sits.** A persistent, sticky strip at the top of the onboarding profile form
(`routes/onboarding.py` / the profile template), visible on every sub-step — not a separate
screen and not buried at the bottom. It is the one element that is always on screen while
the user fills the profile, turning the invisible gate (§5) into a closable goal.

**Copy (reuse the existing `BAND_COPY["thin"]` voice, do not invent a second register).**
- Locked: **"Profile 55% — Run my free scan unlocks at 70%"** with a sub-line listing the
  exact remaining required fields from `completeness.missing_required` (e.g. "Still needed:
  Locations, Job type"). This is the existing "thin" band's promise ("Add what's still
  missing and your first search unlocks") made literal and per-field.
- Unlocked (the moment `can_search` is true): **"Profile 70% — Run my free scan"**, CTA
  live. If `score < quality_threshold` after unlock, keep the existing `should_improve`
  nudge *below* the now-active CTA (honest matching) — never gate the free scan on it.

**CTA behaviour.**
- One primary button, value copy, message-match to the scan it triggers (cro).
- **Disabled while `can_search` is False** — shown, not hidden, with the missing-required
  checklist as its "to unlock" affordance. It is *not clickable* while locked, which is the
  fix: today the gate is discovered only by a failed scan attempt (silent `QuotaError`
  bounce). If a locked scan attempt still reaches `start_search` (deep link, stale page),
  that path emits `scan_blocked_incomplete` instead of bouncing silently.
- The instant `can_search` flips true (last required field saved), the button goes live
  in place — no reload, no new screen — and triggers the free first scan.

**Instrumentation (single KPI = first-scan rate = `scan_started` / `signup_completed`).**
- `onboarding_step_completed` — prop `step_name` = which profile sub-step was completed;
  localises *where* in the profile users stall (the §5 open question).
- `profile_threshold_reached` — fired once, when `can_search` first flips true for a user.
- `scan_blocked_incomplete` — fired where `start_search` would raise `QuotaError`; measures
  how often the old silent-bounce path is still hit after the meter ships (should trend to
  ~0 if the visible meter works).

**A/B (ab-testing; run where traffic allows, else ship as best-practice default and watch
the KPI).**
- **Variant (meter+CTA):** the sticky meter + persistent "Run my free scan — unlocks at
  70%" CTA described above.
- **Control:** today's onboarding — no meter, gate discovered only on a scan attempt.
- **Single success metric:** first-scan rate (`scan_started`/`signup_completed`) per
  assigned cohort. Guardrail (do-no-harm) metric: profile *quality* band at first scan
  (don't let the meter push people to scan at a barely-thin profile and get bad matches).

**R3-04 acceptance checklist**
- [ ] Meter is visible on every onboarding profile sub-step and updates live as fields are
      saved.
- [ ] The % shown equals `completeness(db,user).score`; the number in the copy is derived
      from the required-field weight, not hard-coded.
- [ ] CTA enabled state is driven by `Completeness.can_search` (the `not missing_required`
      one, **not** the band `can_search` and **not** `score >= 70`) — **fixture test
      required:** a user with all 5 optional fields + enough requireds to read ~85% score
      but **one required field still missing** → `can_search == False` and the CTA stays
      disabled. This single test is the guard against the whole-feature correctness bug.
- [ ] Locked sub-line lists exactly `completeness.missing_required` labels.
- [ ] `onboarding_step_completed` (with `step_name`), `profile_threshold_reached` (once, on
      first unlock), and `scan_blocked_incomplete` (on a locked scan attempt) all land in
      `ProductEvent`.
- [ ] Clicking the live CTA starts the free first scan with no intermediate screen.
- [ ] A/B assignment is recorded so first-scan rate can be read per cohort; control path is
      unchanged from today.

### 8.5 Request carried forward

The §6 **REQUEST** stands: GC clears the external-claim copy in the share/invite messages
(§3.3) and the public CTA copy before these go live. The new meter copy in §8.4 is
in-product (not an external claim) and does not need GC clearance, but keep the "70%"
number honest per guardrail 8 — it is a structural fact of the field weighting, not a stat.

---
Skills used: cro (single primary value-CTA, message-match on the scan trigger, turning the
invisible gate into a visible closable goal), onboarding (meter placement in the profile
flow, per-step completion events, reusing the existing band voice instead of a second
register), ab-testing (named the single KPI + do-no-harm guardrail, variant/control
definition, cohort-readable assignment), analytics (event-per-action mapping, the anon
public-view event, the R2-01 allowlist confirm-gate), task-observer (session-start).
Skills considered but not used: signup (the fix is inside the profile step, not the
signup form — nothing to change at sign-up this cycle); paywalls / churn-prevention (not
relevant to Step-1 activation); frontend-ui-engineering / web-design-guidelines /
apple-design (exact meter/CTA markup + CSS is the CTO's build step — this brief reuses the
existing profile template and `BAND_COPY` voice rather than re-specifying pixels).
(Cycle-1 skills for §1–7 above: referrals, cro, analytics, task-observer.)
