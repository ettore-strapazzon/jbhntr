# Comparison-page copy (R2-08)

Owner: CMO · Created 2026-10-26 · Source: `DIRECTORIES_AND_COMPARISONS.md §(c)` outlines, the live `/compare/linkedin-jobs` page, `COMPETITOR_MAP.md`, GTM §6. Finished prose for the four draft comparison pages, ready for CTO/CPO to wire into templates once GC clears the claims.

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
> Jobright is an AI job-search assistant with a matching feed, resume tailoring, and an agent that can apply to roles for you [VERIFY]. JBHNTR reads across many sources and scores each role in both directions, then stops at the shortlist and leaves the applying to you. The two tools make the opposite bet about where your effort pays off: automating the applying, or sharpening the deciding.

**Last reviewed:** `Last reviewed against official sources on [DATE — set when GC clears the VERIFY cells].`

**Where they differ:**

| Dimension | Jobright | JBHNTR |
|---|---|---|
| Automating the application | Offers an AI apply/agent flow and resume tailoring, strong if volume is the goal [VERIFY] | No auto-apply by design; we return the few worth a considered application |
| Fit signal | A match score toward each role [VERIFY] | Two scores, role fit and requirements fit, with the reasons for and against |
| Where roles come from | Aggregated listings [VERIFY coverage claims] | 25+ sources, including direct employer career pages |
| Geography | US-centric [VERIFY] | EU and UK first, every geography open; our GDPR posture is deliberate |
| Privacy and openness | Proprietary [VERIFY] | Source-available shell on GitHub, matching engine private; your profile private by default |

**When Jobright is the better tool:**
> If you want to send a high volume of applications quickly and want the tool to do the applying, an apply agent does something we deliberately do not. JBHNTR makes the opposite bet: fewer, better-chosen applications that you send yourself. Pick Jobright when throughput is the point. Pick JBHNTR when the problem is deciding which roles are worth your time at all.

**CTA:**
> `Start a free scan` → `/signup` · `How matching works` → `/how-it-works`

---

## `/compare/simplify`

**Eyebrow:** COMPARISON
**h1:** JBHNTR and Simplify, compared

**Lede:**
> Simplify is a browser extension that autofills and speeds up applications across job boards, with a tracker alongside it [VERIFY]. JBHNTR works a step earlier: it decides which roles are worth applying to at all, with reasons, before you spend effort on any of them. One tool makes applying faster. The other makes you apply less.

**Last reviewed:** `Last reviewed against official sources on [DATE — set when GC clears the VERIFY cells].`

**Where they differ:**

| Dimension | Simplify | JBHNTR |
|---|---|---|
| Speed of applying | Autofill and 1-click apply across boards, fast form-filling [VERIFY] | We do not fill or submit applications; we choose which few deserve one |
| Where it acts in the funnel | At the application step [VERIFY] | At the decision step, before you apply |
| Fit signal | A match/relevance signal within the extension [VERIFY] | A two-way fit score with the reasons for and against |
| Coverage | Across the boards you visit [VERIFY] | We scan 25+ sources for you, including career pages you would not check |
| Control | Built to apply faster [VERIFY] | Built so you apply deliberately; nothing is sent without you |

**When Simplify is the better tool:**
> If you have already chosen the roles and want to cut the time per application, an autofill extension saves real minutes on every form. JBHNTR does not speed applying up. It reduces how many applications you need to send in the first place, which is a different kind of saving. Use both and they stack: pick the shortlist with us, fill the forms faster with Simplify.

**CTA:**
> `Start a free scan` → `/signup` · `How matching works` → `/how-it-works`

---

## `/compare/teal`

**Eyebrow:** COMPARISON
**h1:** JBHNTR and Teal, compared

**Lede:**
> Teal is a workspace for your search: a job tracker, a résumé builder, and bookmarking from across boards [VERIFY]. JBHNTR is the agent that does the looking. It scans every live role it can reach and ranks the handful worth pursuing, rather than giving you a place to organise the ones you found yourself.

**Last reviewed:** `Last reviewed against official sources on [DATE — set when GC clears the VERIFY cells].`

**Where they differ:**

