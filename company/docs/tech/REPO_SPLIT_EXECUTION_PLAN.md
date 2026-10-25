# REPO_SPLIT_EXECUTION_PLAN — open-core split

Owner: CTO (+ GC on licence) · Updated 2026-10-25 · **Status: PROPOSED — Founder approval required before any code moves.** · Backlog R1-06 · GTM §7 / manual §12.

This is a plan, not an execution. No code is moved by writing it. It is built from a real inspection of this repo (`web/`, `jobhunter/`, `tests/`).

## 1. Goal and shape

Split the monorepo into:

- **Public `jbhntr/jbhntr`** — the shell (FastAPI app, templates, routes, static, auth, credits, billing, measurement, admin) **+ a demo engine** that returns canned data so the app runs and screenshots without the private engine. Source-available licence (see §d).
- **Private `jbhntr/jbhntr-engine`** — an installable Python package (`jbhntr_engine`) holding the moat: sources/connectors, ranking + triage prompts, ingestion lanes, dedup, discovery, tag/criteria vocabulary, embeddings wiring, seed corpus, and (when built) referral anti-abuse heuristics.

Production installs the **real** engine at build time with a read-only token; the app **refuses to boot** if it silently fell back to the demo engine (§c).

Why open-core at all (GTM §7): credibility + inbound ("the shell is real, go read it") without handing competitors the matching engine. The shell is the commodity; the engine is the product.

## 2. The boundary problem (the actual work)

The web shell today imports `jobhunter.*` **deeply and widely** — 78 import sites across `web/`, reaching private helpers (`jobhunter.dedup._is_generic_remote`, `jobhunter.discover._slugify`, `jobhunter.sources.ats.FETCHERS`). Referenced submodules, by frequency:

```
12 jobhunter.config        10 jobhunter.models       4 jobhunter.tags
 4 jobhunter.sources.*     4 jobhunter.sources.base  4 jobhunter.sources.ats
 3 jobhunter.sources.agency_hints   3 jobhunter.matcher   3 jobhunter.candidate
 2 jobhunter.discover  2 jobhunter.dedup  2 jobhunter.criteria
 1 each: sources.keyed, geo, generator, gdrive
```

