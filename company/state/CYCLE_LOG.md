# Cycle log — JBHNTR Team

Newest last. One `##` entry per cycle. Sub-bullets: **Recovery / Dispatched / Results / Requests opened / Blockers / Spend**.

## 2026-10-25 · cycle 1 (company founding)
- **Recovery:** none (first cycle).
- **Dispatched (foreground, parallel):** CTO (R1-06 repo-split plan + ARCHITECTURE) · GC (R1-11 compliance/risk/ToS/privacy) · CFO (R1-10 budget + break-even) · CMO (R1-07 brand accounts + R1-08 directories/comparisons) · CPO (R1-01/02/03 artefact specs + funnel review). CEO (R1-12 ONE_PAGER + COMPETITOR_MAP).
- **Results (all accepted against acceptance criteria):**
  - CEO → `strategy/ONE_PAGER.md`, `strategy/COMPETITOR_MAP.md`.
  - CTO → `tech/REPO_SPLIT_EXECUTION_PLAN.md` (public shell vs private engine; 78 import sites → `jbhntr_engine` façade; boot guard reuses the existing lifespan hard-fail; BSL 1.1 rec; step order 1–7; risks+rollback) + `tech/ARCHITECTURE.md`. Found: referral anti-abuse heuristics not built yet.
  - GC → `legal/COMPLIANCE_CARD.md` (C1–C10), `RISK_REGISTER.md` (1 RED = incorporation gap), `THIRD_PARTY_TERMS.md` (LinkedIn/Reddit/HN = manual only), `PRIVACY_TERMS_NOTES.md`, `LICENCE_RECOMMENDATION.md` (BSL 1.1, concurs with CTO).
  - CFO → `finance/BUDGET.md` (**break-even ≈15 paying users/mo**; compute ~$0.50/activated user; $1k allocation + kill rules), `finance/QUOTAS.md`. Grounded in real `config.py` credit costs.
  - CMO → `marketing/BRAND_ACCOUNTS.md` (8-step creation pack), `marketing/DIRECTORIES_AND_COMPARISONS.md` (40-word desc, directory list, 4 compare-page outlines).
  - CPO → `product/ARTEFACTS_SPEC.md` (build-ready; needs new `share_token` on JobResult+Search; market-read histogram = v2 engine work; OG via Playwright). **Biggest activation gap: signup → profile ≥70%** (gate invisible until hit).
- **Review notes:** no code shipped (per plan); all outward actions filed as requests, not executed. Concurrent README edits coexisted (line-level, no clobber). Sprint R2 opened with the build tasks.
- **Requests opened:** R-006 (confirm 7 costs), R-007 (GitHub org + engine token), R-008 (approve repo-split steps 1–3), R-009 (create brand accounts), R-010 (lawyer session — RED risk), R-011 (WHOIS/privacy@/trademark clearance). R-002 annotated with the BSL recommendation. R-001 (launch/push approval) still open.
- **Blockers:** R2-07 (repo-split exec) blocked on R-007/R-008; outward growth blocked on brand accounts (R-009) + privacy/entity (R-010/R-011) + GC claim clearance. Plenty of unblocked build work for R2.
- **Spend:** none. LEDGER unchanged (7 real costs pending via R-006).
- **Observations logged:** 0001 (agent-run-company-scaffold skill), 0002 (engineering:architecture snapshot mode — by CTO).

