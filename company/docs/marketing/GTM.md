# GTM strategy — JBHNTR Phase 1

Owner: CEO + CMO · v1 (2026-10-25) · Source of detail: *JBHNTR — Phase 1 GTM Execution Manual v2.2* (20 Sep 2026); this is the working condensation — agents keep it current, the manual is the reference.

## One paragraph
JBHNTR scans every live role for a mid-senior professional and returns the 10–20 worth pursuing, with a two-way fit score and reasons for and against — never auto-apply. Growth is **brand-led, not founder-led**: the product does the talking through shareable artefacts, disclosed community participation, data, and referrals. Goal: 1,000 activated users in ~13 weeks on ≤ USD 1,000, then paid credits once the product proves it beats how people search today.

## 1. Target
Mid-senior professionals, ~5–15 yrs, in generalist functions (product, eng incl. management, data, marketing/growth, sales, ops/strategy, finance/BizOps, design, people). **Not** junior/entry, **not** deep-specialist verticals (clinical, legal, academic, trades). Geographies all open day one; community/partner effort concentrated in sequence, 2–3 weeks each: **UK+IE → EU remote hubs → US → Canada**.

## 2. Posture (binding)
Brand-led, honest about who built it. Ettore credited in code/GitHub ("Built by Ettore Strapazzon"), never "Founder/CEO"; no JBHNTR title on his LinkedIn, no PR around the person, no fronting Product Hunt. Plural brand voice ("we / the JBHNTR team"); "a small, founder-led project", never a fake team. One exception: Ettore's own LinkedIn for 1:1 PMF conversations. The "who are you?" paragraph (manual §3.4) goes in every bio/FAQ/thread.

## 3. The order of operations (decided — each unlocks the next)
1. **Build before outreach** — shareable match card, "my market read", `/invite`, referral controls, measurement plumbing; open-core repo split. *Unlock:* artefacts live, OG images render, production on split repos.
2. **Social presence + automation** — brand accounts, directories + comparison pages, disclosed community participation fed by the daily draft digest. *Unlock:* 2 weeks karma, first data post, digest daily.
3. **Conversations + referrals** — Ettore's LinkedIn DMs for PMF interviews, in-product interview recruitment, referral loop on. *Unlock gate:* ≥100 activated, ≥40 interviews, gate read 2 cohorts.
4. **Partnerships** (after ≥100 activated) — coaches/CV writers, layoff cohorts/outplacement, personality-test sites, interview-prep tools, communities/newsletters, relocation/visa. *Gated on:* gate ≥60% "better".
- **Spikes (after Step 2):** data drop ("JBHNTR Research") + Show HN — after ≥4 wks interviews, top-3 complaints fixed, 100+ users.

*Why partnerships wait:* a partner sends their audience once; the first 50 must hit a product with social proof, a real tracker, and a tested referral flow, plus a stat ("71% say the shortlist beats their current process").

## 4. Channels
| Channel | Role | Cadence |
|---|---|---|
| Shareable artefacts (match card, market read, /invite) | the growth loop — every share embeds a referral code | always |
| Reddit (u/jbhntr) | disclosed participation; answer first, link second; 2 wks karma first | 20 min/day |
| X / Bluesky / Threads (@jbhntr) | data points, match cards, replies to job-search complaints | 3–5/wk |
| LinkedIn Company Page | credibility, data drops, partner posts | 2–3/wk |
| Directories | permanent long-tail ("Jobright alternative") | one afternoon |
| Comparison pages | `/compare/jobright`, `/simplify`, `/teal`, `/auto-apply-tools` (honest tables) | as drafted |
| Ettore's LinkedIn (1:1) | PMF interviews (8–20 signups/mo; value = 80+ interviews) | 10–15 msg/day |
| Data drop + Show HN | spikes | once each |
| Partnerships | coaches/cohorts/tools/newsletters | week 7+ |
Not in Phase 1: TikTok/IG/YouTube, full Product Hunt launch, our own Discord.

## 5. Referral policy (manual §4.4)
Uncapped earning (the loop), abuse-controlled: delayed payout (48–72h + first triage action), duplicate check (CV-embedding/device/IP/disposable-email → hold), soft ceiling with human unlock (25/mo then convert super-referrers to partners), non-transferable, leaderboard not cap. No hard caps, no signup CAPTCHAs.

## 6. Funnel & metrics (ranges, not forecasts)
90-day direct: ~455–1,270 activated; +135–380 from referral at K=0.3 → **~590–1,650 activated**. Targets: activation ≥55%, gate ≥60% better, Sean Ellis ≥40%, K ≥0.3 by day 60, ≥3 unprompted mentions/wk by day 90, interview verdicts ≥70%. Full table in `../strategy/KPI_TRACKER.md`. Gate holds + K≥0.3 → Phase 2.

## 7. Open-core & legal (manual §12)
Public `jbhntr/jbhntr` shell + demo engine under a source-available licence (BSL 1.1 default / Elastic 2.0); private `jbhntr/jbhntr-engine` (sources, prompts, ingestion, dedup, referral anti-abuse, corpus). Prod installs the engine at build time with a read-only token, refuses to boot on silent demo fallback. GDPR: named controller + privacy@ before any cohort beyond friends; incorporate before Phase 2 / the spikes. Not legal advice — an Italian-lawyer session before public launch. Plan: `../tech/REPO_SPLIT_EXECUTION_PLAN.md` (R1-06).
