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

## P2 — Typography + webfonts
Files: web/app/static/app.css, templates/base.html, web/app/static/fonts/*.woff2 + OFL.txt
Generated subsets myself (fonttools varLib.instancer + subset): Plus Jakarta Sans 700/800,
DM Sans 400/500/600 + 400-italic (opsz pinned to 14). All woff2 12.9-16.6 KB (<40 KB).
Combined SIL OFL 1.1 licence committed. @font-face + preloads (dmsans-400, pjs-800) added;
theme-color -> #17334B. Installed §3.2 scale (display headings, DM Sans body, 16px input
floor, tabular figures). Verified on /: fonts load 200, PJS headline + DM Sans body render
clean, no unstyled fallback.
Decision: kept 5 component sub-head <h3> sizes (.step/.benefit/.au-run/.market-flow-step 15-17px,
.admin-two 14px) rather than the 20-24px h3 clamp — they're card sub-labels, already use the
display font, and the clamp would break those card layouts (hard-constraint #1). Flagged for
review if strict acceptance is required.

