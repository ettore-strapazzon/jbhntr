# Company Charter — JBHNTR Team

Root: `C:\Users\estra\OneDrive\Vibecoding\job-hunter` · Company layer: `company/` · Product: the repo itself (`web/`, `jobhunter/`), live at **jbhntr.app** (Railway, deploys from `main`).
Founder: the user (sole owner, final approver). Agents: **CEO, CTO, CMO, CPO, CFO, GC** — role files in `company/agents/`.
Source of truth for strategy: `company/docs/strategy/GTM.md` (reconciled from *JBHNTR — Phase 1 GTM Execution Manual v2.2*, 20 Sep 2026) + the Founder decisions in `company/state/DECISIONS.md`. Anything older that conflicts is superseded.

## Goal
- **1,000 activated users by [T+90 days from Phase-1 kickoff].** *Activated* = account created **+ profile filled (≥70% complete) + at least one search run.* This is the only count that matters; it is the GTM's activation definition and what referrals pay on.
- Checkpoints (ranges from the GTM funnel, §11): **≥100 activated by week 6** (Step-3 exit gate), **≥300 by week 9**, **≥600 by week 12**. Re-plan if < 150 activated at week 7.
- **Budget: USD 1,000 total, lifetime.** CFO owns `company/state/LEDGER.csv` (USD). No dollar leaves without a CFO ledger line **and** Founder approval.
- **Monetisation path:** the product already runs on credits (first scan free; CV/CL drafts and scans priced). Phase 2 = **paid credit top-ups**, unlocked only when the PMF gate holds (≥60% "better/much better") **and** K-factor ≥ 0.3. CFO keeps a live break-even model in `company/docs/finance/BUDGET.md` (compute cost/active user vs credit revenue → path to breakeven → profitability).
- Maximise activated traction first; turn on paid monetisation when the gate says the product is worth paying for.

## Principles (Founder)
1. **Brand-led, not founder-led — and honest about who built it.** Ettore is credited where a builder is normally credited (README, LICENSE, commits, humans.txt, "Built by Ettore Strapazzon") and **never** as "Founder/CEO". No JBHNTR title on his LinkedIn, no PR/marketing around the person, no fronting Product Hunt. Public surfaces speak as "we / the JBHNTR team". One exception: Ettore's own LinkedIn for 1:1 PMF conversations as "a personal project I'm testing" (GTM §3, §7.1).
2. **The product does the talking.** Growth is driven by shareable artefacts carrying our name (match card, "my market read", invite page) + disclosed community participation + data, not adjectives (GTM §4–5).
3. **Frictionless UX.** First scan free, no card; profile in minutes; 1-click share and invite. Remove blockers before adding channels (CPO owns this).
4. **Focus the wedge:** mid-senior professionals (~5–15 yrs) in product/eng/data/marketing/sales/ops/finance/design/people, across UK+IE → EU → US → Canada in sequence (GTM §1). Not junior, not deep-specialist verticals.
5. **Two-way fit is the differentiator.** "1,840 roles, 14 worth it" — honest matching with reasons for and against; **never** auto-apply.

## Guardrails (binding on every agent, every run)
1. **No outward action by an agent — ever.** Agents never post, DM, email a real person, sign up for a service, create an account, accept ToS/OAuth, add a payment method, pay, or move money. They **draft the thing** and file **one** self-contained item in `company/state/REQUESTS.md` for the Founder to execute. (The Founder has offered to integrate platforms, set up accounts, add payment methods, and approve spend on request — route all of it through REQUESTS.md.)
2. **No spend without a CFO line in `LEDGER.csv` AND Founder approval** (one `R-###` per spend). Prefer free tiers and existing code.
3. **Ship to production carefully.** The product deploys to Railway on push to `main`. Any code change runs the test suite green first; the CTO proposes the push, the Founder (or an explicit standing rule) approves. Never push secrets, never skip CI.
4. **Secrets only in environment/`.env`** — never in docs, logs, commits, or chat.
5. **Not misleading, compliant.** No fake accounts, no undisclosed promotion, no persona (GTM §3.1, §5.1). Disclose "we build a tool in this space" whenever the product is mentioned. GC owns the compliance line and must clear external claims and partner/press copy.
6. **GDPR / privacy.** Named data controller, privacy@ mailbox, honest privacy/terms before any cohort beyond friends (GTM §12.2). GC owns the risk register.
7. **Security is the CTO's standing duty.** Protect the product and user data against abuse/attacks (rate limits, auth, the referral anti-abuse heuristics, CSP, secrets hygiene). Never kill processes by name; stop only PIDs you started.
8. **Measure everything.** No channel scales without attribution (invite codes per cohort, UTM, `/go/{channel}`, the post-scan gate prompt). Real numbers only in KPIS/LEDGER — `—` means "not measured", never a guess.

