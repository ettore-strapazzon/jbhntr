# JBHNTR — Brand v3 migration log

Per the Brand v3 Migration Manual (v1.1). Baseline: `f761c38`. One commit per phase to `main`.

## P1 — Token layer
Files: web/app/static/app.css
Installed the v3 three-tier token block; removed the second :root block (its vars now
at the top); grid maxima 1140→var(--container) (1200/1120); deleted --brass. Legacy
aliases kept (removed in P3). Preserved --tier-1..5 (re-valued P6) and --step-lede/
--space-* so nothing breaks. Verified: / renders warm-white + navy, no unstyled nodes.
Decisions: kept 4 block-2-only vars the manual's block omitted (as aliases) to avoid
breakage; updated all three 1140px grid maxima (main/nav/footer), not just main.

