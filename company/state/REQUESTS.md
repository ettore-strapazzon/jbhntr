# Requests for the Founder — JBHNTR Team

Owner: CEO. Each request is self-contained (every step inline). `open | answered | done`. Oldest first.

---
### R-001 · Launch the company + confirm the runner · answered 2026-10-26
**What:** start the JBHNTR Team cycles. Same model as copytrade-co/Plainfleet.

**Note as you go** (values to confirm in your reply): (a) runner choice; (b) whether the CEO may auto-push tested, green product changes to `main` or must file each push; (c) the push-notification channel for the 08:00 update.

**Steps:**
1. **To run one cycle now (manual):** open Claude Code in `C:\Users\estra\OneDrive\Vibecoding\job-hunter` and paste the cycle prompt from `company/RUNBOOK.md` (§"Cycle prompt"). The session acts as CEO and dispatches the five agents.
2. **To automate the 30-min heartbeat + 08:00 update:** use the same scheduler you use for copytrade-co (a scheduled Claude Code session / routine that fires the cycle prompt every 30 min, and once at 08:00 Rome for the morning update). If you'd like me to wire a local Windows scheduled task or a Claude Code scheduled routine instead, reply "wire the runner" and say which.
3. **Standing push approval (b):** reply `auto-push: yes` to let the CEO push product changes that are tested green (recommended — the product already deploys safely from `main`), or `auto-push: no` to require a per-push request.
4. **Push notification (c):** reply with the channel for the 08:00 update (email to mt.helikon@gmail.com is the default; or Telegram/push).

**Note:** spend, account creation, OAuth, posting, and payment methods will each come as their own `R-###` with exact steps when a task needs them — the agents never do these themselves.

Answer: **(2026-10-26) ANSWERED.** Runner = same as copytrade-co. **auto-push: YES** (CEO pushes tested-green product changes; still reviews the diff + runs the suite first). Notification channel: default (email mt.helikon@gmail.com). Offered: CEO to wire a local Windows scheduled task for the 30-min + 08:00 cadence — Founder to confirm local vs manual-for-now.

---
### R-002 · Public open-core licence · answered 2026-10-26
**What:** the public `jbhntr/jbhntr` shell needs a source-available licence.
**Recommendation (cycle 1 — GC and CTO concur): BSL 1.1 → Apache-2.0 at a +3yr Change Date.** Both licences block a competitor re-hosting us and the engine stays private regardless, so this only governs the shell; BSL wins on open-core goodwill (precise "no competing hosted service" carve-out), a credible "not fake open source" signal (auto-conversion, which Elastic 2.0 lacks), and strong precedent (MariaDB/Sentry/HashiCorp). Everything already public under MIT stays MIT. Licensor must be the incorporated entity (ties to R-010). Detail: `company/docs/legal/LICENCE_RECOMMENDATION.md`.
**Reply:** `licence: BSL` to confirm, or `licence: Elastic` to override.

Answer: **(2026-10-26) ANSWERED — BSL 1.1.** Confirmed on the basis that BSL does not restrict our own monetisation (credit buys / premium / paid service); it only blocks a competing hosted service.

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
### R-005 · Incorporation vehicle + timing · answered 2026-10-26
**What:** GDPR needs a named controller (your name is fine during private beta). Incorporation is a liability + payments decision, recommended before Phase 2 (paid credits) and ideally before the data-drop/Show-HN spikes (weeks 7–8). GC recommends a one-hour session with an Italian lawyer before public launch (see the GTM §12 / the legal setup doc).
**Reply:** when to calendar it + whether you want GC to prepare a vehicle-options memo first.

Answer: **(2026-10-26) ANSWERED.** No incorporation until revenue is needed (≈ before Phase-2 paid credits). Founder accepts the residual controller-liability/footer exposure during the public-beta spikes. GC: reflect "accepted until revenue" in the risk register; keep /privacy, /terms, data-drop and Show-HN gated on a named controller.

---
### R-006 · Confirm 7 real costs (so the budget snaps to actuals) · open
**What:** the CFO break-even model is structurally complete but the dollar figures stay estimates until these are confirmed. None block building.
**Note as you go** (one line each): 1) **Railway** current monthly bill (app + Postgres plan); 2) **jbhntr.app** domain annual renewal + registrar; 3) **actual LLM spend** last 30d (OpenRouter/Anthropic dashboard) ÷ scan & doc counts — to validate ~$0.13/scan & ~$0.20/doc; 4) **embeddings** provider + rate (or "on-device/free"); 5) **Resend** plan + monthly email volume (free cap 3,000/mo, 100/day); 6) **JSearch/RapidAPI** (or other job source) quota + cost; 7) any **trademark/incorporation** quote you have.
**Reply:** paste the 7 values (or "don't know" for any) — CFO enters real LEDGER rows.

Answer: **(2026-10-26) Founder will confirm later.** Budget figures stay estimates meanwhile; CFO models with estimates, snaps to actuals when provided. Still open.

---
### R-007 · GitHub org + read-only engine token (for the repo-split cut-over) · open
**What:** needed only for the public cut-over (repo-split steps 4+), not for next cycle's in-repo refactor.
**Steps:** 1) create GitHub org `jbhntr`; 2) create public `jbhntr/jbhntr`, private `jbhntr/jbhntr-engine`, private `jbhntr/jbhntr-legacy`; 3) create a **fine-grained PAT scoped to `jbhntr/jbhntr-engine`, contents:read only**; 4) add it as `ENGINE_READ_TOKEN` to the Railway `web` + `cron` services **via the Railway dashboard** (never in a file or chat). 5) confirm the org name.
**Reply:** "org done" + the org name, once set.

Answer: **(2026-10-26) Deferred to the public cut-over.** Not needed for repo-split steps 1–3 (in-repo). CEO will re-surface this when steps 4–7 (public snapshot) are ready. Still open.

---
### R-008 · Approve repo-split steps 1–3 (next cycle) · answered 2026-10-26
**What:** let the CTO execute the **in-repo, reversible** part next cycle: build the `jbhntr_engine` façade (funnel the 78 import sites), add the demo engine + boot guard, carve the private package. Tests stay green; nothing goes public. Steps 4–7 (public snapshot + cut-over) come back for a **separate** go.
**Reply:** `repo-split 1-3: go` or hold.

Answer: **(2026-10-26) ANSWERED — go.** Founder trusts the CTO to execute steps 1–3 following the GTM/plan. Steps 4–7 (public cut-over) return for a separate go.

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

---
### R-012 · Two 5-minute browser checks before `/compare/teal` ships and before we name Indeed · open (rewritten 2026-11-13 after GC R3-12)
**What changed:** GC read every competitor's public pages itself on 2026-11-13 (R3-12). 17 of 24 cells confirmed, 2 wrong ones corrected, 4 reworded to what the sites actually say. Three pages (`/compare/jobright`, `/compare/simplify`, `/compare/auto-apply-tools`) now carry a real "Last reviewed … 13 November 2026" date and **need nothing from you**. **No step below needs an account, sign-up, form or payment.** Two sites block automated readers (HTTP 403), so only a human browser can read them. That is the whole residual.

**Step 1 — Teal (unblocks `/compare/teal`; ~5 min).** In a normal or private browser window, without logging in:
1. Open `https://www.tealhq.com/tools/job-tracker`. Answer: does it say you can save/bookmark jobs from job boards with a Chrome extension? (yes/no)
2. Open `https://www.tealhq.com/tools/resume-builder`. Answer: does it offer a résumé builder that tailors to a job description? (yes/no)
3. Open `https://www.tealhq.com/` and scroll once. Answer: does Teal **recommend or find jobs for you** (e.g. "job recommendations", "job search", "find jobs") or only organise jobs you save? Paste the one sentence that says so, or write "not seen".
4. Open `https://www.tealhq.com/pricing`. Answer: is there a free plan and a paid plan called Teal+? (yes/no). Optional: the Teal+ price(s) as shown.

**Step 2 — Indeed "Apply for me" (decides whether the auto-apply page may name Indeed; ~3 min; optional — the page ships without it).**
1. Open `https://www.indeed.com/news/releases/indeed-tests-apply-for-me-job-search`.
2. Copy the **date** shown on the release and the one sentence that says who can use "Apply for me" (e.g. "a limited group of U.S. job seekers").
3. If that page doesn't load, write "not loaded" and stop. Indeed stays unnamed.

**Reply format (paste under Answer):** `2026-MM-DD · Teal 1:yes/no 2:yes/no 3:"<sentence>"/not seen 4:yes/no [$..] · Indeed: <date> "<sentence>" / not loaded`. GC then sets the Teal date (or corrects a cell), and decides the Indeed line.

**No longer on you:** Jobright, Simplify, LazyApply, AIApply, LoopCV and the LinkedIn User Agreement were all read by GC (URLs in `company/docs/marketing/COMPARE_COPY.md`, section "GC source pass R3-12"). Sonara is not named in any copy, so its status doesn't matter. The "first handful of applications" corpus stat is a CFO/CTO task (GTM §5.3), not a request to you. The interim non-numeric copy ships.

Answer:


---
### R-013 · Turn on the /invite page (~10 min, no spend) · open
**What:** the invite page (your referral link, a live counter and six ready-to-send messages with the incentive disclosed) is built and tested. GC cleared it on 2026-11-13 (COMPLIANCE_CARD v1.3 §E). It stays hidden until you set one Railway variable. **Do this after cycle 6's push has deployed.**

**Before you flip:** in the Railway dashboard, open the **cron** service → Deployments → latest nightly run → Logs. Check that the run ends with a `nightly done …` line containing `'referral_released': <a number>`, not an error and not an exit-137 crash. If it crashed, stop here and reply "nightly crashed". Inviter credits depend on that job.

