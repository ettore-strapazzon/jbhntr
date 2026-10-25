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
