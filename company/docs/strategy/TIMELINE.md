# Roadmap & Gantt — JBHNTR Team

Owner: CEO · Updated 2026-10-25 · Target: **1,000 activated users** by ~week 13 (end Jan 2027), USD 1,000 budget.
Week 1 = 2026-10-27. Dates are planning anchors; the CEO re-plans if < 150 activated at week 7.

## Milestones
| # | Milestone | When | Gate to pass |
|---|---|---|---|
| M1 | Step 1 shipped: match card + market read + /invite + measurement; repo-split plan approved | end wk 3 (~11-16) | artefacts live, OG images render, measurement on every link |
| M2 | Step 2 live: brand accounts + directories + comparison pages + daily digest + 2 wks karma | end wk 4 (~11-23) | first data post live, digest arriving daily |
| M3 | Step 3 gate: ≥100 activated, ≥40 interviews, gate read 2 cohorts | end wk 6 (~12-07) | ≥60% "better" → unlock partnerships |
| M4 | Spikes: data drop + Show HN | wk 7–8 (~12-08…12-21) | top-3 complaints fixed, 100+ real users |
| M5 | Step 4: partnerships (coaches, cohorts, tools, newsletters) | wk 7+ | partner page + stat live |
| M6 | Phase 2: paid credit top-ups | when gate holds + K≥0.3 | break-even model approved |
| 🎯 | **1,000 activated users** | ~wk 13 (end Jan 2027) | — |

Activation checkpoints: **≥100** wk6 · **≥300** wk9 · **≥600** wk12.

## Gantt
```mermaid
gantt
    title JBHNTR Phase 1 — to 1,000 activated users
    dateFormat YYYY-MM-DD
    axisFormat %d %b
    todayMarker on

    section Build (CTO+CPO)
    Match card + market read + /invite      :b1, 2026-10-27, 14d
    Measurement plumbing + gate prompt       :b2, 2026-10-27, 10d
    BI dashboard (live metrics)              :b3, 2026-11-03, 10d
    Repo-split plan -> execute               :b4, 2026-10-27, 21d
    Comparison pages x4                      :b5, 2026-11-10, 14d
    Fix interview top-3                      :b6, 2026-11-24, 10d
    Demo profile for HN                      :b7, 2026-12-08, 7d

    section Growth (CMO)
    Brand accounts + directories             :g1, 2026-10-27, 7d
    Reddit karma (link-free)                 :g2, 2026-10-27, 14d
    Daily draft digest                       :g3, 2026-10-29, 90d
    UK/IE communities + first data post      :g4, 2026-11-10, 14d
    EU communities                           :g5, 2026-11-24, 14d
    Referral loop on                         :g6, 2026-11-10, 14d
    Data drop #1 + press                     :g7, 2026-12-08, 7d
    Show HN + US communities                 :g8, 2026-12-15, 7d
    Partner outreach (coaches/cohorts)       :g9, 2026-12-08, 28d

    section Conversations (Founder + CPO)
    LinkedIn 1:1 PMF interviews              :c1, 2026-11-10, 42d
    In-product interview prompt              :c2, 2026-11-17, 56d

    section Gates (CEO)
    Step-3 gate: >=100 activated             :milestone, m3, 2026-12-07, 0d
    Show HN                                   :milestone, m4, 2026-12-16, 0d
    1,000 activated                           :milestone, goal, 2027-01-26, 0d
```

Swimlane owners: **Build** CTO/CPO · **Growth** CMO · **Conversations** Founder (LinkedIn) + CPO (in-product) · **Gates** CEO. GC clears claims/compliance across all; CFO approves spend.
