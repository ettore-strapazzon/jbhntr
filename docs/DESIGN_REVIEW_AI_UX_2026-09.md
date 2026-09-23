# JBHNTR — UI/UX & AI-UX Review + Improvement Proposal

_2026-09-22 · reviewed against live code (`web/app/templates`, `static/app.css`, `app.js`) and the running app: landing (light/dark/mobile), how-it-works, My Jobs, and the job-card / document / scan-progress components._

---

## 0. Verdict first

The visual system is **already good** — Brand v3 is a real, three-tier token system with self-hosted type, a disciplined mono "connective tissue," dark mode, elevation, motion tokens, and genuine accessibility (focus ring, skip link, `aria-live`, reduced-motion). This is **not** an AI-generated-looking site, and the copy is unusually honest and well-judged.

So this is an **elevation**, not a rescue. The gap is no longer "make it look designed." It is:

1. **A handful of concrete craft cracks** (one is a real clipping bug).
2. **A fragmented "vocabulary of judgement"** — the product's whole promise is *judgement*, yet the words and visuals for it differ on every surface.
3. **The AI experience is under-expressed.** The intelligence is real (two-way fit, reasons, provenance in the engine via `source_hint`, semantic retrieval) but the UI shows the *output* far more than the *reasoning, confidence, and control* that would make an AI product feel trustworthy and alive. This is the biggest opportunity and where most of this proposal lives.

The brand position I am holding constant throughout: **honest broker, judgement over volume, two-way fit, candidate control, calm/editorial, "a reasoned shortlist, not a feed."** Every proposal below serves that, not fashion.

---

## 1. What is already working (do not touch)

- **Token architecture** (`app.css` `:root`): primitives → semantic → component. Keep as the contract for everything below.
- **The two-way fit card** (`job_card.html`): score/100, tier chip, two directional bars, Fits / Watch-out reasons, JD disclosure, triage. This is the product's best idea, well built.
- **The scan waiting state** (`partials/progress.html`): determinate stage rail with live counts and "continues if you close the tab." Genuinely reassuring — a model for the rest of the AI UX.
- **Distinct empty states** (`partials/results.html`): four different reasons, each with one action. Rare and correct.
- **The honesty block** and the "first draft, verify every claim" framing on documents. This is brand equity — we will give it *more* UI teeth, not less.

---

## 2. Findings & proposals — AI-UX (the spine)

> Principle: an AI product earns trust by showing its **reasoning**, its **confidence**, its **sources**, and by giving the user **control that visibly changes the next result**. JBHNTR has all four in the engine. The UI currently surfaces mainly the answer.

### AX-1 · Carry the *verdict* onto the card (highest impact)
The landing page teaches a beautiful mental model — the two-way fit **quadrant**: _Apply now / Worth a stretch / Watch out / Not shown_ (`landing.html` `.fit-band`). The actual match cards never use it. They show a tier number + label + two bars, and leave the *synthesis* to the reader.

**Propose:** make the quadrant verdict the card's headline judgement. Derive it from the two fit scores the card already has (`fit_role`, `fit_candidate`):
- both high → **Apply now**
- role fits you, you don't fit yet → **Worth a stretch**
- you fit, role doesn't fit you → **Watch out**

Render it as a single confident line above the bars, colour-mapped, with the numeric tier demoted to secondary. This is the one place **apricot (`--accent-warm` = "judgement")** should own — the decision moment. It ties landing promise → product reality in one stroke, and it is nearly free (the data is on `r`).

### AX-2 · Unify the vocabulary of judgement (consistency = trust)
Right now the judgement lexicon is **three different sets**:

| Surface | Words used |
|---|---|
| Landing hero / flow | Best match · Strong match · Worth a look |
| Matches filter chips | Apply now · Strong · Possible · Long shots |
| Landing fit-band verdict | Apply now · Worth a stretch · Watch out · Not shown |

