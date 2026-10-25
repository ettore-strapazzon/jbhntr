# BUDGET & Unit Economics — JBHNTR

Owner: CFO · v1 (2026-10-25) · Currency: USD · Budget: **1,000 lifetime, hard cap**
Status: model built from the product's real credit config (`web/app/config.py`) + measured LLM rates. Dollar figures marked **[CONFIRM]** are estimates pending a real bill from Founder/CTO — see §6. No `LEDGER.csv`/`KPIS.md` rows are written with estimates; §7 describes the rows to add once confirmed.

---

## 1. Budget allocation (USD 1,000 lifetime)

Principle (Charter): data/analytics + organic growth first; paid only with a benchmark and Founder approval. So the bulk of the budget is **variable compute to serve 1,000 activated users**, not paid acquisition.

| # | Function | Allocation | Cap (hard) | Kill rule |
|---|---|---|---|---|
| 1 | **LLM + embeddings compute** (scoring, CV/CL, profile parse) | **$500** | $600 | If blended spend >$0.80/activated user for a full week → cut `CORPUS_TOPK` 60→40, drop CV/CL panel to single-model, throttle earn cap. |
| 2 | **Infra above free tier** (Railway app + Postgres) | **$200** | $300 | If Railway >$25/mo → move Postgres to a free/cheaper tier or downsize dynos before paying more. |
| 3 | **Domain + email** (jbhntr.app renewal, Resend) | **$80** | $120 | Stay on Resend free tier (3k/mo) until email volume forces paid; then re-price. |
| 4 | **Directories / listings that cost** | **$40** | $60 | Only paid listings with a tracked `/go/{channel}` and a Founder `R-###`. Free directories first. |
| 5 | **Paid-growth test reserve** | **$100** | $150 | One small benchmarked test only, after organic + referral are live and K is measured. No test without a prior CAC benchmark and Founder approval. |
| 6 | **Contingency / trademark-incorporation buffer** | **$80** | — | Legal/incorporation is a GC/Founder line (GTM §7: incorporate before Phase 2); sized here as a placeholder, real quote pending. |
| | **Total** | **$1,000** | | Lifetime cap is absolute: no dollar without a `LEDGER.csv` line **and** a Founder `R-###`. |

**Global kill rule:** at **$800 cumulative actual spend**, freeze all non-essential spend and re-plan; the only lines that keep running are infra + compute needed to keep the live product up.

---

## 2. Unit economics — the inputs (all real, from the product)

**Credit config** (`web/app/config.py`, Guide v3.0):

| Lever | Value | | Earn lever | Value |
|---|---|---|---|---|
| Signup grant | 10 credits | | Referral (inviter) | 15 cr |
| First scan | **free** (no credit) | | Referral (friend) | 5 cr |
| Scan | 2 cr | | Outcome report | 2–3 cr |
| CV draft | 3 cr | | Product feedback | 3 cr |
| Cover letter | 3 cr | | **Weekly earn cap** | **30 cr** |
| Bundle (CV+CL+scan) | 5 cr | | Low-balance warn | 4 cr |
| External import | 1 cr | | | |
| Regenerate | 1 cr | | | |

**Compute mechanics** (measured):
- **Scan:** up to `CORPUS_TOPK`=60 geo-matched jobs scored, one independent LLM call each, model `claude-haiku-4.5`. Shared candidate/profile context is a **prompt-cached system prompt** reused across all 60 jobs; only the per-job JD (capped 3,000 chars) varies; output capped 600 tokens. Enrichment, link-check, geo backfill are **HTTP-only (no LLM $)**. A `score_cache` reuses identical job-scores across overlapping/repeat searches; an identical re-run within 24h is free.
- **Haiku-4.5 rate** (measured via cost tool): ~$0.83/M input, ~$4.2/M output.
- **CV / cover letter:** multi-model **panel** (`claude-3.7-sonnet` + `gpt-4o` + `gemini-2.0-flash`) — each drafts, critiques, revises, votes; a synthesiser merges (~10–13 calls over a CV-length doc). This is the single most expensive user action.

