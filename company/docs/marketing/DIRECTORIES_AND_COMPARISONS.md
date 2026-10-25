# Directories & comparison pages (R1-08)

Owner: CMO · Created 2026-10-25 · Source: GTM manual §6 (directories + comparison pages), §4.1 (match card), existing `/compare/linkedin-jobs`.

**Scope.** (a) the one 40-word description + the listing image spec reused everywhere; (b) the directory list with submission URLs and maker-field handling; (c) outlines for `/compare/jobright`, `/compare/simplify`, `/compare/teal`, `/compare/auto-apply-tools`, matched to the existing `/compare/linkedin-jobs` template.

**Compliance gate (binding).** GC clears every external claim before anything is filed to submit or publish. Two hard rules carried from the directory-submissions skill: **destination pages and privacy/terms must be live before we submit** anywhere, and **every competitor-fact cell below is dated and marked `VERIFY`** — we confirm it against the competitor's own site/docs (or a hands-on trial) and re-date it before publish. "Not listed on their page" is never written as "they don't have it".

---

## (a) The one description + the listing image

### 40-word product description (reuse on every directory)
> JBHNTR reads every live role for a mid-senior professional and returns the ten to twenty worth pursuing, with a two-way fit score and honest reasons for and against. No auto-apply. A small, founder-led project in private beta, built in Europe.

(Exactly 40 words. The directory-submissions skill recommends varying the opening sentence per directory tier to avoid duplicate-content down-weighting; GTM §6 asks for one description everywhere. We follow §6 for consistency now, and keep per-tier opener variants as an optional later refinement if AI-citation tracking shows duplicate-content drag.)

**Shorter forms derived from it:**
- **Tagline (<10 words):** Less searching. Fewer applications. Better matches.
- **60-char:** Every live role, scored both ways. The few worth pursuing.
- **5–8 tags:** job search, AI job matching, career, recruiting, job board alternative, mid-senior roles, Europe.
- **Maker field (every listing):** `JBHNTR team` — never a personal name (GTM §6, §3.1).

### Match-card listing image spec
One image reused across every directory and as the OG card, so the brand reads identically everywhere.
- **Source:** the match-card template from GTM §4.1 (the "Senior Product Manager, Payments" sample — a realistic, anonymised card, never a real user).
- **Size:** 1200×630 PNG (OG/directory standard); also export 1270×760 for Product Hunt gallery and a 1:1 1024×1024 crop for avatar-style slots.
- **Must show:** the JBHNTR wordmark, the two scores ("Fits what you want 91 / You fit what they need 74"), one ✓ fit line and one ⚠ watch-out line, the tagline footer, and `jbhntr.app`.
- **Must not show:** any real user's name, any real salary/company unless it is the fabricated sample, any founder name or face.
- **Where it lives:** a static asset (e.g. `web/app/static/og/directory-card.png`) rendered once from the §4.1 template, so it is identical everywhere and does not depend on the live `/m/{short_id}` render path (which CTO/CPO own). Build note handed to CTO/CPO; not built here.

---

## (b) Directory list

**Readiness first (directory-submissions Rule 1–2).** Before submitting, these must be live and indexed: pricing/credits page (exists), privacy + terms naming the controller + `privacy@` (GC — pending, §12.2), the four comparison pages below, 5–8 real screenshots, a short demo clip, logo assets. G2/Capterra listings are dead without reviews — defer those to launch month and run the 10-in-30 review drive then. **Each submission is an outward action: file it as a Founder REQUEST, one row at a time, never auto-submit** (CHARTER guardrail 1).

