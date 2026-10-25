# Third-Party Terms Posture — JBHNTR

Owner: GC · v1 (2026-10-25) · Tracks the ToS of every platform the product or growth relies on, flags what our GTM might breach, and states the compliant approach.

> **Confidence tags.** `[CERTAIN]` = a well-established, long-standing term unlikely to have changed. `[INFER]` = my reading of the platform's typical posture; **verify against the live ToS/API terms before relying** — platform terms change often and my knowledge has a cutoff (Jan 2026). `[VERIFY]` = must be read against the current terms before the action.
> Not legal advice. Where a term is load-bearing for a channel, the Founder/a lawyer should confirm the current wording before that channel goes live.

## Summary of flags
- **Hard "manual only" lines:** LinkedIn (no scraping, no automation of member data/activity), Reddit (no automated posting without API compliance), HN (no automation/promotion at all). Our GTM already assumes manual posting on these — keep it that way.
- **API-governed, generally OK if we use the official API within quota:** Reddit API, X/Twitter API, Resend, job-source/ATS providers.
- **Biggest exposure:** LinkedIn (R-001) and any job-source whose terms forbid redistribution/caching of listings.

## Platform-by-platform

### Job sources / ATS (ingestion — the product's core input)
- **What our GTM does:** ingest live roles via ATS resolution + budgeted third-party job API (e.g. JSearch) + dedup; show full JDs; link out to apply.
- **Flags `[VERIFY per provider]`:** many job APIs/boards forbid (a) scraping outside the official API, (b) caching/redistributing listings beyond display, (c) stripping/altering the apply link or attribution. Some require showing the source and a working apply URL. Rate/quota caps apply.
- **Compliant approach:** use each provider's **official API within its quota and attribution rules**; link out to the original posting (never present ourselves as the application endpoint — reinforces C6 no auto-apply); don't redistribute raw listing dumps; keep a per-provider note of what its terms permit. No URL-scraping where it's dead/forbidden (careerjet URL-scraping already abandoned — product memory). **Verify each provider's terms individually before it becomes load-bearing** (ties to R-008). `[VERIFY]`

### LinkedIn (credibility page + Ettore's 1:1 DMs)
- **What our GTM does:** Company Page for posts/data drops; Ettore's personal account for 1:1 PMF DMs (10–15/day). No ingestion of LinkedIn data.
- **Flags `[CERTAIN]`:** LinkedIn's User Agreement and bot policy prohibit scraping, crawling, or automated collection of member data, automated/bulk messaging, fake profiles, and most automation tools. Connection/message automation is a common ban trigger and account-termination risk.
- **Compliant approach:** **manual posting and manual DMs only** — no automation tool, no bulk/templated-at-scale sending that looks automated, no scraping of profiles or search results. Keep DM volume human and personalised. Disclose the project per C1. Never feed LinkedIn data into the product. This is the sharpest ToS line we touch (R-001). `[CERTAIN]`

### Reddit (u/jbhntr disclosed participation)
- **What our GTM does:** disclosed participation, 20 min/day, answer-first link-second, 2 weeks karma first; drafts filed not posted (R1-09).
- **Flags `[CERTAIN/INFER]`:** Reddit's Content Policy + API Terms require that automated access use the official API under its terms; posting automation outside the API and spam/undisclosed promotion violate both sitewide rules and most subreddit rules. Each subreddit sets its own self-promo rule (often a 9:1 or 10% ratio). `[CERTAIN]` sitewide; `[VERIFY]` per subreddit.
- **Compliant approach:** **manual posting** (our drafts are filed for the Founder, not auto-posted — already compliant); obey each subreddit's self-promo ratio and link rules (C3); always disclose (C1); build karma first. If we ever automate reads, use the official Reddit API within its terms and rate limits.

### Hacker News (Show HN spike + participation)
- **What our GTM does:** one "Show HN" at the spike; organic participation.
- **Flags `[CERTAIN]`:** HN guidelines prohibit voting rings, astroturfing, undisclosed promotion, and any automation/bots; "Show HN" has specific rules (it must be something people can try). `[CERTAIN]`
- **Compliant approach:** **manual, genuine, no automation, no ask-for-upvotes, no sockpuppets** (C2); post Show HN only when the product is genuinely try-able and the spike criteria are met (≥4 wks interviews, top-3 complaints fixed, 100+ users). Disclose who we are.

### X / Bluesky / Threads (@jbhntr)
- **What our GTM does:** 3–5 posts/wk, data points, match cards, replies to job-search complaints.
- **Flags `[INFER]`:** X's Developer Agreement governs API use (posting via API within rate limits is allowed; bulk/spam automation and platform manipulation are banned). Bluesky (AT Protocol) and Threads are more permissive but still ban spam/inauthentic behaviour. `[INFER]` — verify X API tier terms if we automate posting.
- **Compliant approach:** manual or official-API posting within limits; no automated mass-replies; no engagement farming; disclose per C1. Posting via a scheduler using the official API is generally fine `[VERIFY]` against current X API terms if used.

### Resend (transactional + Sean-Ellis emails via HTTPS API)
- **What our GTM does:** day-14 Sean-Ellis email to active searchers; transactional email (email already live via Resend HTTPS API — product memory).
- **Flags `[INFER]`:** Resend's AUP requires a verified sending domain, permission-based sending (no purchased lists), honest headers, and working unsubscribe for non-transactional mail; anti-spam compliance (CAN-SPAM / GDPR / PECR) is on us. `[INFER]`
- **Compliant approach:** send only to users who gave us their email in-product (lawful basis + consent recorded); clear sender identity + physical address + unsubscribe on the Sean-Ellis/marketing email; keep transactional vs marketing separate; honour unsubscribes; verified domain + SPF/DKIM/DMARC. Signed DPA with Resend on file (R-004). `[VERIFY]` current AUP.

### Railway (hosting / deploy — product memory: prod on Railway from main)
- **Flags `[INFER]`:** standard PaaS ToS + AUP (no illegal content, resource-abuse limits); as a sub-processor of user PII, needs a DPA for GDPR. `[INFER]`
- **Compliant approach:** DPA with Railway on file before the Phase-2 cohort; note processing location (transfer mechanism if outside EEA — SCCs); secrets only in env (CHARTER G4). `[VERIFY]` DPA availability + region.

### Directories (GTM §6: AlternativeTo, TAAFT, Futurepedia, SaaSHub, G2, Capterra, BetaList, Uneed, Product Hunt "coming soon")
- **What our GTM does:** one 40-word description + match-card image per directory; honest listing.
- **Flags `[INFER]`:**
  - **G2 / Capterra `[INFER]`:** reviews must be genuine and non-incentivised unless the incentive is disclosed and the review is unbiased; **vendors must not write or solicit fake/gated reviews**. Both have strict review-integrity rules. `[VERIFY]` their current review policies before soliciting any review.
  - **Product Hunt `[CERTAIN posture]`:** bans vote manipulation and incentivised upvotes; a "coming soon" page is fine. Our posture (no fronting PH, no PH launch in Phase 1 — C9) keeps us clear. `[INFER]` current rules.
  - **AlternativeTo / TAAFT / Futurepedia / SaaSHub / BetaList / Uneed `[INFER]`:** self-submission is expected and allowed; just submit accurate info, one listing, no spam. Low risk.
- **Compliant approach:** submit accurate self-descriptions (C4/C7); **never buy, fake, gate, or incentivise reviews** on G2/Capterra (or disclose the incentive if one is ever offered — C8); one listing per directory, no duplicate/spam submissions; no vote manipulation anywhere. `[VERIFY]` G2/Capterra review policies before any review drive.

## Standing rule
Manual posting stays manual wherever automation is banned (LinkedIn, Reddit outside the API, HN). Before any channel is automated or any provider becomes load-bearing, read its **current** terms and update this doc. GC re-checks the high-exposure terms (LinkedIn, job sources, G2/Capterra) each month.

Skills used: legal:compliance-check, legal:legal-risk-assessment.
Skills considered but not used: legal:vendor-check (no specific vendor contract to run through the full vendor-check flow this cycle; revisit when the Resend/Railway DPAs are on the table).
