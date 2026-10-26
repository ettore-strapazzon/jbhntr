# Privacy / Terms Notes — JBHNTR

Owner: GC · v2 (2026-10-26) · Drafts and notes to feed `/privacy` and `/terms`, plus incorporation and name/trademark steps. (v2: controller paragraph finalised per Founder decision **R-005**; `/terms` now drafted in `TERMS_DRAFT.md`.)

> **Not legal advice; a one-hour session with an Italian lawyer before public launch is worth it.** JBHNTR is a multi-country product (UK+IE → EU → US → Canada) processing personal data (profiles, CVs, emails) of individuals in the EU/EEA and elsewhere, so GDPR/UK GDPR apply regardless of where we host. The drafts below are a starting point to be confirmed by counsel.

## 1. Named controller + privacy@ paragraph (FINAL per R-005 — for /privacy and /terms)

**Founder decision R-005 (2026-10-26):** no incorporation until revenue is needed (≈ before Phase-2 paid credits). So **during the private beta the data controller is Ettore Strapazzon personally** (sole trader). The entity version below is the swap-in for the moment incorporation happens (at revenue / Phase 2). The Founder has accepted the residual controller liability this puts on the individual until then (R-007 downgraded to "accepted until revenue/Phase-2" in the risk register).

### 1a. Private-beta controller paragraph (USE NOW — until incorporation)

> **Who is responsible for your data.** JBHNTR is operated by **Ettore Strapazzon** ("we", "us"), **[registrant address]**, as the **data controller** for the personal data you provide when you use JBHNTR. (JBHNTR is a small project currently run by an individual; it will move to a company before any paid service launches, and we will update this notice.) You can reach us about privacy, your data, or any request to access, correct, delete, or port your data at **privacy@jbhntr.app**. We respond to data-subject requests within 30 days (GDPR / UK GDPR). You also have the right to lodge a complaint with your local data protection authority (in Italy, the **Garante per la protezione dei dati personali**; in the EU, your national DPA; in the UK, the **ICO**).

### 1b. Post-incorporation controller paragraph (SWAP IN at revenue / Phase 2)

> **Who is responsible for your data.** JBHNTR is operated by **[LEGAL ENTITY NAME]** ("we", "us"), **[registered office address]**, **[company registration number / VAT]**, which is the **data controller** for the personal data you provide when you use JBHNTR. [...rest identical to 1a: privacy@ contact, 30-day DSAR, DPA-complaint rights.]

### 1c. "What we do with it" (both versions)

> **What we do with it.** We use the information in your profile and CV to scan live job listings and produce your two-way fit shortlist. We do not sell your personal data. We do not apply to jobs on your behalf. [List processors: hosting — Railway; email — Resend; job-data providers — [names]. Each is bound by a data-processing agreement.] Where your data is processed outside the EEA/UK, we rely on [adequacy / Standard Contractual Clauses].

**Honest-terms requirement — before `/privacy` or `/terms` goes live to any cohort beyond friends (GTM §12.2; gate kept by R-005):**
- A **named controller is live** — Ettore personally now (1a), the entity once formed (1b). No un-named/placeholder controller shown to users.
- `privacy@jbhntr.app` mailbox **actually created and monitored**.
- Lawful basis documented per processing activity (consent/contract/legitimate interest).
- DPAs on file with Railway, Resend, and each job-data provider.
- Transfer mechanism confirmed for any non-EEA processing (hosting region, US providers).
- `/terms` carries the matching operator identity + the liability / acceptable-use / "no auto-apply / no scraping via us" sections (drafted in **`TERMS_DRAFT.md`**, 2026-10-26).

**Residual exposure (accepted by Founder, R-005):** naming Ettore personally as controller (1a) puts controller liability on the individual, and the public footer identifies him during the data-drop / Show-HN spikes (R-007). The Founder has accepted this until revenue/Phase-2; `/privacy`, `/terms`, the data drop and Show HN stay **gated on a named controller being live** and on the honest-terms checklist above.

## 2. Incorporation timing (note — updated per R-005)
- **When (R-005):** **at revenue / before Phase-2 paid credits** — the Founder has decided *not* to incorporate earlier, and **accepts that the public spikes (data drop + Show HN) may happen before incorporation**, with controller liability + public footer sitting on Ettore personally in the interim (R-007, now "accepted until revenue/Phase-2"). GC's standing advice remains that incorporating before the spikes would remove that exposure, but the Founder has weighed and accepted it.
- **Why:** incorporating (an Italian **SRL/SRLS**, or whatever the lawyer advises) moves product liability, data-controller status, and contract/ToS exposure off Ettore personally onto the entity. It's the single biggest reduction of the Founder's personal exposure (R-007, RED).
- **What it unlocks:** a real controller name for /privacy and /terms; the ability to sign DPAs and partner agreements as an entity; a clean home for the trademark.
- **Who:** only the Founder (with an Italian commercialista/lawyer) can do this. Steps are in the REQUEST below.

## 3. Name / trademark steps (note)
- **Domain:** enable **WHOIS privacy** on jbhntr.app now (hides Ettore's personal registrant details from public WHOIS — a cheap, immediate personal-exposure reduction).
- **Clearance before public launch:** search **TMview** (EU/international), **EUIPO** (EU trade marks), **USPTO TESS** (US — since US is in scope), and **UIBM** (Italy) for conflicting marks on "JBHNTR" / "JobHunter"-type marks in the relevant classes (software/SaaS — Nice class 42, maybe 9/35). Confirm no blocking prior mark **before** investing further in the brand (R-009).
- **Registration:** once incorporated and cleared, consider filing an EU trade mark (and US, given scope) in the entity's name. Lawyer advises on classes and timing.
- **Caveat:** trademark clearance/registration is a legal judgement — the lawyer confirms the search results and whether to file.

## 4. REQUEST: (Founder / lawyer only — no agent can do these)
File as a single self-contained item in `company/state/REQUESTS.md`:

1. **Enable WHOIS privacy on jbhntr.app** (via the domain registrar's privacy setting). *Reply: done / not available.*
2. **Book a one-hour session with an Italian lawyer/commercialista** before public launch, to cover: (a) incorporating an SRL/SRLS before Phase 2/the spikes; (b) confirming the data-controller + privacy/terms drafts above; (c) trademark clearance + whether to file an EU (and US) mark for "JBHNTR". *Reply: booked for [date] / provide entity name + address + reg number once formed.*
3. **Create and monitor privacy@jbhntr.app.** *Reply: created.*
4. **Run (or have the lawyer run) the TMview / EUIPO / USPTO / UIBM clearance** on "JBHNTR". *Reply: clear / conflict found: [detail].*
5. **Provide, once incorporated:** legal entity name, registered office address, registration/VAT number — to fill the `[...]` placeholders in /privacy and /terms. *Reply: [values].*

Skills used: legal:compliance-check, legal:legal-risk-assessment.
Skills considered but not used: product-legal:marketing-claims-review (no marketing claim on this surface).
