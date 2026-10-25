# Requests for the Founder — JBHNTR Team

Owner: CEO. Each request is self-contained (every step inline). `open | answered | done`. Oldest first.

---
### R-001 · Launch the company + confirm the runner · open
**What:** start the JBHNTR Team cycles. Same model as copytrade-co/Plainfleet.

**Note as you go** (values to confirm in your reply): (a) runner choice; (b) whether the CEO may auto-push tested, green product changes to `main` or must file each push; (c) the push-notification channel for the 08:00 update.

**Steps:**
1. **To run one cycle now (manual):** open Claude Code in `C:\Users\estra\OneDrive\Vibecoding\job-hunter` and paste the cycle prompt from `company/RUNBOOK.md` (§"Cycle prompt"). The session acts as CEO and dispatches the five agents.
2. **To automate the 30-min heartbeat + 08:00 update:** use the same scheduler you use for copytrade-co (a scheduled Claude Code session / routine that fires the cycle prompt every 30 min, and once at 08:00 Rome for the morning update). If you'd like me to wire a local Windows scheduled task or a Claude Code scheduled routine instead, reply "wire the runner" and say which.
3. **Standing push approval (b):** reply `auto-push: yes` to let the CEO push product changes that are tested green (recommended — the product already deploys safely from `main`), or `auto-push: no` to require a per-push request.
4. **Push notification (c):** reply with the channel for the 08:00 update (email to mt.helikon@gmail.com is the default; or Telegram/push).

**Note:** spend, account creation, OAuth, posting, and payment methods will each come as their own `R-###` with exact steps when a task needs them — the agents never do these themselves.

Answer:

---
### R-002 · Public open-core licence · open
**What:** the public `jbhntr/jbhntr` shell needs a source-available licence.
**Recommendation (cycle 1 — GC and CTO concur): BSL 1.1 → Apache-2.0 at a +3yr Change Date.** Both licences block a competitor re-hosting us and the engine stays private regardless, so this only governs the shell; BSL wins on open-core goodwill (precise "no competing hosted service" carve-out), a credible "not fake open source" signal (auto-conversion, which Elastic 2.0 lacks), and strong precedent (MariaDB/Sentry/HashiCorp). Everything already public under MIT stays MIT. Licensor must be the incorporated entity (ties to R-010). Detail: `company/docs/legal/LICENCE_RECOMMENDATION.md`.
**Reply:** `licence: BSL` to confirm, or `licence: Elastic` to override.

Answer:

---
### R-003 · Partner economics (Step 4) · open
**What:** when partnerships start (after ≥100 activated), do coach/partner codes pay **credits only** (default) or **credits + a small cash bounty** (e.g. €3–5) per activated client? Affects CAC and the budget.
**Reply:** `partner: credits-only` or `partner: credits+cash (€N)`. Can defer until week 6.

Answer:

---
### R-004 · Show HN timing · open
**What:** fix the Show HN to ~week 8, or make it conditional on ≥70% positive interview verdicts? (It needs the post-split public repo + 100+ real users who can answer in the thread.)
**Reply:** `showhn: week8` or `showhn: conditional`. Can defer until week 6.

Answer:

---
### R-005 · Incorporation vehicle + timing · open
**What:** GDPR needs a named controller (your name is fine during private beta). Incorporation is a liability + payments decision, recommended before Phase 2 (paid credits) and ideally before the data-drop/Show-HN spikes (weeks 7–8). GC recommends a one-hour session with an Italian lawyer before public launch (see the GTM §12 / the legal setup doc).
**Reply:** when to calendar it + whether you want GC to prepare a vehicle-options memo first.

Answer:

---
### R-006 · Confirm 7 real costs (so the budget snaps to actuals) · open
**What:** the CFO break-even model is structurally complete but the dollar figures stay estimates until these are confirmed. None block building.
**Note as you go** (one line each): 1) **Railway** current monthly bill (app + Postgres plan); 2) **jbhntr.app** domain annual renewal + registrar; 3) **actual LLM spend** last 30d (OpenRouter/Anthropic dashboard) ÷ scan & doc counts — to validate ~$0.13/scan & ~$0.20/doc; 4) **embeddings** provider + rate (or "on-device/free"); 5) **Resend** plan + monthly email volume (free cap 3,000/mo, 100/day); 6) **JSearch/RapidAPI** (or other job source) quota + cost; 7) any **trademark/incorporation** quote you have.
**Reply:** paste the 7 values (or "don't know" for any) — CFO enters real LEDGER rows.

Answer:

---
### R-007 · GitHub org + read-only engine token (for the repo-split cut-over) · open
**What:** needed only for the public cut-over (repo-split steps 4+), not for next cycle's in-repo refactor.
**Steps:** 1) create GitHub org `jbhntr`; 2) create public `jbhntr/jbhntr`, private `jbhntr/jbhntr-engine`, private `jbhntr/jbhntr-legacy`; 3) create a **fine-grained PAT scoped to `jbhntr/jbhntr-engine`, contents:read only**; 4) add it as `ENGINE_READ_TOKEN` to the Railway `web` + `cron` services **via the Railway dashboard** (never in a file or chat). 5) confirm the org name.
**Reply:** "org done" + the org name, once set.

Answer:

---
### R-008 · Approve repo-split steps 1–3 (next cycle) · open
**What:** let the CTO execute the **in-repo, reversible** part next cycle: build the `jbhntr_engine` façade (funnel the 78 import sites), add the demo engine + boot guard, carve the private package. Tests stay green; nothing goes public. Steps 4–7 (public snapshot + cut-over) come back for a **separate** go.
**Reply:** `repo-split 1-3: go` or hold.

Answer:

---
### R-009 · Create the JBHNTR brand accounts (one sitting) · open
**What:** the CMO wrote the full pack (handles, bios, cadence) in `company/docs/marketing/BRAND_ACCOUNTS.md §3` — 8 numbered steps, one platform each, dependency-ordered (email aliases → GitHub org → X → Bluesky → Threads → Reddit → LinkedIn Page → HN), ending with a one-paste reply template for the 7 URLs + 2 LinkedIn confirmations. **Important:** create/administer the LinkedIn Company Page from `hello@jbhntr.app`, and do **not** list JBHNTR on your personal LinkedIn (brand-led posture).
**Reply:** follow §3 and paste the reply template; or say "do the handles check first" and GC/CMO will verify availability.

Answer:

---
### R-010 · Book the Italian lawyer/commercialista session (RED risk) · open
**What:** the risk register flags incorporation as the one **RED** item — until an entity exists, data-controller liability sits on you personally, and /privacy, /terms, and the BSL Licensor all need the entity. Recommended before Phase 2 and before the data-drop/Show-HN spikes (weeks 7–8).
**Session covers:** incorporate (SRL/SRLS), confirm the controller + privacy/terms drafts, trademark clearance + whether to file the EU (and US) mark. *Not legal advice; GC prepares a briefing doc for the session on request.*
**Reply:** a target date + "GC: prep the briefing" if you want it.

Answer:

---
### R-011 · Quick legal-foundation setup (15 min) · open
**Steps:** 1) turn on **WHOIS privacy** for jbhntr.app at the registrar; 2) create + monitor **privacy@jbhntr.app**; 3) run a free **TMview / EUIPO / USPTO / UIBM** clearance search on "JBHNTR" (flag any conflict to GC).
**Reply:** "done" + any trademark conflict found.

Answer:

