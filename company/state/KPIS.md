# KPIs — JBHNTR Team

Owner: CTO (data) / CFO (spend & revenue). **Real numbers only.** `—` = not measured yet, never a guess.
CTO populates `current` from the prod DB + ProductEvent table in cycle 1 and refreshes every cycle; the live view is the BI dashboard (R1-05).

| metric | target | current | as of | source |
|---|---|---|---|---|
| **Activated users** (acct + profile ≥70% + ≥1 search) | 1,000 by week ~13 | — | — | prod DB |
| Activation checkpoint | ≥100 (wk6) · ≥300 (wk9) · ≥600 (wk12) | — | — | prod DB |
| Signups (total accounts) | — | — | — | prod DB |
| Activation rate (signup→activated) | ≥55% | — | — | ProductEvent |
| Gate: "vs how you search today" | ≥60% better/much-better, ≥30% much-better, stable 4 wks | — | — | gate prompt |
| Sean Ellis (day-14 active) | ≥40% "very disappointed" | — | — | day-14 email |
| Return within 7 days (while active) | ≥50% | — | — | ProductEvent |
| Outcome events / active user / week | ≥5 | — | — | ProductEvent |
| K-factor | ≥0.3 by day 60 | — | — | referral data |
| Unprompted mentions | ≥3/week by day 90 | — | — | CMO log |
| Interview verdicts | ≥70% "wouldn't have found #1–3 myself" | — | — | interview notes |
| **Spend (USD)** | ≤ 1,000 lifetime | — | — | LEDGER.csv |
| Revenue (USD, paid credits) | — (Phase 2) | — | — | LEDGER.csv |
| Compute cost / active user | minimise | — | — | CFO model |