---

## 3. Unit economics — derived costs

### Per action (base estimate)
| Action | Credits | Compute cost (base) | $/credit |
|---|---|---|---|
| Scan (60 jobs) | 2 | **~$0.13** (≈$0.11 scoring w/ cache + ~$0.02 profile/criteria derivation) | ~$0.065 |
| CV draft (panel) | 3 | **~$0.20** [CONFIRM] | ~$0.067 |
| Cover letter (panel) | 3 | **~$0.20** [CONFIRM] | ~$0.067 |
| Embeddings (per scan) | — | negligible (<$0.001) | — |

→ **Blended compute ≈ $0.07 / credit** (range $0.04 warm-cache / short outputs … $0.11 cold-cache / 600-tok outputs / all-fresh).

### Per activated user
*Activated = account + profile ≥70% + ≥1 search (the free first scan).*
- To reach activation: CV parse + criteria/company derivation (~$0.02) + free first scan (~$0.13) ≈ **$0.15**.
- Plus the share of the **10-credit signup grant** (and, for referred users, the 15+5 referral grant) that actually gets redeemed over the user's life.

| Scenario | Assumptions | **Compute / activated user** |
|---|---|---|
| **Upside (lean)** | Activates, little further use; most granted credits unredeemed; warm cache | **~$0.20** |
| **Base** | First scan + profile + ~5 further credits redeemed (scans/imports) | **~$0.50** |
| **Downside (heavy/referral)** | Redeems all 10 signup + 20 referral credits, several on panel CVs; cold cache | **~$1.20** |

This base/downside range reconciles with the GTM/CFO figure of **~$0.30–1.00 per referral activation** (the compute the granted referral credits represent when redeemed).

---

## 4. The $1,000 budget vs the 1,000-user goal

| Scenario | Compute/user | Compute for 1,000 activated | Headroom for infra + domain + growth test |
|---|---|---|---|
| Upside | $0.20 | $200 | ~$800 |
| **Base** | **$0.50** | **$500** | **~$500** |
| Downside | $1.20 | $1,200 | **−$200 → OVER CAP** |

**Reading:** at base, serving the full 1,000-user target costs ~half the budget — comfortable. The downside blows the cap, which is **why the credit guardrails exist** (signup grant 10, weekly earn cap 30) and why the §1 kill rules must fire on cost-per-user, not just total spend. The swing variable is how many granted/earned credits get redeemed on the expensive panel CV/CL path.

---

## 5. Phase-2 break-even & path to profitability

Phase 2 (paid credit top-ups) unlocks only when the PMF gate holds (≥60% "better") **and** K ≥ 0.3. The number the Founder needs to decide with:

**Proposed price (pricing skill — value-based, "prosumer ~$10" bucket, avoid the $9 trap):**
- **$12 for 60 credits ($0.20/credit)**, or a $12/mo subscription granting 60 credits. Anchored below Teal/Jobright (~$20–30/mo), above our ~$0.07/cr cost → ~65–70% gross margin/credit. *This is a bet to learn from, not a final price — ship it and watch conversion.*

**Contribution per paying user / month (base):**
- Consumes ~40 cr/mo → compute $0.07×40 = **$2.80**.
- Revenue $12 − payment fees (~3.5% + $0.35 ≈ $0.77) = **$11.23 net**.
- **Contribution = $11.23 − $2.80 ≈ $8.4 / paying user / month.**

**Monthly fixed opex (base) [CONFIRM infra]:**
- Infra (Railway + Postgres): **~$25/mo** [CONFIRM]
- Domain amortized + Resend: **~$2/mo** (Resend free <3k emails)
- **Free-tier compute burn** (non-payers): ~250 monthly-active non-payers × ~5 cr/mo × $0.07 ≈ **~$88/mo**
- **Total ≈ $115/mo** (base); downside ~$200/mo if free burn + infra run hot.