**Steps:**
1. Railway dashboard → project → **web** service → **Variables** → **New Variable**: name `INVITE_PAGE`, value `true` → Add.
2. Click **Deploy** (or apply the staged change) and wait until the deploy shows Active. Don't put the value in any file or chat.

**Verify:**
- a) Signed in, open https://jbhntr.app/invite. You should see "Know someone applying to everything?", your link `https://jbhntr.app/signup?ref=<CODE>`, "Your invites" and six messages.
- b) An **Invite** link appears in the top nav and on /credits.
- c) The page source contains `<meta name="robots" content="noindex,nofollow">`.
- d) In a private window, /invite sends you to /login.
- e) "Copy link" changes to "Copied".

**Roll back (any time, nothing is lost):** web service → Variables → set `INVITE_PAGE` to `false` (or delete it) → Deploy. /invite returns 404 and the links disappear. Codes, bonuses and pending payouts are unaffected.

**After launch:** once R3-15 ships, check the held-referral queue in /admin each Monday and unlock clean rewards. The page promises held rewards are reviewed by hand, never refused automatically.

**Reply:** `invite live <time>` or `nightly crashed`.

Answer:

---

### R-014 · Confirm the nightly cron runs in production mode (~3 min, no spend) · open
**What:** the nightly job refuses to run on the demo engine only when `DEBUG=false` is set on the cron service. The repo can't prove it is set (`railway.cron.json` sets no variables; `config.debug` defaults to true). This must be confirmed before repo-split step 4.

**Steps:**
1. Railway dashboard → project → the **cron** service (start command `python -m web.app.services.cron`) → **Variables**.
2. Look for `DEBUG`. If it is `false`, change nothing. If it is missing or `true`: **New Variable** (or edit) → name `DEBUG`, value `false` → Add. Don't put the value in any file or chat.
3. If you changed it, open Deployments and click **Run now** once.

**Verify:** the latest cron run's logs end with a `nightly done …` line, with no `Refusing to start in production` and no `ENGINE:` warning.

**Roll back:** set `DEBUG` back to its previous value and redeploy.

**Reply:** `cron debug=false confirmed` / `was missing, set` / `run failed: <first error line>`.

Answer:

### R-015 · Install the in-repo team runner (~15 min, no spend, after R3-34–R3-36 ship) · open
**What:** the team runner moves into the repo (`ops/team/`) so agents can fix it by commit, and chat gets its own clone so it can answer while a cycle runs. Installing it touches crontab, the `jbhntr-chat` systemd unit and the runtime dir, which agents must not do. Wait until the Boardroom shows R3-34, R3-35 and R3-36 as shipped. **Never touch anything named plainfleet** (its cron lines and `plainfleet-chat.service` stay as they are).

**Steps (on the VM, as `ubuntu`):**
1. `cd ~/jbhntr && git pull --ff-only`
2. Back up the old runner: `cp ~/run_cycle.sh ~/.jbhntr-team/run_cycle.old.sh`
3a. Seed the wrapper's fallback copy: `cp ops/team/run_cycle.sh ~/.jbhntr-team/run_cycle.good.sh`
3. Install the wrapper by copy + move (never edit in place): `cp ops/team/run_wrapper.sh ~/.jbhntr-team/run_cycle.sh.tmp && chmod +x ~/.jbhntr-team/run_cycle.sh.tmp && mv -f ~/.jbhntr-team/run_cycle.sh.tmp ~/.jbhntr-team/run_cycle.sh`
4. Chat clone: `git clone "$(git -C ~/jbhntr remote get-url origin)" ~/.jbhntr-team/chat-wt` (uses the VM's existing GitHub key; if it asks for credentials, stop and reply `clone needs key`).
5. Env file: `nano ~/.jbhntr-team/env` and add only the non-secret lines the R3-36 CYCLE_LOG entry lists (repo path, chat-clone path, attachments dir). Keep `chmod 600 ~/.jbhntr-team/env`. Don't paste values into chat.
6. Crontab: `crontab -e`, change **only** the two lines containing `/home/ubuntu/run_cycle.sh` to `/home/ubuntu/.jbhntr-team/run_cycle.sh` (same times, same log).
7. Chat service: `sudo systemctl edit --full jbhntr-chat` → set the loop to call `~/.jbhntr-team/run_cycle.sh chat` (or point `ExecStart` at `ops/team/chat-daemon.sh` if R3-36 ships one) → `sudo systemctl restart jbhntr-chat`. Do not restart or edit `plainfleet-chat`.

**Verify:** send "ping" in the Boardroom → CEO reply within ~1 min; `tail ~/.jbhntr-team/cycle.log` shows the next `[cycle]` run with no `[wrapper]` warning; `systemctl status plainfleet-chat` still active.

**Roll back:** put the two crontab paths back to `/home/ubuntu/run_cycle.sh`, revert the service loop, `sudo systemctl restart jbhntr-chat`.

**Reply:** `runner installed` / `stuck at step N: <first error line>`.

Answer:
