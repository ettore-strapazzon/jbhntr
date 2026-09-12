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

## P3 — Colour sweep
Files: web/app/static/app.css, web/app/static/app.js, web/app/templating.py, 3 templates
Swept ~90 literal hex + 17 alias vars (269 alias refs) to canonical tokens; deleted the
legacy alias block. a{}->--link + a:hover; :focus-visible 3px/--focus-ring. plan--premium
navy-surface: rgba(255,255,255,.x) -> corn-300 (text/marks), navy-600 (figs border), btn
border corn-300. toast bg -> navy-900, toast link/x -> corn-300. app.js toast default
#1f2a24->#17334B. TIER_COLOURS marked TODO(P6). Verified /, /credits: no legacy hex, no
console errors, tabular figures align. Loadbar shimmer rgba left for P9.
Unmapped: none. Decisions: #eee/#ddd->--border-subtle, #444->--text-primary, #1b7a43
(offer)->--status-success, step-marker white ring kept as --white.

## P4 — Component state matrix
Files: web/app/static/app.css
Buttons -> pill (--r-chip) with full state matrix (default/hover/active/disabled/busy;
ghost/link/danger; lg/md/sm sizes). Inputs -> border-strong + focus (3px focus-ring)/
invalid/disabled. Card -> border + --elev-0, .card--selected 2px, mobile sp-4 padding.
Selection states (.chipcheck.on/.ratebtn.on/.btn.on/.actiongroup.on/.plan-row:hover) ->
2px border + --accent-selected tint (no fill-alone). Elevation only on overlays: stripped
textarea/proof-card/marker shadows; toast + cookie-note -> --elev-2. Old-pine rgba(23,75,62)
-> navy rgba. Verified /signup: pill button, styled inputs, 3px focus ring, border-only card.
Observation (not fixed, copy is out of scope): /signup subtitle still says "run 25 complete
market scans" (pre-credits copy).

