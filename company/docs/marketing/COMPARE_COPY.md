# Comparison-page copy (R2-08)

Owner: CMO · Created 2026-10-26 · Source: `DIRECTORIES_AND_COMPARISONS.md §(c)` outlines, the live `/compare/linkedin-jobs` page, `COMPETITOR_MAP.md`, GTM §6. Finished prose for the four draft comparison pages, ready for CTO/CPO to wire into templates once GC clears the claims.

## GC clearance summary (2026-10-28)

**20 CLEARED · 4 REVISED · 2 HELD** (+1 conditional hold: naming Teal+'s exact price).

- **CLEARED** = the wording is honest, comparative-fair (Compliance Card C4) and non-misleading *as written*. It is **not** a currency check: every competitor-fact cell stays gated on the one-time hands-on source check that fills the `Last reviewed against official sources on …` line. **No page ships with that date blank.** I did not run that check — those date placeholders stay as-is until someone confirms each cell against the competitor's live site.
- **REVISED (4):**
  1. Jobright "US-centric" → "US market focus" (loaded characterisation; geography drifts).
  2. Teal pricing → structure only ("free tier + paid Teal+"), **no dollar figure** in copy.
  3. Auto-apply ToS cell → LinkedIn automated-activity term kept (certain); the Indeed "Apply-for-Me paused" status removed.
  4. Teal lede "every live role it can reach" → "25+ sources" — the only signed-off coverage phrasing.
- **HELD (2) — blockers:**
  1. **"marginal application past ~30 is close to worthless"** — needs a real, dated stat from our own match corpus (GTM §5.3). *Unblocks when:* CFO/CTO run a dated corpus query quantifying the diminishing return. Interim shippable copy uses a non-numeric form.
  2. **Indeed "Apply-for-Me" current status** — needs a current, dated source confirming paused/live. *Unblocks when:* the hands-on source check reads Indeed's own page/help docs on the review date and cites it. Until then the claim is omitted.
  - *Conditional hold:* naming **Teal+'s exact price** — hold until confirmed at the source check; the revised cell asserts only the free/paid structure.
- **Own coverage phrasing:** "25+ sources" is **CLEARED** as the defensible form; "every live role we can reach" stays **prohibited** until a separate sign-off with substantiation.
- **LinkedIn automated-activity ToS:** CLEARED, consistent with `THIRD_PARTY_TERMS.md` (tagged `[CERTAIN]`); still verify current wording before the page goes live.

## GC source pass R3-12 (2026-11-13) — public pages only, no accounts

Access date for every URL below: **2026-11-13**. Read without sign-up, login or forms. Fetched content treated as data. Each competitor-fact cell now carries ✓ (page supports it), ✗ (page contradicts it — copy corrected) or ? (not determinable publicly) with its URL inline.

**Competitor-fact cells (24):** **17 ✓ · 2 ✗ · 5 ?** on the 2026-10-28 wording.
- **✗ → corrected (2):** Simplify "1-click apply" (they say one-click *autofill*, and sell a separate auto-apply product); Simplify coverage "across the boards you visit" (they also run their own job search).
- **? → reworded to something the public page does support (4):** Jobright listing source → "its own large job board"; Simplify fit signal → "AI job matching in its job search"; Simplify "built to apply faster" → time-per-application + Autopilot; auto-apply fit method → "filters such as role, location, salary and keywords".
- **? still open (1):** Indeed "Apply for me" status — stays omitted (copy ships without it).
- **Fairness additions (C4):** Simplify lede now says it also has job search + an auto-apply product.
- **Own-claim ✗ found in passing (2, not competitor cells):** Teal table "across the whole market" (prohibited absolute) → "for every role we shortlist from 25+ sources"; auto-apply lede "ten to twenty roles" (unsourced number) → "the short list of roles".
- **Teal caveat:** tealhq.com returns HTTP 403 to automated readers; its 7 cells are ✓ from Teal's own pages as indexed by search plus Teal-published articles, not a direct read. The Teal page's "Last reviewed" date stays blank until a human opens 3 public Teal pages (R-012 step 1).
- **Not named, not needed:** Sonara (sonara.ai timed out; third-party sources conflict on whether it relaunched under BOLD). The auto-apply page copy names no product, so nothing ships on Sonara's status. Do not add product names to that page without a fresh check.
- **Dates set:** `/compare/jobright`, `/compare/simplify`, `/compare/auto-apply-tools` → "13 November 2026". `/compare/teal` → pending R-012 step 1.
- **Still HELD (internal, not a web check):** the quantified "marginal application past ~30" stat (CFO/CTO corpus query, GTM §5.3). Interim non-numeric copy ships.

**Structure (every page matches the live `compare_linkedin_jobs.html`):** eyebrow `COMPARISON` → `h1` "JBHNTR and [X], compared" → `lede` framing the honest difference → `Last reviewed …` line → one "Where they differ" table (Dimension · [Competitor] · JBHNTR) → a "When [X] is the better tool" honest section → the CTA pair (`Start a free scan` → `/signup`, `How matching works` → `/how-it-works`).

**Compliance gate (binding).**
- **Every competitor claim below is marked `[VERIFY]` and is a draft as of 2026-10-26.** GC + a hands-on check confirm each against the competitor's own site/docs and re-date it before publish. "Not listed on their page" is never written as "they don't have it".
- The `Last reviewed against official sources on …` line is left as a placeholder on purpose. **No review has happened yet** — it is filled with the real date only when GC clears the `VERIFY` cells and someone checks each against source. Do not ship a fabricated review date.
- Our own coverage phrasing uses **"25+ sources"**, never "every live role" in a claim cell — the broader phrasing ("every live role we can reach") is still pending GC sign-off (carried from `BRAND_ACCOUNTS.md`).
- Plural voice throughout. We are the vendor on our own page, so the community disclosure line ("we build a tool in this space") is not needed here; it belongs in threads.

---

## `/compare/jobright`

**Eyebrow:** COMPARISON
**h1:** JBHNTR and Jobright, compared

**Lede:**
> Jobright is an AI job-search assistant with a matching feed, resume tailoring, and an agent that can apply to roles for you [CLEARED 2026-10-28] [✓ 2026-11-13: https://jobright.ai/ai-agent — "…customizing your resume, and applying for you"]. JBHNTR reads across many sources and scores each role in both directions, then stops at the shortlist and leaves the applying to you. The two tools make the opposite bet about where your effort pays off: automating the applying, or sharpening the deciding.

**Last reviewed:** `Last reviewed against official sources on 13 November 2026.` [set by GC 2026-11-13, R3-12: all cells ✓ on public pages]

**Where they differ:**

| Dimension | Jobright | JBHNTR |
|---|---|---|
| Automating the application | Offers an AI apply/agent flow and resume tailoring, strong if volume is the goal [CLEARED 2026-10-28] [✓ 2026-11-13: https://jobright.ai/ai-agent ; https://jobright.ai/job-autofill "Tailor Your Resume For Each Job With AI"] | No auto-apply by design; we return the few worth a considered application |
| Fit signal | A match score toward each role [CLEARED 2026-10-28] [✓ 2026-11-13: https://jobright.ai/ai-job-match "Match Score estimates how closely your background fits a job"] | Two scores, role fit and requirements fit, with the reasons for and against |
| Where roles come from | Its own large job board [REVISE 2026-11-13: was "Aggregated listings" — **?** its public pages and Terms do not say where listings come from; https://jobright.ai/job-autofill calls itself "The Largest Job Board!" and https://jobright.ai/legal/service (updated 29 Jul 2026) says employers and recruiters "use Jobright to post jobs" → ✓ for the new wording] | 25+ sources, including direct employer career pages |
| Geography | US market focus [REVISE 2026-10-28: was "US-centric"] [✓ 2026-11-13: https://jobright.ai/ search defaults to "United States"; https://jobright.ai/h1b-jobs "All U.S. locations", U.S. DOL sponsorship data] | EU and UK first, every geography open; our GDPR posture is deliberate |
| Privacy and openness | Proprietary [CLEARED 2026-10-28] [✓ 2026-11-13: https://jobright.ai/legal/service §2 "We are the owner or the licensee of all intellectual property rights in our Services"; §8–9 bar copying/reverse engineering] | Source-available shell on GitHub, matching engine private; your profile private by default |

**When Jobright is the better tool:**
> If you want to send a high volume of applications quickly and want the tool to do the applying, an apply agent does something we deliberately do not. JBHNTR makes the opposite bet: fewer, better-chosen applications that you send yourself. Pick Jobright when throughput is the point. Pick JBHNTR when the problem is deciding which roles are worth your time at all.

**CTA:**
> `Start a free scan` → `/signup` · `How matching works` → `/how-it-works`

---

## `/compare/simplify`

**Eyebrow:** COMPARISON
**h1:** JBHNTR and Simplify, compared

**Lede:**
> Simplify is a browser extension that autofills and speeds up applications across job boards, with a tracker alongside it [CLEARED 2026-10-28] [✓ 2026-11-13: https://simplify.jobs/copilot "free browser extension that autofills job applications on 100,000+ company career sites in one click and saves every application to your Simplify tracker"]. It also has its own job search with AI matching and a separate auto-apply product [ADDED 2026-11-13 for C4 fairness: https://simplify.jobs/ "AI job matching"; https://simplify.jobs/llms.txt "Autopilot … AI auto apply … submits the application"]. JBHNTR works a step earlier: it decides which roles are worth applying to at all, with reasons, before you spend effort on any of them. One tool makes applying faster. The other makes you apply less.

**Last reviewed:** `Last reviewed against official sources on 13 November 2026.` [set by GC 2026-11-13, R3-12: all cells ✓ after the revisions marked]

**Where they differ:**

| Dimension | Simplify | JBHNTR |
|---|---|---|
| Speed of applying | One-click autofill on supported career sites and application systems, plus a separate AI auto-apply product [REVISE 2026-11-13: was "Autofill and 1-click apply across boards" — **✗** Simplify does not say "1-click apply"; it says autofill "in one click" (https://simplify.jobs/copilot) and sells Autopilot, which "submits the application" (https://simplify.jobs/llms.txt)] | We do not fill or submit applications; we choose which few deserve one |
| Where it acts in the funnel | Mainly at the application step; it also has a job search [CLEARED 2026-10-28; fairness edit 2026-11-13] [✓ 2026-11-13: https://simplify.jobs/llms.txt "Simplify Copilot helps candidates autofill applications…"; "Job Search: Search and filter job postings with AI-powered matching"] | At the decision step, before you apply |
| Fit signal | AI job matching in its job search [REVISE 2026-11-13: was "A match/relevance signal within the extension" — **?** no public page ties a match signal to the extension; ✓ for the new wording: https://simplify.jobs/ "Get matched to relevant roles from millions of openings based on your experience, skills, and preferences"] | A two-way fit score with the reasons for and against |
| Coverage | Its own job search, plus autofill on the career sites you visit [REVISE 2026-11-13: was "Across the boards you visit" — **✗** understates them: Simplify runs its own listings (https://simplify.jobs/llms.txt "Latest Jobs: Recently posted job openings updated daily") and autofill covers "100,000+ company career sites" (https://simplify.jobs/copilot)] | We scan 25+ sources for you, including career pages you would not check |
| Control | Built to cut the time per application; its Autopilot product can submit applications for you [REVISE 2026-11-13: was "Built to apply faster" — **?** the Copilot page makes no speed claim; ✓ for the new wording: https://simplify.jobs/llms.txt "apply faster" (AI Job Search) and Autopilot "submits the application"] | Built so you apply deliberately; nothing is sent without you |

**When Simplify is the better tool:**
> If you have already chosen the roles and want to cut the time per application, an autofill extension saves real minutes on every form. JBHNTR does not speed applying up. It reduces how many applications you need to send in the first place, which is a different kind of saving. Use both and they stack: pick the shortlist with us, fill the forms faster with Simplify.

**CTA:**
> `Start a free scan` → `/signup` · `How matching works` → `/how-it-works`

---

## `/compare/teal`

**Eyebrow:** COMPARISON
**h1:** JBHNTR and Teal, compared

**Lede:**
> Teal is a workspace for your search: a job tracker, a résumé builder, and bookmarking from across boards [CLEARED 2026-10-28] [✓ 2026-11-13, indexed copy — direct fetch of tealhq.com returns HTTP 403 to automated readers: https://www.tealhq.com/tools/job-tracker "bookmark jobs … with one click from 40+ job boards"; https://www.tealhq.com/tools/resume-builder]. JBHNTR is the agent that does the looking. It scans 25+ sources and ranks the handful worth pursuing [REVISE 2026-10-28: was "every live role it can reach" — unsigned coverage phrasing], rather than giving you a place to organise the ones you found yourself.

**Last reviewed:** `Last reviewed against official sources on [DATE — set when R-012 step 1 (Teal eyeball) is done].` [GC 2026-11-13: Teal blocks automated reads (403); cells verified from indexed Teal pages only]

**Where they differ:**

| Dimension | Teal | JBHNTR |
|---|---|---|
| Finding roles | You save roles you find; Teal organises them [CLEARED 2026-10-28] [✓ 2026-11-13 indexed: https://www.tealhq.com/tools/job-tracker — stages Bookmarked → Applying → Applied → Interviewing…; **?** whether Teal also recommends roles itself — R-012 human check] | We scan 25+ sources and rank the few worth a decision |
| Résumé building | Built-in résumé builder and tailoring [CLEARED 2026-10-28] [✓ 2026-11-13 indexed: https://www.tealhq.com/tools/resume-builder ; https://www.tealhq.com/post/teal-vs-huntr] | We tailor a CV and cover letter to a role you have chosen; building a CV from scratch is not our core |
| Tracking | Polished tracker and Chrome extension [CLEARED 2026-10-28] [✓ 2026-11-13 indexed: https://www.tealhq.com/post/teal-vs-huntr "Chrome extension that saves jobs from 40+ job boards"] | We have a tracker, but our weight is on the shortlist, not the filing cabinet |
| Fit signal | A keyword match score between your résumé and a saved role [precision edit 2026-11-13: was "A match score on saved roles"] [✓ 2026-11-13 indexed: https://www.tealhq.com/post/teal-vs-resume-worded — Job Matcher marks each keyword present/missing; free plan shows top 5 keywords] | A two-way fit score with the reasons for and against, for every role we shortlist from 25+ sources [REVISE 2026-11-13, own claim: "across the whole market" is the prohibited absolute-coverage form — **✗**] |
| Pricing | Free tier plus a paid subscription (Teal+) [REVISE 2026-10-28: was "Freemium with a paid Teal+ tier"; state no dollar figure — exact Teal+ price is HOLD until confirmed at the source check] [✓ structure 2026-11-13: Teal-published https://www.tealhq.com/post/teal-vs-enhancv (pricing "reviewed October 19, 2026"): free plan + Teal+ at $13 / 7 days, $29 / 30 days, $79 / 90 days, auto-renewing. **Copy still names no dollar figure** — Teal changes price often; structure-only cell is the durable one] | First scan free; credits after |

**When Teal is the better tool:**
> If your main need is to build a strong résumé and keep a tidy tracker for roles you are already finding, Teal's workspace is built for exactly that. JBHNTR is for the earlier problem: not missing the right roles across a market too big to read by hand. If finding is not your bottleneck, Teal may be all you need.

**CTA:**
> `Start a free scan` → `/signup` · `How matching works` → `/how-it-works`

---

## `/compare/auto-apply-tools`

A positioning page, not a one-to-one table. Covers LazyApply, AIApply, Sonara, LoopCV-style tools as a category.

**Eyebrow:** COMPARISON
**h1:** JBHNTR and auto-apply tools

**Lede:**
> Auto-apply tools send applications for you, at volume [CLEARED 2026-10-28] [✓ 2026-11-13: https://lazyapply.com/ "150 Applications/Day" / "1500 Applications/Day" plans; https://www.loopcv.pro/ "Auto-Apply to 1,000+ Jobs"; https://aiapply.co/ "Let AIApply to matching jobs for you automatically"]. JBHNTR is a deliberate bet against that. We return the short list of roles actually worth applying to [REVISE 2026-11-13, own claim: was "the ten to twenty roles" — an unsourced number (C7); restore only with a dated KPIS/corpus figure] and leave the applying to you. Here is the honest case for each approach, so you can decide which problem you are trying to solve.

**Last reviewed:** `Last reviewed against official sources on 13 November 2026.` [set by GC 2026-11-13, R3-12: Indeed not named; all named facts ✓]

**Where they differ (category, not one product):**

| Dimension | Auto-apply tools | JBHNTR |
|---|---|---|
| What they are great at | Throughput: hundreds of applications with little effort [CLEARED 2026-10-28] [✓ 2026-11-13: https://www.loopcv.pro/pricing "applications to hundreds of matching roles per week across 30+ job boards"; https://lazyapply.com/pricing] | Precision: the few roles worth a considered application |
| How fit is judged | Filters such as role, location, salary and keywords, to send applications fast [REVISE 2026-11-13: was "Keyword and relevance matching" — **?** none of LazyApply/AIApply/LoopCV describes its matching method; ✓ for the new wording: https://aiapply.co/ (role, location, salary preferences), https://www.loopcv.pro/ "advanced filters, keyword search, company exclusion"] | A two-way fit score with the reasons for and against |
| Platform rules | Mass-apply can run against platform terms, for example LinkedIn's terms on automated activity [CLEARED 2026-10-28: consistent with THIRD_PARTY_TERMS, tagged CERTAIN] [✓ 2026-11-13: https://www.linkedin.com/legal/user-agreement (effective 3 Nov 2025) §8.2(13) "Use bots or other unauthorized automated methods to access the Services…"; https://www.linkedin.com/help/linkedin/answer/a1341387 "…browser extensions that scrape, modify the appearance of, or automate activity on LinkedIn's website"] [REVISE 2026-10-28: Indeed "Apply-for-Me paused" status removed] [HOLD: to name Indeed, needs a current dated source confirming the feature's status] [**?** 2026-11-13: an Indeed-owned release exists in search results (https://www.indeed.com/news/releases/indeed-tests-apply-for-me-job-search) describing a limited U.S. test, but indeed.com and support.indeed.com return HTTP 403 to automated readers and no date was readable → stays omitted; R-012 human step] | We never apply on your behalf, so there is nothing to run against the rules |
| Effect on the recruiter side | A high volume of low-fit applications can weaken how you are received [CLEARED 2026-10-28: framed as a tendency, not a measured claim] | Fewer, better-targeted applications protect your signal |

**Our position (plain):**
> We think most of the value is in the first handful of well-chosen applications, not the hundredth [HOLD: the quantified form — "the marginal application past ~30 is close to worthless" — needs a real, dated stat from our own corpus before it goes public, GTM §5.3]. Automating more of them optimises the wrong number. We optimise which few to send. That is the whole bet, and it is why we will never add an apply agent.

**When an auto-apply tool is the better choice:**
> If you have decided that casting the widest possible net is your strategy, and you accept the platform-terms risk that can come with it, a mass-apply tool does that at a scale no human can. We are built for the opposite candidate: the mid-senior professional who would rather send fifteen strong applications than three hundred weak ones.

**CTA:**
> `Start a free scan` → `/signup` · `How matching works` → `/how-it-works`

---

## Claims flagged for GC sign-off (before any page is published)

**GC processed every one of these on 2026-10-28 — see the "GC clearance summary" at the top. The groups below are the original index of what was flagged.** Each cell now carries `[CLEARED 2026-10-28]`, `[REVISE 2026-10-28: …]`, or `[HOLD: …]`. The grouping:

1. **Jobright** — the AI apply/agent flow + resume tailoring; "a match score toward each role"; "aggregated listings" coverage; "US-centric"; "proprietary". (Confirm against jobright.ai + a hands-on trial.)
2. **Simplify** — autofill / 1-click apply scope; "acts at the application step"; in-extension match signal; "across the boards you visit"; "built to apply faster". (Confirm against simplify.jobs + trial.)
3. **Teal** — job tracker + résumé builder + bookmarking feature set; "match score on saved roles"; **current Teal+ pricing** (changes often — re-date). (Confirm against tealhq.com + trial.)
4. **Auto-apply category** — per-tool "throughput" and "keyword matching" framing for LazyApply / AIApply / Sonara / LoopCV; **the ToS facts**: LinkedIn's terms on automated activity, and whether Indeed's Apply-for-Me is still paused (status + sources, re-date); the "harms how you are received" framing.
5. **Our own claims (not competitor facts, but GC-gated):** the coverage phrasing — **"25+ sources"** is used throughout as the defensible form; "every live role we can reach" is still pending GC sign-off. The **"marginal application past ~30 is close to worthless"** claim must have a real number from our corpus behind it before it is public (GTM §5.3) — now **HELD** inline; shipped copy uses the non-numeric interim form until the corpus stat exists.

**Build note:** these are copy, not templates. CTO/CPO wire the routes and templates (matching `compare_linkedin_jobs.html` + the `_compare_table.html` partial) once GC clears the claims and each `VERIFY` cell is confirmed and dated. Each page gets a single `h1`; FAQ/JSON-LD schema is a CTO concern at build time, not part of this copy.

Skills used: competitors (honest "they win on X / we win on Y" tables, Evidence Discipline — dated `VERIFY` cells, "not observed ≠ absent", explicit who-it's-for sections, format match to the live page), copywriting (finished ledes/CTAs, benefit-over-feature, no AI tells, no em dashes in short copy, no self-answered questions or negation lists), brand-voice:brand-voice-enforcement (plural "we / the JBHNTR team", no-auto-apply framing, honest tone, no hype/emojis).
Skills considered but not used: ai-seo / seo-audit (GEO/schema is a separate pass once pages are built), programmatic-seo (scaling alternative pages is a later task), schema (JSON-LD belongs with the CTO build), launch (PH/HN launch is week 7–8).

Skills used (GC R3-12 pass, 2026-11-13): product-legal:marketing-claims-review (claim taxonomy: comparative/absolute/implied; caught the two own-claim absolutes), legal:legal-risk-assessment (publish-with-unverified-cells risk). Web reads via WebFetch/web-fetch agents + WebSearch.
Skills considered but not used: competitors / competitor-profiling / brightdata-plugin:competitive-intel (CMO-side positioning and scraping; GC needed source verification, not new copy or bulk scraping); anthropic-skills:deep-research (a handful of known URLs, not open research).
