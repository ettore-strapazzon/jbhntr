# Compliance Card — JBHNTR

Owner: GC · v1 (2026-10-25) · **The company lints every outbound surface against this card.** Each rule is checkable: a human (or a lint pass) can look at an artefact and answer yes/no. A "no" blocks the surface until fixed. GC clears the exceptions.

> Not legal advice. These are the company's self-imposed honesty rules, tightened to the GTM posture (CHARTER Guardrail 5, GTM §2, §5.1, §7). A one-hour session with an Italian lawyer before public launch is still worth it.

## The rules (lint checklist)

| # | Rule | Check (pass = yes) | Applies to |
|---|---|---|---|
| C1 | **Disclose we build the tool.** Any public mention of the product/space discloses that we build a tool in it — the "who are you?" paragraph (GTM §2) or an inline "(disclosure: I work on JBHNTR)". | Does every post/comment/reply/bio that names the product or the job-search space carry a disclosure? | Reddit, HN, X, LinkedIn, comments, DMs, bios, FAQ |
| C2 | **No fake accounts or personas.** Every account is a real, disclosed brand or person account. No sockpuppets, no invented team members, no fake reviewers, no fake "I'm just a user who found this" posts. | Is every account traceable to the brand or to Ettore, and never posing as an unaffiliated third party? | all channels, reviews, directories |
| C3 | **Respect each community's promo rules.** Before posting to a community, read its self-promotion rule; post only within it. Where a community bans links/promo, participate without the link (answer first, link only if the rule allows). Where automation is banned, post manually. | Is there a per-community rule-check line on the draft, and does the draft obey it? | Reddit, HN, forums, Slack/Discord communities |
| C4 | **Honest comparison tables.** Every row is a real, current, verifiable fact about the named competitor. No cherry-picked framing that misstates what they do; if they do a thing, the table says so. We can be favourable; we cannot be false. | Can each cell be sourced to the competitor's live product/site as of the stated date? Is the "last checked" date on the page? | /compare/* pages, ads, decks |
| C5 | **"Source-available", never "open-source (OSI)".** The public repo is described as "source-available" under BSL 1.1 / Elastic 2.0. Never call it "open source" unqualified, never imply an OSI-approved licence. Existing MIT-licensed public code stays MIT to whoever already has it; the new licence applies from the split forward. | Does every description of the licence say "source-available", not "open source"? | README, LICENSE, site, posts, directories |
| C6 | **Never imply auto-apply.** We score and shortlist with reasons for/against; the user applies. No copy, screenshot, or feature name may state or imply we apply to jobs for the user. "Two-way fit", "shortlist", "worth pursuing" — never "we apply", "auto-apply", "applies for you". | Does the surface avoid any claim or implication that the product submits applications? | product UI, landing, ads, /compare/auto-apply-tools, posts |
| C7 | **Numbers must be real and sourced.** Every statistic (activation %, "71% say better", user counts, "1,840 roles, 14 worth it") is a measured number with a source/date behind it. `—` means not measured; never a guess, never a rounded-up projection stated as fact. Cumulative vs current is stated honestly (e.g. "currently active", not total signups). | Can each number be traced to KPIS.md / a query / a dated study? Is any forecast labelled as a forecast, not a fact? | all external claims, press, partner copy, ads, data drops |
| C8 | **No undisclosed incentive.** If a share/review/referral earns the sharer credits or money, that incentive is disclosed where required (reviews, testimonials, endorsements). Referral mechanics are disclosed on the /invite surface. | Is any incentivised endorsement/review/testimonial disclosed as incentivised? | referrals, reviews, testimonials, influencer/partner posts |
| C9 | **Brand-led, not founder-led.** Ettore is credited only as a builder (README/LICENSE/commits/humans.txt, "Built by Ettore Strapazzon"), never titled "Founder/CEO"; no PR around the person; no fronting Product Hunt. Exception: Ettore's own LinkedIn for 1:1 PMF chats as "a personal project I'm testing". | Does the surface avoid giving Ettore a company title or building PR around the person? | all public surfaces, PH, press |
| C10 | **Privacy promises are kept.** We don't claim a privacy/security posture we haven't implemented. "Anonymised" share actually strips the identifying fields; "we don't sell your data" is true; named controller + privacy@ live before any cohort beyond friends. | Does every privacy/security claim match what the product actually does today? | product, privacy/terms, security copy, ads |

## How to use it
- **CMO/CPO:** self-lint every draft against C1–C10 before filing it for the Founder. Put a one-line `rule-check:` on each digest draft (R1-09 already requires this).
- **GC:** clears edge cases and any surface that can't cleanly answer "yes". Blocks (doesn't soften) a "no"; states what would unblock it.
- **Review cadence:** GC re-reads this card every Monday against new surfaces; updates in place when a rule proves too weak or a community's rule changes.

Skills used: legal:compliance-check, product-legal:marketing-claims-review.