| Directory | Submit at | Maker field | Notes / timing |
|---|---|---|---|
| AlternativeTo | alternativeto.net/manage/submit-app/ | JBHNTR team | List as alternative to Simplify, Jobright, Teal, LinkedIn Jobs, Indeed. Week 1. |
| There's An AI For That (TAAFT) | theresanaiforthat.com/submit/ | JBHNTR team | AI-first framing. Week 1–3. |
| Futurepedia | futurepedia.io/submit-tool | JBHNTR team | AI directory. Week 1–3. |
| SaaSHub | saashub.com/submit | JBHNTR team | SaaS/alternative framing. Week 1. |
| BetaList | betalist.com/submit | JBHNTR team | Pre-launch/private-beta friendly — fits our stage now. Week 1. |
| Uneed | uneed.best/submit-a-tool | JBHNTR team | Indie launch. One afternoon. |
| Product Hunt "coming soon" | producthunt.com/products/new (Ship / upcoming) | JBHNTR team | **Free "coming soon" page only** — no founder-led PH launch in Phase 1 (§2, §3.3). Collects "notify on launch" subscribers. |
| G2 | g2.com/products/new | JBHNTR team | **Defer:** worthless until ~10 reviews (10-in-30 drive at launch month). Do not buy a paid plan year one. |
| Capterra | capterra.com/vendors/sign-up | JBHNTR team | **Defer** with G2 (now Gartner Digital Markets). |
| Toolify (optional) | toolify.ai/submit | JBHNTR team | Extra AI directory from §6; low effort if time allows. |
| MicroLaunch (optional) | microlaunch.net | JBHNTR team | Indie launch site from §6; afternoon, not strategy. |

**Also for GEO/AI-citation (directory-submissions + ai-seo):** claim the LinkedIn Company Page (done in R1-07), and a Crunchbase entry — both feed AI training corpora. Flag to GC/CEO; Crunchbase names a company so it waits on the incorporation decision (§12.2).

---

## (c) Comparison-page outlines

Format matches the live `/compare/linkedin-jobs`: eyebrow `COMPARISON`, an `h1` "JBHNTR and [X], compared", a `lede` that frames the honest difference, a `Last reviewed … on [date]` line, one "Where they differ" table (columns: Dimension · [Competitor] · JBHNTR), a "When [X] is the better tool" honest section, and the CTA pair (`Start a free scan` → `/signup`, `How matching works` → `/how-it-works`).

> **Every competitor cell is a draft claim as of 2026-10-25 and marked `VERIFY`.** GC + a hands-on check confirm and re-date each before publish. We do not auto-apply and we say so — but we also never overstate a competitor's limits.

### `/compare/jobright`
- **h1:** JBHNTR and Jobright, compared
- **lede:** Jobright is an AI job-search assistant with a matching feed and an apply agent. JBHNTR reads across many sources and scores each role in both directions, then stops at the shortlist and leaves the applying to you. They sit on opposite sides of one choice: automate the applying, or sharpen the deciding.
- **Where they differ (they win on X / we win on Y):**

| Dimension | Jobright `VERIFY` | JBHNTR |
|---|---|---|
| Automating the application | Offers an AI apply/agent flow and resume tailoring — strong if volume is the goal `VERIFY` | No auto-apply by design; we return the few worth a considered application |
| Fit signal | Match score / percentage toward the role `VERIFY` | Two scores — role fit and requirements fit — with reasons for and against |
| Where roles come from | Aggregated listings `VERIFY coverage claims` | 25+ sources including direct employer career pages |
| Geography focus | US-centric `VERIFY` | EU/UK first, all geographies open; GDPR posture is deliberate |
| Privacy & openness | Proprietary `VERIFY` | Source-available shell on GitHub; engine private; private profile by default |

- **When Jobright is the better tool (honest):** if you want to send a high volume of applications quickly and want the tool to do the applying, an apply agent does something we deliberately do not. JBHNTR is the opposite bet: fewer, better-chosen applications you send yourself.
- **CTA:** Start a free scan → `/signup` · How matching works → `/how-it-works`

### `/compare/simplify`
- **h1:** JBHNTR and Simplify, compared
- **lede:** Simplify is a browser extension that autofills and speeds up applications across job boards, plus a tracker. JBHNTR works a step earlier: it decides which roles are worth applying to at all, with reasons, before you spend effort on any of them.
- **Where they differ:**

| Dimension | Simplify `VERIFY` | JBHNTR |
|---|---|---|
| Speed of applying | Autofill / 1-click apply across boards — fast form-filling `VERIFY` | We don't fill or submit applications; we choose which few deserve one |
| Where it acts in the funnel | At the application step `VERIFY` | At the decision step, before you apply |
| Fit signal | Match/relevance within the extension `VERIFY` | Two-way fit score with reasons for and against |
| Coverage | Across boards you visit `VERIFY` | Scans 25+ sources for you, including career pages you wouldn't check |
| Control / review | Built to apply faster `VERIFY` | Built so you apply deliberately; nothing is sent without you |