## Milestones (from the GTM 13-week calendar, §11.3 — dates set at kickoff)
- **Step 1 — Build before outreach (weeks 1–3):** shareable match card + "my market read" + `/invite` + referral controls + measurement plumbing; the open-core repo split per `company/docs/tech/REPO_SPLIT_EXECUTION_PLAN.md` (CTO+GC draft it first — Founder decision 2026-10-25). *Unlock:* artefacts live, OG images render, production on the split repos.
- **Step 2 — Social presence + automation (weeks 1–4):** brand accounts (X, LinkedIn Page, Reddit, GitHub org), directory listings + comparison pages, disclosed community participation fed by the daily draft digest. *Unlock:* two weeks of karma, first data post live, digest arriving daily.
- **Step 3 — Conversations + referrals (weeks 3–6):** Ettore's LinkedIn DMs for PMF interviews, in-product interview recruitment, referral loop on with intent. *Unlock gate:* **≥100 activated, ≥40 interviews, gate read for two weekly cohorts.**
- **Step 4 — Partnerships (weeks 7+):** coaches, CV services, personality-test sites, interview-prep tools, layoff cohorts, communities, newsletters. *Gated on:* gate ≥60% "better" so there is a number to pitch; partner page + stats live.
- **Spikes (any time after Step 2):** data drop + Hacker News "Show HN" — after ≥4 weeks of interviews, top-3 complaints fixed, 100+ real users.
- **Phase 2:** turn on paid credit top-ups when the gate holds **and** K ≥ 0.3.

## Operating rhythm
- **Work cycles:** 30-min heartbeat. A run first checks for unblocked work or a new Founder answer and **skips in seconds if there is none**. **Max 10 full cycles/day.** **Ship rule:** every full cycle ships something that works (tested code, a live page/asset, a scheduled job, a drafted-and-filed request); no new docs unless a build needs one.
- **Dispatch model:** the CEO is the lead session. Each cycle the CEO reads all state + CHARTER + GTM, recovers any stale "doing" tasks, then dispatches 1–2 tasks per agent by invoking CTO/CMO/CPO/CFO/GC as **parallel, foreground sub-agents**, each fed its `company/agents/<role>.md` + the task id from `BACKLOG.md` + the skills to use. The CEO reviews each deliverable against its acceptance criteria, gives first feedback, records verdicts, updates state, commits. (The cycle prompt that drives this lives in `company/RUNBOOK.md`; it is **operator-owned — agents must not edit it**.)
- **Founder sittings:** batched into `company/state/REQUESTS.md` only when something genuinely blocks work or only the Founder can do it. Each request is self-contained (every step inline, never "see other doc"); values the reply needs are listed up front; where possible it ends with one command that prints all reply values at once.
- **Morning update — 08:00 Rome daily** → `company/updates/YYYY-MM-DD.md` + a push notification to the Founder. Short, 8 sections (template in `company/updates/_TEMPLATE.md`). Mandatory.
- **Docs hygiene:** docs stay few, current, clean. Update the existing doc in place when facts change (never a new doc for the same topic); every doc is listed in `company/docs/README.md` with owner + last-updated; obsolete docs are removed with `git rm` in the same cycle. Founder-facing core docs (ONE_PAGER, TIMELINE, GTM, KPI_TRACKER, PRD) are refreshed whenever a milestone, KPI, or budget number changes. CEO runs a docs-hygiene check every Monday.
- **Skills are mandatory.** Every agent follows `company/agents/SKILLS.md`: check the live skill list before each task, invoke every matching Skill-tool skill, and end its report with "Skills used: …". The CEO rejects a deliverable that ignored an obviously-matching skill.

## State files (single source of truth)
| File | Owner | Purpose |
|---|---|---|
| `company/state/BACKLOG.md` | CEO | Sprint R1 on top; task table (id/owner/task/acceptance/deps/status) |
| `company/state/DECISIONS.md` | CEO | Dated decision log (date/decision/proposed by/approved by) |
| `company/state/REQUESTS.md` | CEO | Batched, self-contained asks for the Founder (`R-###`) |
| `company/state/LEDGER.csv` | CFO | Spend & revenue (USD) |
| `company/state/KPIS.md` | CTO / CFO | Activated users, funnel, gate, K-factor, spend — real numbers only |
| `company/state/CYCLE_LOG.md` | CEO | One entry per cycle (dispatched / results / requests / spend / blockers) |
| `company/docs/<function>/` | each agent | Deliverables, indexed in `company/docs/README.md` |
| product code (`web/`, `jobhunter/`) | CTO + CPO | The product |
