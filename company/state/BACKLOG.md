# Backlog — JBHNTR Team

Owner: CEO. Newest sprint on top; older sprints marked superseded. Status: `todo | doing | done (cN)`.

## Sprint R3 — Step 1 visible artefacts + activation + repo split (next cycle)
| id | owner | task | acceptance criteria | deps | status |
|---|---|---|---|---|---|
| R3-01 | CTO+CPO | **Match card** build | Per ARTEFACTS_SPEC §8: lazy-mint `JobResult.share_token` on `POST /job/{id}/share`; `/m/{token}`; OG PNG (Playwright); Share button on job+tracker cards; emits `match_card_shared` + `shared_artifact_viewed`; referral embed | done R2-01 | **done (c3)** 606 green |
| R3-02 | CTO+CPO | **Market read** build | `Search.share_token`; `/r/{token}` v1 stage funnel; anonymise toggle; OG/PNG; emits `market_read_shared`+`shared_artifact_viewed` | R3-01 | todo |
| R3-03 | CTO+CPO | **/invite page** build | Code+link+per-channel messages+live counter; emits `invite_page_viewed`+`invite_link_copied` | R3-01 | todo |
| R3-04 | CPO+CTO | **Activation meter** (first A/B) | Completeness strip + "unlocks at 70%" CTA; **enable-state keyed to `can_search`, NOT `score≥70`** (ARTEFACTS_SPEC §8.4 + the fixture test); KPI = first-scan rate | done R2-01 | todo |
| R3-05 | CTO | **Repo-split steps 1–3** (R-008 approved) | In-repo `jbhntr_engine` façade (78 import sites) + demo engine + boot guard + private-package carve; tests green; steps 4–7 return for separate go | — | todo |
| R3-06 | CTO | **BI dashboard** | Read-only metrics on `/admin`: activated, funnel, activation rate, gate, K-factor, outcome/user, spend/revenue — now that R2-01 events exist | done R2-01 | todo |
| R3-07 | GC | **Clear COMPARE_COPY `[VERIFY]` cells** | Verify each competitor claim + ToS fact against live sources, date them; then R3-08 can wire the pages | — | todo |
| R3-08 | CMO+CTO | **Comparison pages** build | Wire `/compare/jobright|simplify|teal|auto-apply-tools` to `compare_linkedin_jobs.html` from COMPARE_COPY after R3-07 | R3-07 | todo |
| R3-09 | CTO | **Config cleanup** (CFO flag) | Reconcile legacy `plans`/`premium_*` display in `config.py` to the chosen Phase-2 pricing; wire packs/sub as credit grants (not doc-allowance). Low priority, pre-Phase-2 | — | backlog |

**Phase-2 backlog:** EU/UK 14-day right-of-withdrawal acknowledgement in the paid-credit purchase flow (GC/TERMS_DRAFT §5). Migration: swap `db.py` additive migrator → Alembic before more schema churn (CTO flag, ×2 cycles now).

## Sprint R2 — measurement foundation + strategy docs (CLOSED, cycle 2, 2026-10-26)
| id | owner | task | status |
|---|---|---|---|
| R2-01 | CTO | Measurement plumbing + share_token columns + /go redirect | **done (c2)** — 597 passed; pushed |
| R2-10 | GC | /terms draft + /privacy controller (R-005) + risk update | **done (c2)** |
| — | CFO | Phase-2 monetisation model (Plus $15/mo; packs $12/30/60; BE ≈12 subs) | **done (c2)** |
| R2-08 | CMO | Comparison-page copy (claims [VERIFY]) | **copy done (c2)** → build R3-08 |
| R2-09 | CMO | First daily draft digest (filed) | **done (c2)**; ongoing daily |
| R2-02/03/04/05 | CPO | Artefact + meter build plan (ARTEFACTS_SPEC §8) | **plan done (c2)** → build R3-01..04 |

## Sprint R1 — Step 1 foundations (CLOSED, cycle 1, 2026-10-25)
All 12 tasks closed — see cycle-1 CYCLE_LOG. Docs in `company/docs/`.
