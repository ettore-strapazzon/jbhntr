# Decisions log — JBHNTR Team

Owner: CEO. Append-only; superseded rows kept and annotated inline.

| date | decision | proposed by | approved by |
|---|---|---|---|
| 2026-09-13 | Wedge = mid-senior professionals (5–15 yrs) in generalist functions; geography order UK+IE → EU → US → Canada; LinkedIn for 1:1 only from Ettore's own account; partnerships gated on ≥100 activated users; daily draft digest live | Founder | Founder |
| 2026-09-20 | Brand-led, not founder-led — credit in code/GitHub is fine, no Founder/CEO title on LinkedIn, no PR/marketing around the person; open-core split (source-available public shell + private engine); GitHub org `jbhntr` | Founder | Founder |
| 2026-10-25 | **JBHNTR Team stood up** — 6 agents (CEO/CTO/CMO/CPO/CFO/GC), 30-min heartbeat, max 10 cycles/day, 08:00 Rome morning update; same orchestration model as copytrade-co/Plainfleet (CEO session dispatches 5 foreground sub-agents) | CEO | Founder |
| 2026-10-25 | Goal = **1,000 activated users** (account + profile ≥70% + ≥1 search); budget **USD 1,000** lifetime; monetisation via paid credit top-ups after the gate holds + K≥0.3 | Founder | Founder |
| 2026-10-25 | Company layer lives **inside the job-hunter repo** under `company/` | Founder | Founder |
| 2026-10-25 | Run mechanism = **same as copytrade-co** (orchestration-by-convention; cycle prompt in `company/RUNBOOK.md`, fired by the Founder's scheduler or manually) | Founder | Founder |
| 2026-10-25 | **CTO + GC draft `REPO_SPLIT_EXECUTION_PLAN.md` early** (first Step-1 deliverable, R1-06) rather than assuming an existing plan; Founder approves before execution | Founder | Founder |
| 2026-10-26 | **R-001:** runner = same as copytrade-co; **auto-push: YES** (CEO may push product changes that are tested green). CEO still reviews every diff + runs the suite before pushing | Founder | Founder |
| 2026-10-26 | **R-002:** public licence = **BSL 1.1 → Apache-2.0 (+3yr)**. Confirmed on the basis that BSL does not restrict our own monetisation (credit purchases / premium / paid service) — it only blocks a competing hosted service; engine stays private | Founder | Founder |
| 2026-10-26 | **R-005:** no incorporation until revenue is needed (≈ before Phase-2 paid credits). Founder accepts the residual controller-liability + footer exposure during the public-beta spikes (GC to downgrade R-007 status to "accepted until revenue" in the risk register and keep /privacy, /terms, data-drop/Show-HN gated on a named controller) | Founder | Founder |
| 2026-10-26 | **R-008:** execute repo-split **steps 1–3** (in-repo façade + demo engine + boot guard + private-package carve) — CTO's call, following the GTM/plan. Steps 4–7 (public cut-over) return for a separate go; GitHub org creation (R-007) happens then | Founder | Founder |

## Open decisions (tracked as Founder requests in REQUESTS.md)
- Public licence: **BSL 1.1** (default) vs **Elastic 2.0** — decide before repo-split step 6 (→ R-002).
- Coach/partner economics when Step 4 starts: credits only (default) vs credits + a small cash bounty per activated client (→ R-003).
- Show HN timing: fixed to ~week 8 vs conditional on ≥70% positive interview verdicts (→ R-004).
- Incorporation vehicle + timing (before Phase 2 / before the spikes) (→ R-005).
