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

## 2026-11-13 · cycle 4 (market read + activation meter + artefact privacy hardening)
- **Recovery:** none ("doing" tasks: none). No new Founder orders in BACKLOG/REQUESTS/DECISIONS. Note: R3-07 was already done in c3 but still marked todo — corrected.
- **Dispatched (foreground, parallel):** CTO (R3-02 market read) · CPO (R3-04 activation meter) · CMO (/invite copy for R3-03 + digest) · GC (match-card compliance review owed from c3 + R3-07 close-out). CFO idle (no unblocked finance task; R-006 still open).
- **Results:**
  - CTO → **R3-02 sent back once** (GC found false claims "every live role scanned"/"every role is scored both ways", no incentive disclosure, no unshare, PNGs under public `/static`, no noindex header; CTO's first report was a security review only). Re-delivered: `/r/{token}` stage funnel (raw→located→ranked→scored), anonymise default on (PII canary tests both states), owner-only share/unshare for card+read, OG cache → `data/og/` (git-ignored), `X-Robots-Tag: noindex`, PNGs deleted on account deletion, employer default off, GC caption text w/ referral disclosure, /cookies (jb_ref, "two cookies") + /privacy rows. 22 new tests. **Accepted.** CTO ran `git stash`/`pop` on the shared tree briefly (restored cleanly) — reminded: never on a shared worktree.
  - CPO → **R3-04 accepted**: meter on onboarding + /profile (meter arm only, until first scan); CTA bound to `Completeness.can_search` with 91%-but-locked fixture + reverse + 70 boundary tests; deterministic 50/50 hash A/B; variant on signup/scan/threshold/onboarding/blocked events; `first_scan_rate_by_variant` readout; `ACTIVATION_METER` kill switch. Not on /matches (protected file).
  - CMO → /invite copy build-ready in ARTEFACTS_SPEC §3.5 (all states, 6 channel messages w/ incentive disclosure, config-driven numbers); digest `digest/2026-11-13.md` (8 drafts, filed). Dropped invented first-person stories from the brand voice. **Accepted.**
  - GC → COMPLIANCE_CARD v1.1 (new C11 + 20-element card verdict table + market-read MR1–6 + invite IN1–6 rules), RISK_REGISTER v3 (share over-exposure 3×3 YELLOW). 2 HIGH / 5 MED / 2 LOW card changes — all fixed this cycle except HIGH #2 (fit-notes preview) → R3-10. Found TERMS_DRAFT §6 vs code mismatch on referral payout → R3-11. **Accepted.**
- **Test gate (CEO, once, after all agents):** first run 1 failure — the new test modules leaked fixture profiles' `search_terms` into the shared test DB, breaking `test_corpus_terms_and_countries_prioritise_users_then_defaults`. CEO added module-scoped teardown fixtures to both new modules. **Final: 645 passed, 1 skipped.** Pushed.
- **New backlog:** R3-10 (fit-notes preview/concerns toggle), R3-11 (referral payout ↔ terms), R3-12 (GC self-serve compare source pass).
- **Requests:** R-012 updated with GC's 45-min checklist. None new. R-009 (brand accounts) open 19 days — the top outward blocker (25 drafts filed, none postable).
- **Blockers:** outward growth still on R-009/R-011; /compare on R-012. GC must clear /invite §3.5 copy + CTO's extra /cookies//privacy sentences before /invite ships.
- **Spend:** none.
- **Observations:** `task-observer` skill not present in this session's live skill list (gap). Starting-map skills `cro`/`onboarding`/`referrals`/`copywriting` also absent — SKILLS.md map is stale vs live list.

## 2026-11-13 · cycle 5 (referral payout safety + fit-notes control + /invite built dark)
- **Recovery:** none ("doing": none). No new Founder orders. Cycles today: 2/10.
- **Dispatched (foreground, parallel):** CTO (R3-10 then R3-11) · CPO (R3-03 /invite behind `INVITE_PAGE` flag) · GC (clear §3.5 invite copy + R3-12 compare source pass). CMO idle (today's digest already filed) · CFO idle (R-006 open).
- **Results (all accepted):**
  - CTO → **R3-10**: one `share.public_bullets()` feeds share-sheet preview, `/m/{token}` and the OG PNG (identical by test); new `JobResult.share_show_concerns` (default off, owner-only toggle, resets on re-share, busts PNG cache). **R3-11**: referral reward now `ReferralReward` pending → `release_due()` pays only after ≥48h **and** friend's first triage action (nightly cron + opportunistic), soft ceiling 25/calendar month → held + admin unlock/hold routes (`require_admin`); idempotent on the legacy ledger key (no double pay); account deletion cleans rows; TERMS_DRAFT §6 v1.1 matches code. `test_web` referral e2e test updated to the delayed rule. Auto duplicate-detection (CV/device/IP) not built → engine, post-split.
  - CPO → **R3-03** `/invite` (route, template, `invite.js` CSP-safe, counter signed-up/credited/pending/earned, events, noindex meta+header), flag default **off** (404). Re-wired mid-build to GC's v1.2 copy.
  - GC → COMPLIANCE_CARD v1.2: invite copy 16 clear / 7 revised / launch HOLD until R3-11 live + build re-check; COMPARE_COPY: 17✓ 2✗(fixed) 5? dated 2026-11-13; R-012 shrunk to 2 short browser checks (Teal pages + optional Indeed).
- **CEO review fixes:** applied GC's outstanding text — "about two days" → "two to three days" in invite.html/credits.html/welcome emails (+ test string); step-3 triage list incl. "marked as applied"; `base.html` cookie notice now "two essential cookies" (K6/K7).
- **Test gate (CEO, once, after all agents):** **682 passed, 1 skipped, 0 failed.** Pushed.
- **New backlog:** R3-13 (GC re-check of the built /invite, then CEO files the flag-flip request).
- **Requests:** R-012 rewritten by GC (smaller). None new.
- **Blockers:** outward growth still on R-009 (brand accounts, open 19 days) / R-011. /invite go-live on R3-13.
- **Spend:** none.
- **Observations:** `task-observer` absent from the skill list at session start, appeared mid-cycle → invoked late; logged obs 0001 in the new host workspace `~/.claude/skill-observations/`. GC flagged a reusable gap: a "competitor public-page source pass" workflow with search-result fallback for bot-blocked sites.

## 2026-11-13 · cycle 6 (BI dashboard + comparison pages + /invite cleared)
- **Recovery:** none ("doing": none). No new Founder orders. Cycles today: 3/10.
- **Dispatched (foreground, parallel):** CTO (R3-06 BI dashboard) · CMO (R3-08 compare pages ×3) · GC (R3-13 /invite re-check). R3-05 repo-split **held for a solo cycle** (78 import sites would collide with parallel web/ edits). CPO idle (no unblocked CPO task until R3-14 was opened) · CFO idle (R-006 open).
- **Results (all accepted):**
  - CTO → **R3-06**: `web/app/services/metrics.py` (`compute(db)`: activated, signups, funnel, activation rate, gate, K, outcomes/active/wk, meter A/B, referral rewards, LEDGER spend/revenue; every "—" carries a reason), `/admin` tiles + `/admin/metrics.json` (admin gate, no-store, no PII). Activation reuses `profile_service` via new pure `present_from`/`completeness_from` (one rule, tested against `completeness()` on 7 shapes); flat query count tested. K = referred activated ÷ all activated (standard viral coefficient; per-inviter ratio shown beside it) — accepted. Gate = — because the gate prompt was never built → R3-14.
  - CMO → **R3-08**: `/compare/jobright`, `/compare/simplify`, `/compare/auto-apply-tools` from one `compare.html` + `compare_pages.py` data; GC-cleared copy verbatim; "Last reviewed 13 November 2026", vendor disclosure, sources, JSON-LD `lastReviewed`, sitemap + footer/how-it-works cross-links; `/compare/teal` 404, no Indeed/Sonara. Note: auto-apply sources list names LazyApply/LoopCV/AIApply (GC-checked ✓ 13 Nov) — GC to confirm at next pass.
  - GC → **R3-13 GO** (COMPLIANCE_CARD v1.3 §E): IN1–IN6 all hold vs code + TERMS §6 v1.1; one comma fixed in invite.html. Findings: E-1 payout stage ran last in nightly (OOM risk) · E-2 no held-queue UI · E-3 pending count from events · E-4 live /terms lacks referral section (named-operator track) · E-5 FIRST_SCAN_FREE copy edge.
- **CEO review fixes:** E-1 fixed — `referral_released` now the FIRST stage of `cron.nightly()`.
- **Test gate (CEO, once, after all agents):** **720 passed, 1 skipped, 0 failed.** Pushed.
- **New backlog:** R3-14 (gate prompt), R3-15 (held-referral admin queue + E-3).
- **Requests:** **R-013** filed (flip `INVITE_PAGE=true`, with pre-flip nightly-log check + rollback).
- **Blockers:** outward growth still on R-009 (brand accounts) / R-011; /compare/teal on R-012.
- **Spend:** none.
- **Observations:** GC proposed a reusable "flag-flip launch re-check" workflow (copy vs code vs terms + pre-flip ops check); sub-agents skipped task-observer at task start.

## 2026-11-13 · cycle 7 (repo split steps 1–3 — solo)
- **Recovery:** none ("doing": none). No new Founder orders. Cycles today: 4/10.
- **Dispatched (foreground, solo by c6 decision):** CTO (R3-05). CPO/CMO/GC/CFO held: R3-14/R3-15 touch `web/` and would collide with a 78-site import refactor; today's digest already filed; R-006 open.
- **Result (accepted):** CTO → **R3-05** steps 1–3 in-repo: `jbhntr_engine/` = public contract + lazy selector (`JBHNTR_ENGINE=auto|real|demo`, default auto→real); all 78 `jobhunter.*` imports in `web/` now 60 `from jbhntr_engine import …` lines (0 left; `tests/test_engine_boundary.py`, mutation-checked); prompt-bearing `panel`/`recover`/CV-vision + 3 small prompts moved to `jbhntr_engine_real/`; `jbhntr_engine_demo/` (12 fictional example.com jobs, keyword scoring, no LLM/network) runs signup→scan→/matches end-to-end; `web/app/engine_guard.py` at web start + cron refuses non-real engine with `DEBUG` off; `scripts/build_engine_wheel.py --verify` proves public-only → demo (prod refuses) and public+wheel → real. No new env var needed for the live deploy (CTO checked a clean `requirements-web.txt` venv; CEO re-checked `DEBUG=false` → real engine, no problems). Deviations recorded in plan §0 (naming `jbhntr_engine_real`; Settings/types public; façade 48 symbols vs 8).
- **CEO review fixes:** CTO found a pre-existing bug — `search_service._verify_links` returned a bare list on its early exits while the caller unpacks two values, so zero-result scans (or a link-check exception) failed and were refunded. Fixed (returns `(ranked, set())`) + `tests/test_verify_links.py`.
- **Test gate (CEO, once, after all agents):** **745 passed, 1 skipped, 0 failed.** Pushed.
- **New backlog:** R3-16 (finish the private carve + cron `DEBUG=false` check before step 4).
- **Requests:** none new. R-009 (brand accounts) still the top outward blocker; R-013 (flip `INVITE_PAGE`) awaiting Founder.
- **Blockers:** steps 4–7 of the split need a separate Founder go (after R3-16).
- **Spend:** none.
- **Observations:** CTO logged a reusable lesson: a refactor that changes which modules load at startup needs a check in a clean environment built only from the production requirements.