A user who learns "Worth a stretch" on the landing page never sees it again; they meet "Possible" and "Long shots" instead. For a product whose entire value is *a trustworthy verdict*, the words for the verdict must be **one lexicon** everywhere: landing, tier labels, filter chips, empty-state skeletons, emails. Pick one set (recommend the fit-band's, since it encodes the two-way model) and repoint `tier_label`, the filter labels, and the marketing copy to it.

### AX-3 · Show provenance — "why this is on your list"
The engine knows *where* a candidate came from (`source_hint: exa | llm`, the source string, semantic vs constraint match) but the card only shows a raw `Source: …` line. Users trust an agent that can say **why it surfaced something**.

**Propose:** a quiet, expandable "Why this is here" affordance on the card — one line: _"Found via a company similar to [seed] · matched on payments + Milan · cleared your must-haves."_ No new engine work for v1; assemble it from fields already on `r` (source, tags, the reasons). It converts an opaque ranking into a defensible one.

### AX-4 · Confidence, not just score
A score of `78/100` reads as false precision. The model has uncertainty (thin profile, unverified link, sparse JD). The card already flags `link unverified`; extend the idea: a subtle **confidence cue** on the score (e.g. a lower-confidence score reads muted with a "based on a short JD" tooltip). Ties directly to the existing profile-strength nudge in `matches.html`. Prevents the score from over-promising — which *is* the brand ("scores help you prioritise; they are not a prediction you'll be hired").

### AX-5 · Generation should feel like drafting, not a spinner
The scan has a gorgeous staged progress rail; the **document generation** has a blank overlay ("Creating your tailored CV… up to a minute"). Same problem, worse solution. Mirror the scan pattern: a 3-beat staged line — _Reading your CV → Matching the posting → Writing the draft_ — reusing the `.loadbar` + `.stage-rail` components. The infrastructure exists; this is mostly reuse.

### AX-6 · Give the honesty promise UI teeth (verify-the-claims)
The product promises "verify every role, date, metric and claim." Today that is prose above a plain textarea. Make it operational: after generation, **highlight the AI-produced specifics** (numbers, dates, employer claims) in the editor as "verify" chips the user clicks to acknowledge. This is the single most brand-defining AI-UX move available — it turns "we're honest about hallucination" from a disclaimer into a *feature no competitor has_. (v1 can be a heuristic pass over the draft text; it does not need model support.)

### AX-7 · Make refine a first-class conversation
The refine box is excellent but blank-page. Add **suggested refine chips** — _Shorter · More technical · Lead with [most-relevant role] · Warmer tone_ — that pre-fill the feedback box. It teaches users the tool is steerable and turns the refine loop into the product's "chat with the agent" moment without building a chat UI.

### AX-8 · Close the feedback loop visibly
Ratings, dismiss reasons, saves, and applications already feed the next scan (per `landing.html` "Learns what you reject"). The user never sees that happen. A one-line acknowledgement after a dismiss/rating — _"Noted — this shapes your next scan"_ — makes the agent feel like it's *learning with you*, which is the emotional core of an AI product.

---

## 3. Findings & proposals — brand & visual craft

### V-1 · [BUG] Hero-card score clips the second digit (P0)
In dark mode the hero card scores render **"9" and "8"** instead of "92"/"78" — the score column has zero safety margin, so the ~15px layout shift from the scrollbar clips the last digit (`.hero-card-num` / `.hero-card-dim`). Same fragility will bite three-digit `100`. **Fix:** give the number a `min-width` (≈`3ch`, tabular) and `flex-shrink:0`, and verify the in-app `.fitbar` score column too. Cheap, real, visible on the marketing page.

### V-2 · Apricot should map to "judgement," and only that
`--accent-warm` (apricot) is documented as "judgement" and used in ~4 scattered places. Give it **one owned job**: the verdict moment (AX-1) and the decision CTAs. An accent that maps 1:1 to a brand concept reads as intent; scattered, it reads as decoration. This is a *reduction*, not an addition.

### V-3 · Logged-out mobile header is bulky
On mobile the logged-out nav wraps to ~3 rows (How it works / Credits / Security / Log in, then the pill, then the toggle) — a tall, ragged header before the hero. Collapse the logged-out mobile nav into the same disclosure pattern the logged-in view already has, or drop secondary links to the footer on small screens.

### V-4 · Mono discipline
The mono face is the brand's signature — keep it strictly on **data** (scores, tiers, counts, eyebrows, numerals). Audit for drift; every non-data use of mono dilutes the signal. (Currently close; this is guard-rail, not repair.)

### V-5 · Card action density
The My Jobs card mixes verbs and pricing tersely: _"Draft tailored CV · 3"_, _"10 credits · later versions 1"_. The `· 3` reads as cryptic. Spell the unit once ("· 3 credits") and let the persistent credits pill carry the balance; the card shouldn't restate the economy in shorthand.

---

## 4. Cross-cutting

- **Accessibility:** tier meaning is carried by colour + label (good), but the fit **bars are `aria-hidden`** with the number only in `.sr-only` on the main score — make sure both directional fit values are announced, not just the composite. Verify AA contrast of the five tier chip colours in both themes (the dark tier palette flips to navy text — spot-check tier-4/5).
- **Lexicon/UX copy:** one pass to unify judgement words (AX-2), credit phrasing (V-5), and the "My Jobs / Your Jobs" naming (the toast says "Your Jobs," the nav says "My Jobs").
- **Motion:** the reveal/funnel/count-up system is strong. Extend the count-up to the **in-app score** on first paint and the fit bars filling — the same delight the hero gets, on the real cards, reinforces "a considered result just arrived."
- **Responsive:** desktop/read/operate are solid; the only rough edge found was the logged-out mobile header (V-3).

---

## 5. Prioritised roadmap

**P0 — cracks (hours, ship immediately)**
- V-1 hero-card score clipping (+ audit in-app fit column)
- AX-2 start: unify tier `tier_label` ↔ filter labels ↔ marketing to one lexicon
- V-5 credit-copy clarity; "My/Your Jobs" naming

**P1 — AI-UX, high impact (the real work)**
- AX-1 verdict on the card (derive from existing fit scores) — _do this first, it anchors everything_
- AX-3 "why this is here" provenance line
- AX-5 staged generation progress (reuse scan components)
- AX-7 refine chips

**P2 — brand & trust deepening**
- AX-6 verify-the-claims highlighting (brand-defining; scope as its own slice)
- AX-4 confidence cue on scores
- AX-8 feedback-loop acknowledgement
- V-2 apricot = judgement, consolidated

**P3 — polish**
- V-3 mobile header, V-4 mono audit, motion extension, a11y bar announcements

---

## 6. Design-system additions this implies

Small, additive — all resolve through existing tokens:

- **`.verdict`** component: the two-way judgement line (label + colour by quadrant), apricot-anchored. Shared by landing fit-band and the real card.
- **`.provenance`** disclosure: quiet one-line "why this is here" (reuse `<details>`/`.desc` styling).
- **`.confidence`** cue: a muted-score modifier + tooltip pattern.
- **`.refine-chips`**: chip row reusing existing `.fchip`/`.tag` styling, pre-filling the refine box.
- **generation-progress**: reuse `.loadbar` + `.stage-rail` for AX-5 (no new component, just a second caller).

No new dependency, no new colour, no framework. The system already carries this.

---

## 7. Recommendation

Start with **AX-1 (verdict on the card)** and **P0**. AX-1 is the highest ratio of brand payoff to effort in the whole list: it uses data already on the card, unifies the landing promise with the product, and gives apricot its meaning — one change that makes the product visibly *judge* rather than *list*. From there, the P1 AI-UX slice is what turns a well-designed job tool into something that feels like an agent working for you.

I can take any slice from here into implementation — say which, and I'll ship it behind the same test discipline as the rest of the app.
