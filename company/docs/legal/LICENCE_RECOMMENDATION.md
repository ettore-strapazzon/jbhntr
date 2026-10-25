# Open-Core Licence Recommendation — public `jbhntr/jbhntr` shell

Owner: GC (with CTO) · v1 (2026-10-25) · Feeds R-002 and R1-06 (REPO_SPLIT_EXECUTION_PLAN). Not legal advice — confirm with the lawyer at the pre-launch session.

## Recommendation: **BSL 1.1** (Business Source License 1.1) for the public shell + demo engine.

**Reasoning (one paragraph).** Both BSL 1.1 and Elastic License 2.0 are source-available (not OSI "open source" — call it "source-available", C5) and both block the one outcome we actually care about: a competitor taking our public code and standing up a rival hosted JBHNTR. The real engine (sources, prompts, dedup, anti-abuse, corpus) stays in the private repo regardless of licence, so the public licence only has to protect the shell/demo. **BSL 1.1 fits better** for three reasons: (1) its "Additional Use Grant + change date" model lets us write a precise non-compete restriction — "no competing hosted job-search/matching service" — while still permitting almost all other use (self-hosting, learning, internal use), which is friendlier to the developer goodwill and contribution we want from the open-core GTM than Elastic 2.0's blunter "you may not provide it as a managed service" ban; (2) the automatic **change date** (each version converts to a true OSI licence — e.g. Apache 2.0 — after a set period, typically 2–4 years) is a credible good-faith signal to the community that ages well and pre-empts "fake open source" criticism, whereas Elastic 2.0 never converts; (3) BSL is well-understood, has a standard parameterised template (Licensor, Change Date, Change License, Additional Use Grant), and is widely precedented (MariaDB, Sentry, CockroachDB, HashiCorp), so the lawyer review is cheap. Elastic 2.0 is simpler to drop in and marginally stronger as a flat anti-SaaS clause, so it is the acceptable fallback if we want zero parameters to tune — but BSL's tailored grant + conversion is the better match for a community-facing open-core play. **Either way:** code already released under MIT stays MIT to whoever already has it; the new licence governs only from the split commit forward, and value accrues to the private engine, not the public shell.

**Parameters to set if BSL 1.1 is adopted (for R1-06 / the lawyer):**
- **Licensor:** [the incorporated entity, once formed] — another reason to incorporate before the split matters (R-007).
- **Change Date:** e.g. 3 years from each release.
- **Change License:** Apache License 2.0.
- **Additional Use Grant:** permit all use except offering a competing hosted job-search / job-matching service to third parties.

Skills used: legal:legal-risk-assessment, legal:compliance-check.