**This is the blocker and the bulk of the engineering.** You cannot `pip install` a private package and have 78 deep import sites keep working unless the package exposes exactly those paths — which would publish the module layout (Hyrum's Law: every imported path becomes a contract). So the split's real task is to **funnel those 78 sites through one stable façade** (`jbhntr_engine`'s top-level API), then move everything behind it private. Until the façade exists, the split is not executable.

## 3. (a) File / module inventory — PUBLIC vs PRIVATE

### PUBLIC — `jbhntr/jbhntr` (shell + demo engine)

| Path | Why public |
|---|---|
| `web/app/main.py`, `config.py`, `db.py`, `templating.py`, `seo.py`, `security.py` | App wiring, no moat |
| `web/app/routes/` (all) | HTTP surface; commodity |
| `web/app/templates/`, `static/` | UI |
| `web/app/auth.py`, `routes/auth_routes.py` | Standard auth |
| `web/app/services/`: `credits.py`, `referral.py` (code-minting only), `email.py`, `digest.py`, `events.py`, `job_events.py`, `analytics.py`, `doc_quota.py`, `export.py`, `cv_build.py`, `cv_html.py`, `cv_style.py`, `migrate_credits.py`, `reset_usage.py`, `import_service.py`, `recover.py`, `job_state.py`, `matches_service.py`, `text.py`, `gdocs.py` | Product plumbing: billing, email, export rendering, measurement, account. No ranking/source logic. |
| `web/app/models.py` | Product DB schema (users, credits, events) — not the engine's data contracts |
| `tests/test_web.py`, `test_credits.py` | Shell tests |
| `jobhunter/models.py` **(the data contracts only)** → re-homed, see §b | `JobPosting`, `MatchResult`, `RankedJob`, `TIER_LABELS`, `tier_for_score` are the wire types the shell needs |
| **NEW** `jbhntr_engine_demo/` (demo engine) | Canned scan/score/generate so the public app runs standalone |
| `README.md`, `LICENSE` (stays MIT for existing public code), `requirements-web.txt`, `Procfile`, `railway*.json`, `nixpacks.toml`, `.env.example`, `docs/` | Already public / ops |

### PRIVATE — `jbhntr/jbhntr-engine` (package `jbhntr_engine`)

| Path | Why private (the moat) |
|---|---|
| `jobhunter/sources/` (all: adzuna, keyed, boards, ats, careers_scrape, agency_hints, browser_sniff, custom_sites, exa, linkedin, remoteok, remotive, arbeitnow, base) | **Connectors + which sources + how to scrape** — the coverage advantage |
| `jobhunter/matcher.py` (incl. `_triage_system_prompt`, `_system_prompt`, `_user_prompt`, `PROMPT_VERSION`) | **Ranking + triage prompts** — the core IP |
| `jobhunter/generator.py` | CV/cover-letter generation prompts |
| `jobhunter/criteria.py`, `tags.py` | Criteria + tag vocabulary = the triage taxonomy |
| `jobhunter/dedup.py` | Dedup + dedup-upgrade heuristics |
| `jobhunter/discover.py`, `seeds.py` | Company discovery + seed corpus |
| `jobhunter/candidate.py` | Candidate/company-profile derivation prompts |
| `jobhunter/pipeline.py`, `apply.py`, `detect_ats.py`, `feedback.py` | Engine orchestration / CLI |
| `jobhunter/embeddings.py`, `geo.py` | Ranking infra + geo mapping (engine logic) |
| `jobhunter/llm.py` | *Borderline — see note.* The wrapper is generic, but `STYLE_RULES` + the two-tier policy ship here with the prompts |
| `jobhunter/config.py` | Engine-side `Settings`/`Profile`/`Materials`/`load_companies` |
| `jobhunter/gdrive.py` | Engine's Drive helper (shell has its own `gdocs.py`) |
| `jobhunter/sources/*`-coupled tests: `test_ats.py`, `test_dedup.py`, `test_discover.py`, `test_matcher.py`, `test_criteria.py`, `test_candidate.py`, `test_tags.py`, `test_keyed.py`, `test_geo.py`, `test_embeddings.py`, `test_llm.py`, `test_pipeline.py`, `test_seeds.py`, `test_models.py`, `test_text.py` | Engine tests move with the engine |
| **Ingestion lanes** (`web/app/services/ingest.py`, `reaper.py`, `corpus_service.py`, `enrich_service.py`, `aggregator_calibrate.py`, `companies_service.py`, `cron.py`, `score_cache.py`, `panel.py`, `cv_vision.py`, `term_localize.py`, `profile_service.py`'s engine-calling parts) | **These live in `web/app/services` today but are engine logic** — they orchestrate sources/scoring/corpus. Either move into the engine package or keep in the shell as thin callers of the façade. **Decision needed (§7 risk).** Recommendation: move the source/score/ingest internals into the engine, keep a thin shell wrapper that owns the DB session. |

**Referral anti-abuse heuristics:** not built yet (`referral.py` only mints codes + rewards). When built, the *heuristics* (velocity/fraud scoring) go in the private engine; the code-minting stays public.

## 4. (b) Interface boundary — the façade

Define `jbhntr_engine` with a **stable, documented top-level API** — contract first (the types are the documentation). The shell imports only these top-level names; never a submodule.

```python
# jbhntr_engine/__init__.py  — the ONLY surface the shell may import
from .types import JobPosting, MatchResult, RankedJob, Profile, TIER_LABELS, tier_for_score
from .api import (
    build_profile,          # CV + targets -> Profile
    run_scan,               # Profile + corpus handle -> list[RankedJob]  (the daemon-thread entrypoint)
    score_jobs,             # Profile + [JobPosting] -> [MatchResult]
    ingest,                 # refresh corpus from sources (cron)
    discover_companies,     # seeds -> verified companies (cron)
    generate_documents,     # Profile + RankedJob -> CV + cover letter
    PROMPT_VERSION,         # opaque cache-busting token the shell passes to score_cache
    ENGINE_KIND,            # "real" | "demo"  — read by the boot guard
)
```

Design rules (from `api-and-interface-design`):
- **Contract first, addition over modification.** New capability = new optional arg or new function, never a changed signature. The shell pins one engine version (One-Version Rule).
- **DB stays in the shell.** The engine takes/returns plain dataclasses and a corpus *handle* (a narrow read/write port the shell implements against Postgres); the engine never imports `web.app.db`. This keeps the engine host-agnostic and testable.
- **Validate at the boundary.** Engine output (and third-party source responses inside it) is validated against the `types` schemas before the shell renders or stores it — LLM/source output is untrusted (`security-and-hardening` LLM05).
- **No leaked internals.** `_is_generic_remote`, `_slugify`, `FETCHERS` etc. become private to the engine; the 78 sites are rewritten to call façade functions. This is the migration's main diff.
- **`types` is the shared contract.** `JobPosting`/`MatchResult`/`RankedJob`/`Profile`/tier helpers move from `jobhunter/models.py` into `jbhntr_engine/types.py`. The demo engine and the real engine both import from it, so the shell's type imports resolve identically either way.

The **demo engine** (`jbhntr_engine_demo`, public) implements the exact same `__init__` surface with canned data and `ENGINE_KIND = "demo"`. `pip install jbhntr-engine` (private) shadows/replaces it in prod.

## 5. (c) Build changes — real engine at build, refuse silent demo fallback

1. **Packaging.** Private engine ships as `jbhntr-engine` (wheel) from a private index / Git source. Prod install (edit `railway.json` `buildCommand`):
   ```
   pip install -r requirements-web.txt
   pip install "jbhntr-engine @ git+https://x-access-token:${ENGINE_READ_TOKEN}@github.com/jbhntr/jbhntr-engine@<pinned-sha-or-tag>"
   ```
   `ENGINE_READ_TOKEN` is a **read-only, least-privilege** deploy token in Railway env (never in the repo; `security-and-hardening` secrets rule). Pin a tag/sha — not a branch — so a build is reproducible (One-Version Rule).
2. **Resolution order.** `import jbhntr_engine` resolves to the real package when installed, else to the public demo shim. The demo package is a separate dist (`jbhntr-engine-demo`) so a failed private install can't be masked by a stale real wheel.
3. **Boot guard — reuse the existing hard-fail.** `main.py` already refuses to boot prod on weak secrets (`config.validate()` → `RuntimeError`). Add one line to the same lifespan check:
   ```python
   from jbhntr_engine import ENGINE_KIND
   if ENGINE_KIND != "real" and not config.debug:
       raise RuntimeError("Refusing to start: demo engine in production (private engine not installed)")
   ```
   Same mechanism, same place, so the guard can't be "forgotten" — it rides the proven path. `ENGINE_KIND` is set by the package that wins import, not by env, so it can't be spoofed by a stray env var.
4. **`/health`** stays a liveness probe; the engine-kind assertion is the boot guard, not the healthcheck (a demo build should never reach `running`).
5. **CI.** Public repo CI runs shell tests against the **demo** engine (no token needed — contributors can run everything). A separate private-engine CI runs the engine tests. A prod-parity job (token-gated) installs the real engine and runs the integration slice.

## 6. (d) Licence recommendation

- **Existing public code stays MIT.** The current `LICENSE` is MIT (© Ettore Strapazzon). Anything already published under MIT **remains MIT** — you cannot retroactively un-MIT shipped code, and we don't want to. Credit stays as-is (README/LICENSE/commits/humans.txt), per Charter principle 1.
- **New shell-specific source-available licence: recommend BSL 1.1.** Reasoning:
  - **BSL 1.1** lets anyone read, modify, and self-host for non-production/eval, forbids offering it as a competing hosted service, and **auto-converts to a true open-source licence (we pick Apache-2.0) after a set Change Date (recommend 3 years)**. It is purpose-built for exactly "open for trust and contribution, closed against a hosted clone", and the time-bomb conversion is a credibility signal.
  - **Elastic 2.0** also blocks hosted-competitor use but **never converts to open source** and is less familiar to individual devs; weaker as an inbound/credibility play.
  - For a wedge product whose value is the (private) engine, BSL's "you can run it, you can't resell it as a service, and it opens up eventually" fits the open-core intent best.
  - **The engine repo is not licensed for the public at all** — all-rights-reserved / proprietary, private access only.
  - **Caveat (GC owns):** licence choice + the BSL "Additional Use Grant" + Change Date wording are a legal decision. GC drafts; an Italian-lawyer session before public launch confirms (GTM §7). Not legal advice.

## 7. (e) Step order

Ordered so the product never breaks and each step is reversible until the last.

1. **Build the façade in the monorepo first (no repos split yet).** Create `jbhntr_engine` (top-level API over existing `jobhunter/` internals) + `types.py`. Rewrite the 78 shell import sites to use the façade. Decide ingest/corpus/reaper placement (§3 risk). Full suite green. *This is the real work and is safe — it's a refactor inside one repo.*
2. **Build the demo engine** (`jbhntr_engine_demo`) implementing the same surface with canned data. Shell runs + screenshots with the private code absent. Add the boot guard (§c3).
3. **Carve the private package** `jbhntr-engine` out of `jobhunter/` + the engine-side services, as its own buildable wheel. Prove `pip install` + real-engine boot locally and in a token-gated CI job.
4. **Fresh squashed public snapshot.** New public history for `jbhntr/jbhntr` = shell + demo engine only, **squashed to one commit** so no engine code or secret ever appears in public git history. Verify: `git log -p` carries no `jobhunter/sources`, no prompts, no `.env`. (Attribution lines on the snapshot commit per house rule.)
5. **Archive the old repo as private `jbhntr/jbhntr-legacy`.** Keep full history private; it is the provenance record and the rollback target. Public repo starts clean.
6. **Point production at the split.** Railway `web` + `cron` build from public `jbhntr/jbhntr` and `pip install` the pinned private engine with `ENGINE_READ_TOKEN`. First deploy is the real cut-over; watch the boot guard.
7. **Publish** the public repo + README pointer; GC's licence files land in the same commit.

## 8. (f) Risks + rollback

| Risk | Mitigation / rollback |
|---|---|
| **Façade misses a needed call; a shell path breaks** | Step 1 is a same-repo refactor behind full tests; nothing ships until green. The 78-site inventory (§2) is the checklist. |
| **Ingest/corpus/reaper placement wrong** | Decide in Step 1 *before* carving. Recommendation: engine owns source/score/ingest internals; shell keeps the thin DB-owning wrapper. Reversible while still one repo. |
| **Secret/engine leaks into public history** | Fresh **squashed** snapshot (Step 4) + `git log -p` + secret-scan gate before first public push. Old history stays in private `-legacy` only. |
| **`ENGINE_READ_TOKEN` compromised** | Least-privilege read-only token; rotate in Railway; it grants read to one private repo, nothing else. If leaked: rotate first, then audit. |
| **Prod silently runs demo (the headline failure)** | Boot guard (§c3) hard-fails prod on `ENGINE_KIND != "real"`; separate demo dist can't mask a failed real install; demo build can't reach `running`. |
| **Private install flaky at build → deploy fails** | Pin a tag/sha (reproducible); Railway `restartPolicy` + healthcheck catch a bad build; **rollback = redeploy the previous Railway build** (still on the old monorepo until Step 6, so pre-cutover rollback is "don't merge the cutover"). |
| **BSL deters contributors / wrong licence** | GC + lawyer review before launch; MIT code stays MIT regardless; licence is data in files, changeable before the public push. |
| **Contributor can't run the app** | Demo engine means the public repo runs end-to-end with zero private access — the point of Step 2. |

## 9. REQUEST items (for the Founder, via the CEO → REQUESTS.md)

These need the Founder and block **execution** (not this plan). Listed self-contained:

- **REQUEST (R-ENG-ORG):** Create the GitHub org/repos: public `jbhntr/jbhntr`, private `jbhntr/jbhntr-engine`, private `jbhntr/jbhntr-legacy` (archive of the current repo). Confirm the org name to use in build commands.
- **REQUEST (R-ENG-TOKEN):** Create a **read-only** deploy token / fine-grained PAT scoped to `jbhntr/jbhntr-engine` **read-only, contents only**, and add it to Railway as `ENGINE_READ_TOKEN` on both the `web` and `cron` services. Do **not** put it in any file or chat — set it in the Railway dashboard. (Agents never create accounts/tokens — Charter guardrail 1.)
- **REQUEST (R-ENG-LICENCE):** Approve the licence direction — **BSL 1.1 (Change Date +3 years → Apache-2.0) for the public shell, proprietary for the engine, existing MIT code stays MIT** — subject to GC draft + an Italian-lawyer session before public launch.
- **REQUEST (R-ENG-GO):** Approve executing Steps 1–3 (the in-repo façade + demo engine + private-package carve) next cycle. Steps 4–7 (the public snapshot + cut-over) come back for a separate go after Steps 1–3 are green.

---
Skills used: api-and-interface-design, security-and-hardening, engineering:architecture, task-observer.