| Dimension | Teal | JBHNTR |
|---|---|---|
| Finding roles | You save roles you find; Teal organises them [VERIFY] | We scan 25+ sources and rank the few worth a decision |
| Résumé building | Built-in résumé builder and tailoring [VERIFY] | We tailor a CV and cover letter to a role you have chosen; building a CV from scratch is not our core |
| Tracking | Polished tracker and Chrome extension [VERIFY] | We have a tracker, but our weight is on the shortlist, not the filing cabinet |
| Fit signal | A match score on saved roles [VERIFY] | A two-way fit score with the reasons for and against, across the whole market |
| Pricing | Freemium with a paid Teal+ tier [VERIFY current pricing] | First scan free; credits after |

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
> Auto-apply tools send applications for you, at volume [VERIFY per tool]. JBHNTR is a deliberate bet against that. We return the ten to twenty roles actually worth applying to and leave the applying to you. Here is the honest case for each approach, so you can decide which problem you are trying to solve.

**Last reviewed:** `Last reviewed against official sources on [DATE — set when GC clears the VERIFY cells].`

**Where they differ (category, not one product):**

| Dimension | Auto-apply tools | JBHNTR |
|---|---|---|
| What they are great at | Throughput: hundreds of applications with little effort [VERIFY per tool] | Precision: the few roles worth a considered application |
| How fit is judged | Keyword and relevance matching, to fire applications fast [VERIFY per tool] | A two-way fit score with the reasons for and against |
| Platform rules | Mass-apply can run against platform terms, for example LinkedIn's terms on automated activity; Indeed paused its Apply-for-Me feature [VERIFY sources + current status] | We never apply on your behalf, so there is nothing to run against the rules |
| Effect on the recruiter side | A high volume of low-fit applications can weaken how you are received [VERIFY framing] | Fewer, better-targeted applications protect your signal |

**Our position (plain):**
> We think the marginal application past roughly thirty is close to worthless [VERIFY — needs a number from our own corpus before this goes public, GTM §5.3]. Automating more of them optimises the wrong number. We optimise which few to send. That is the whole bet, and it is why we will never add an apply agent.

**When an auto-apply tool is the better choice:**
> If you have decided that casting the widest possible net is your strategy, and you accept the platform-terms risk that can come with it, a mass-apply tool does that at a scale no human can. We are built for the opposite candidate: the mid-senior professional who would rather send fifteen strong applications than three hundred weak ones.

**CTA:**
> `Start a free scan` → `/signup` · `How matching works` → `/how-it-works`

---

## Claims flagged for GC sign-off (before any page is published)

Every `[VERIFY]` cell above, grouped:

1. **Jobright** — the AI apply/agent flow + resume tailoring; "a match score toward each role"; "aggregated listings" coverage; "US-centric"; "proprietary". (Confirm against jobright.ai + a hands-on trial.)
2. **Simplify** — autofill / 1-click apply scope; "acts at the application step"; in-extension match signal; "across the boards you visit"; "built to apply faster". (Confirm against simplify.jobs + trial.)
3. **Teal** — job tracker + résumé builder + bookmarking feature set; "match score on saved roles"; **current Teal+ pricing** (changes often — re-date). (Confirm against tealhq.com + trial.)
4. **Auto-apply category** — per-tool "throughput" and "keyword matching" framing for LazyApply / AIApply / Sonara / LoopCV; **the ToS facts**: LinkedIn's terms on automated activity, and whether Indeed's Apply-for-Me is still paused (status + sources, re-date); the "harms how you are received" framing.
5. **Our own claims (not competitor facts, but GC-gated):** the coverage phrasing — **"25+ sources"** is used throughout as the defensible form; "every live role we can reach" is still pending GC sign-off. The **"marginal application past ~30 is close to worthless"** claim must have a real number from our corpus behind it before it is public (GTM §5.3) — left `[VERIFY]` inline.

**Build note:** these are copy, not templates. CTO/CPO wire the routes and templates (matching `compare_linkedin_jobs.html` + the `_compare_table.html` partial) once GC clears the claims and each `VERIFY` cell is confirmed and dated. Each page gets a single `h1`; FAQ/JSON-LD schema is a CTO concern at build time, not part of this copy.

Skills used: competitors (honest "they win on X / we win on Y" tables, Evidence Discipline — dated `VERIFY` cells, "not observed ≠ absent", explicit who-it's-for sections, format match to the live page), copywriting (finished ledes/CTAs, benefit-over-feature, no AI tells, no em dashes in short copy, no self-answered questions or negation lists), brand-voice:brand-voice-enforcement (plural "we / the JBHNTR team", no-auto-apply framing, honest tone, no hype/emojis).
Skills considered but not used: ai-seo / seo-audit (GEO/schema is a separate pass once pages are built), programmatic-seo (scaling alternative pages is a later task), schema (JSON-LD belongs with the CTO build), launch (PH/HN launch is week 7–8).