## 2026-10-26 · cycle 2 (measurement foundation + strategy)
- **Recovery:** none. Founder answered R-001 (auto-push: yes), R-002 (licence: BSL), R-005 (no incorp till revenue), R-008 (repo-split 1–3: go); R-006 later; R-007 deferred to cut-over. Recorded in DECISIONS.
- **Dispatched (foreground, parallel):** CTO (R2-01 measurement build) · GC (R2-10 /terms + risk) · CFO (Phase-2 monetisation model) · CMO (R2-08 compare copy + R2-09 digest) · CPO (artefact/meter build plan).
- **Results (all accepted):**
  - CTO → R2-01 shipped: 8 files (events +9 names +step_name/channel; `share_token` on Search+JobResult + migration w/ unique index; `scan_blocked_incomplete` emit; signup `source`; `referred_signup`/`referral_activated`; `/go/{channel}` redirect w/ open-redirect guard; 9 new tests). **Independent gate: 597 passed, 1 skipped.** Reviewed /go guard + migration — safe, additive. **Pushed.**
  - GC → `TERMS_DRAFT.md` (no-auto-apply/no-scrape clause; non-refundable credits + EU 14-day carve-out), `PRIVACY_TERMS_NOTES` v2 (controller = Ettore personal, R-005), `RISK_REGISTER` v2 (incorp = accepted-until-revenue).
  - CFO → BUDGET §6 Phase-2: Plus **$15/mo** + packs **$12/30/60** (50/150/400cr); break-even **≈12 subs/mo**. Flagged legacy `plans`/`premium_*` config drift.
  - CMO → `COMPARE_COPY.md` (4 pages, claims [VERIFY]) + first `digest/2026-10-26.md` (8 drafts, filed).
  - CPO → ARTEFACTS_SPEC §8 build plan; key rule: activation CTA keys off `can_search`, not `score≥70`. Logged obs 0005.
- **Review notes:** CEO independently re-ran the full suite (597 passed) before pushing CTO's code; stray CSP-fix edits left untouched and out of the commit.
- **Requests opened:** none new. Standing: GC to clear COMPARE_COPY [VERIFY] cells (R3-07) before the pages publish.
- **Blockers:** none. R3 builds the visible artefacts + activation meter + repo-split 1–3 on this foundation.
- **Spend:** none.
- **Observations:** 0005 (CPO — threshold-gated CTAs bind to the gate predicate, not the displayed %).

## 2026-10-28 · cycle 3 (flagship match card + growth prep)
- **Recovery:** none. Scheduler decision: hourly cloud routine created (paused during this cycle to avoid collision; re-enabled after push).
- **Dispatched (foreground, parallel):** CTO (R3-01 match card) · GC (R3-07 clear COMPARE_COPY claims) · CPO (R3-02/03/04 build specs) · CMO (daily digest). CFO idle (no unblocked finance task).
- **Results (all accepted):**
  - CTO → **R3-01 shipped**: `web/app/routes/share.py` (`POST /job/{id}/share` owner-only → lazy-mint `share_token`; public `GET /m/{token}` no-auth card, no PII leak, noindex; `GET /m/{token}/card.png` OG via **cairosvg** reusing weasyprint's cairo libs + static fallback), `m_card.html`, `share_sheet.html`; Share button on job + tracker cards; `JobResult.share_show_company/name` cols + migration; referral embed. **Card is anonymous** (no name field exists). **Independent gate: 606 passed, 1 skipped.**
  - GC → cleared COMPARE_COPY: **20 cleared / 4 revised / 2 held** (dropped unsourced Indeed status, removed Teal $ figure). Pages gated on a hands-on source-review date (→ R-012).
  - CPO → ARTEFACTS_SPEC §8 de-staled + build-ready R3-02/03/04; caught the two-`can_search` ambiguity (bind CTA to `Completeness.can_search`).
  - CMO → `digest/2026-10-28.md` (9 drafts, filed); BetaList + PH-coming-soon first directories once accounts exist.
- **Review notes:** CEO re-ran the full suite (606 green) before push. Bundled the long-standing **CSP-dropdown fix** (track_card stage select + matches.html import field + app.js handler) into this commit — complete, tested, was entangled with the match-card edit to track_card.html.
- **Requests opened:** R-012 (hands-on source-review pass before any /compare page publishes). GC to review the share-card caption/CTA copy next cycle (honest/low-risk, shipped meanwhile).
- **Blockers:** none. R3-02/03/04 (market read, invite, activation meter) build next on the share machine.
- **Spend:** none. Added prod dep `cairosvg` (fallback-safe).
- **Scheduler:** hourly cloud routine `trig_01SFpcUqEqDrtvmsSUwYm2qw` — re-enabled + first run validated after this push.