**► BREAK-EVEN HEADLINE: ~15 paying users/month** covers all monthly costs at base assumptions ($12 ARPU, $8.4 contribution, ~$115/mo opex). At 1,000 activated that is **1.5% paid conversion** — well within reach. Downside break-even ~**35 paying users** ($200/mo opex, $5.7 contribution).

**Path to profitability (plain numbers, base):**
| Paying users/mo | Net contribution/mo | Monthly P&L (after ~$115 opex) |
|---|---|---|
| 15 | $126 | **~$0 (break-even)** |
| 30 (3% of 1,000) | $252 | **+$137/mo** |
| 50 (5%) | $420 | **+$305/mo** |
| 150 (15%) | $1,260 | **+$1,145/mo** |

So the free-tier burn is the real cost to watch (see `QUOTAS.md`), and **every paying user above ~15/mo is ~$8/mo of profit**. Free-tier burn — not infra — is the variable that decides whether break-even is 15 or 35 users.

---

## 6. Unknown costs to confirm (REQUEST: to Founder/CTO)

Do **not** guess these — each becomes a `pending-founder` ledger row once confirmed:
1. **Railway** — current monthly bill (app compute + Postgres plan). The single biggest unknown in the opex model.
2. **jbhntr.app domain** — annual renewal cost + registrar.
3. **Actual LLM spend** — from the OpenRouter dashboard: real $/scan and $/CV-CL, to validate the $0.13/scan and $0.20/doc estimates. Pull last 30 days / divide by scan & doc counts.
4. **Embeddings** — which provider/model and its rate (OpenRouter vs OpenAI).
5. **Resend** — current plan and monthly email volume vs the 3,000/mo free cap.
6. **Job-source API budgets** — JSearch/RapidAPI monthly quota & cost, plus any Adzuna/careerjet paid usage.
7. **Trademark / incorporation** — quote (GC/Founder line; GTM §7 requires incorporation before Phase 2).

---

## 7. Proposed LEDGER rows (describe only — not written; values pending confirmation)

Once each cost in §6 is confirmed, add to `LEDGER.csv` (one `R-###` per spend). Proposed rows, all `approved_by = pending-founder` until the Founder issues an `R-###`:

```
<date>,CTO,Railway hosting (app+Postgres),Railway,committed,<TBD>,pending-founder,monthly recurring; confirm current bill
<date>,CTO,jbhntr.app domain renewal,<registrar>,committed,<TBD>,pending-founder,annual; FX if non-USD
<date>,CTO,LLM API (OpenRouter) scoring+panel,OpenRouter,actual,<TBD>,pending-founder,backfill last 30d actual from dashboard
<date>,CTO,Email,Resend,committed,0,pending-founder,free tier <3k/mo; row at $0 until paid
<date>,CTO,Job-source API,JSearch/RapidAPI,committed,<TBD>,pending-founder,monthly quota; confirm plan
<date>,GC,Trademark/incorporation,<provider>,committed,<TBD>,pending-founder,GTM §7 pre-Phase-2
```

`KPIS.md` rows **Spend (USD)** and **Compute cost / active user** stay `—` until real actuals exist — no estimates in state files.

---

Skills used: pricing (value-based price point, $10-bucket / avoid-$9-trap, credit-model pricing), cost-guardian:cost-estimate (real Haiku-4.5 / Sonnet / gpt-4o token rates to ground per-scan & panel compute).
Skills considered but not used: finance:financial-statements & finance:variance-analysis (no actuals/GL yet — LEDGER is empty; applies once real rows land), statistical-analysis & data:statistical-analysis (scenarios are deterministic sensitivity, not inference over a dataset — no data to analyze yet), cost-guardian:cost-report (no tracked historical spend to report on yet).