- **When Simplify is the better tool (honest):** if you've already chosen the roles and want to cut the time per application, an autofill extension saves real minutes. JBHNTR doesn't speed up applying — it reduces how many applications you need to send.
- **CTA:** same pair.

### `/compare/teal`
- **h1:** JBHNTR and Teal, compared
- **lede:** Teal is a workspace for your search: a job tracker, a résumé builder, and bookmarking from across boards. JBHNTR is the agent that does the looking — it scans every live role and ranks the handful worth pursuing, rather than giving you a place to organise the ones you found yourself.
- **Where they differ:**

| Dimension | Teal `VERIFY` | JBHNTR |
|---|---|---|
| Finding roles | You save roles you find; Teal organises them `VERIFY` | We proactively scan 25+ sources and rank the few worth a decision |
| Résumé building | Built-in résumé builder and tailoring `VERIFY` | We tailor CVs/cover letters to a chosen role, but building a CV from scratch is not our core |
| Tracking | Polished tracker and Chrome extension `VERIFY` | We have a tracker; our weight is on the shortlist, not the filing cabinet |
| Fit signal | Match score on saved roles `VERIFY` | Two-way fit score with reasons for and against, across the whole market |
| Pricing | Freemium with Teal+ `VERIFY current pricing` | First scan free; credits after |

- **When Teal is the better tool (honest):** if your main need is to build a strong résumé and keep a tidy tracker for roles you're already finding, Teal's workspace is built for that. JBHNTR is for the earlier problem — not missing the right roles across a market too big to read.
- **CTA:** same pair.

### `/compare/auto-apply-tools`
Positioning page (not a one-to-one table) — "why we don't auto-apply". Covers LazyApply / AIApply / Sonara / LoopCV-style tools as a category.
- **h1:** JBHNTR and auto-apply tools
- **lede:** Auto-apply tools send applications for you, at volume. JBHNTR is a deliberate bet against that: we return the ten to twenty roles actually worth applying to and leave the applying to you. Here's the honest case for each approach.
- **The honest table (category, not one product):**

| Dimension | Auto-apply tools `VERIFY per tool` | JBHNTR |
|---|---|---|
| What they're great at | Throughput — hundreds of applications with little effort `VERIFY` | Precision — the few roles worth a considered application |
| How fit is judged | Keyword/relevance to fire applications fast `VERIFY` | Two-way fit with reasons for and against |
| Platform rules | Mass-apply can run against platform terms — e.g. LinkedIn's terms on automated activity, and Indeed paused its Apply-for-Me feature `VERIFY sources + current status` | We never apply on your behalf, so there's nothing to run against the rules |
| Effect on the recruiter side | High volume of low-fit applications can harm how you're received `VERIFY framing` | Fewer, better-targeted applications protect your signal |

- **Our position (plain):** we think the marginal application past ~30 is close to worthless (data we can cite from our own corpus, GTM §5.3), so automating more of them optimises the wrong number. We optimise which few to send.
- **CTA:** same pair.

**Build note:** these are copy outlines, not templates. CTO/CPO wire the routes/templates (matching `compare_linkedin_jobs.html`) once GC clears the claims and the `VERIFY` cells are confirmed. The daily digest agent (R1-09) can draft the final prose per §6.

---

**Claims flagged for GC sign-off:** every `VERIFY` cell (Jobright apply-agent + US focus; Simplify autofill scope; Teal pricing + feature set; auto-apply ToS/LinkedIn/Indeed facts); the coverage phrasing "every live role" / "25+ sources"; the "marginal application is close to worthless" claim (needs our corpus number behind it before it's public).

Skills used: directory-submissions (readiness gate, maker field, submission URLs, one-afternoon vs defer-on-reviews), competitors (honest "they win on X / we win on Y" tables, Evidence Discipline / dated VERIFY cells / "not observed ≠ absent", who-it's-for sections, format match to existing page), copywriting (40-word description, ledes, CTAs, no AI tells), brand-voice:brand-voice-enforcement (plural voice, no auto-apply framing, honest tone).
Skills considered but not used: ai-seo / seo-audit (GEO tactics noted inline — FAQ schema, single H1 — but full SEO audit is a separate pass once pages are built), programmatic-seo (alternative-page scaling is a later task), launch (PH full launch is week 7–8), schema (JSON-LD belongs with the CTO build, not the copy outline).
