# Backlog — JBHNTR Team

Owner: CEO. Newest sprint on top; older sprints marked superseded. Status: `todo | doing | done (cN)`.

## Sprint R2 — Step 1 build + measurement (next cycle)
| id | owner | task | acceptance criteria | deps | status |
|---|---|---|---|---|---|
| R2-01 | CTO | **Measurement plumbing** (was R1-04) | Add the 9 missing ProductEvents (CPO list) + `step_name`/`channel` to `ALLOWED_PROPS`; set `source` on `signup_completed`; UTM + `/go/{channel}` redirect; post-scan gate prompt | — | todo |
| R2-02 | CTO+CPO | **Match card** build | Per `ARTEFACTS_SPEC.md`: new random `JobResult.share_token`; `/m/{token}`; OG PNG via Playwright screenshot (cached); Share button on job + tracker cards; referral embed | R2-01 | todo |
| R2-03 | CTO+CPO | **Market read** build | New `Search.share_token`; `/r/{token}` v1 = existing stage funnel ("1,840 roles, 14 worth it"); anonymise toggle; OG/PNG; referral embed. (Reason histogram = v2 engine work) | R2-01 | todo |
| R2-04 | CTO+CPO | **/invite page** build | Code + link + per-channel messages + live counter (referral loop already wired) | R2-01 | todo |
| R2-05 | CPO | **Activation gate fix** (first test) | Live profile-completeness meter + "Run my free scan — unlocks at 70%" CTA in onboarding; KPI = first-scan rate; A/B where traffic allows | R2-01 | todo |
| R2-06 | CTO | **BI dashboard** (was R1-05) | Read-only metrics view extending `/admin`: activated users, funnel, activation rate, gate by cohort, K-factor, outcome events/user, spend vs revenue, compute cost/user | R2-01 | todo |
| R2-07 | CTO | **Repo-split steps 1–3** | In-repo `jbhntr_engine` façade (funnel the 78 import sites) + demo engine + boot guard + private-package carve; tests green; steps 4–7 (public cut-over) return for separate go | R-007,R-008 | blocked (Founder) |
| R2-08 | CMO+CTO | **Comparison pages** build | Wire `/compare/jobright`, `/simplify`, `/teal`, `/auto-apply-tools` to the `compare_linkedin_jobs` template from CMO outlines (after GC clears VERIFY cells) | R2-02 | todo |
| R2-09 | CMO+GC | **Daily draft digest** (was R1-09) | Spec + first run: 6–10 thread replies + layoff watch + 1 X post + compare drafts, all filed not posted; GC clears claims | — | todo |
| R2-10 | GC | **/terms draft** | Full terms (liability, AUP, no-auto-apply clause) + finalise /privacy controller paragraph | R-010 | todo |

## Sprint R1 — Step 1 foundations (CLOSED, cycle 1, 2026-10-25)
| id | owner | task | status |
|---|---|---|---|
| R1-01/02/03 | CPO | Artefact specs (match card / market read / invite) | spec done (c1) → build R2-02/03/04 |
| R1-04 | CTO | Measurement plumbing | scoped (c1) → R2-01 |
| R1-05 | CTO | BI dashboard | scoped (c1) → R2-06 |
| R1-06 | CTO+GC | Repo-split execution plan + licence rec (BSL 1.1) | **plan done (c1)**; exec = R2-07 pending R-007/008 |
| R1-07 | CMO | Brand-accounts setup pack | **done (c1)**; creation = R-009 |
| R1-08 | CMO | Directories + comparison outlines | **drafts done (c1)**; build R2-08 |
| R1-09 | CMO+GC | Daily draft digest | → R2-09 |
| R1-10 | CFO | Budget + break-even (≈15 paying users/mo) | **done (c1)** |
| R1-11 | GC | Compliance card + risk register + ToS + privacy | **done (c1)** |
| R1-12 | CEO | ONE_PAGER, TIMELINE, KPI_TRACKER, GTM, COMPETITOR_MAP | **done (c1)** |
