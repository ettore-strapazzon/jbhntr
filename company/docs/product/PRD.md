# PRD — JBHNTR

Owner: CPO · v1 (2026-10-25) · The product requirements; CPO keeps it current as flows change.

## What it is
An AI job-search agent for mid-senior professionals. It scans every live role across many sources, evaluates each against the user's profile in **two directions** — "fits what you want" and "you fit what they need" — and returns the 10–20 worth a decision, each with reasons **for and against**. It then helps tailor a CV and cover letter per role and tracks applications. **Never auto-apply** — the user stays in control. Live at jbhntr.app (FastAPI + Jinja + HTMX, Postgres, Railway).

## Who it's for
See GTM §1 — mid-senior generalists, UK/IE → EU → US → Canada. Not junior, not deep-specialist.

## Core value & differentiators
1. **Two-way fit with reasons** — not a relevance list; the honest "1,840 roles, 14 worth it".
2. **Direct career-page coverage** — roles title-only alerts miss.
3. **No auto-apply** — a decision tool, not a spray tool; this is also the ethical/positioning line.
4. **Credits, first scan free** — no card to try; frictionless.
5. **GDPR posture** — a selling point vs US-centric competitors.

## The flow (north-star = activation: profile ≥70% + ≥1 search)
1. **Sign up** (first scan free, no card) → 2. **Profile** (CV upload + targets/preferences; the activation bar is ≥70% complete) → 3. **Scan** (background job; "my market read" summarises the funnel) → 4. **Matches** (scored cards, two-way fit, reasons, sort/filter, date added) → 5. **Save to My Jobs / track** (stages, dates, notes; bulk-draft CVs/CLs) → 6. **Tailor** (per-role CV + cover letter, editable, export PDF/DOCX) → 7. **Gate prompt** (post-scan: "vs how you search today") → 8. **Invite** (referral loop).

## Phase-1 product priorities (serve the funnel; GTM §4)
| Priority | Why | KPI it moves |
|---|---|---|
| **Shareable match card** `/m/{short_id}` + OG/PNG + referral embed | the growth loop | K-factor, signups |
| **"My market read"** `/r/{short_id}` (funnel + rejection histogram) | the repeatable sentence; impossible for auto-apply tools | signups, shares |
| **/invite page** + live counter | turns activation into referrals | K-factor |
| **Measurement plumbing** (source field, UTM, /go, gate prompt) | nothing scales without attribution | all |
| **BI dashboard** (live) | the Founder/CPO see drop-offs | activation rate |
| **Profile completion + first-scan frictionlessness** | the activation bar itself | activation rate |

## Product principles
- Remove friction, don't add chrome (first scan free, profile in minutes, 1-click share/invite, mobile-first).
- One metric per change; A/B test where traffic allows, best-practice default where it doesn't.
- Keep the gate prompt in the flow — it's both a KPI and a product surface.
- The matching engine (sources, prompts, ingestion, dedup, anti-abuse) moves to the private repo in the open-core split; the shell + demo engine stays public.

## Already shipped (reconcile in cycle 1, don't rebuild)
Two-way fit scoring + reasons; credits economy (first scan free, priced CV/CL + scans); Matches with score/tier pills, sort (incl. date added), filters; My Jobs tracker with stages, dates (added/saved), bulk-draft CVs/CLs; CV/CL generation + editor (bold/italic/underline, fonts) + PDF/DOCX export; `/compare/linkedin-jobs`; daily digest/ingestion; `/admin`; email via Resend; scan-recovery on restart. **Not yet built:** the three share artefacts, the full measurement plumbing, the live BI dashboard, the open-core split.
