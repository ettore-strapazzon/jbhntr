"""Premium multi-model panel for CV / cover-letter generation.

A single model tailoring a CV is something any free tool does. This raises the
bar: several *diverse* OpenRouter models each draft a tailored version, a
synthesiser merges the strongest parts, and the panel then votes yes/no on the
result — revising once more until they agree (>= a threshold) or the rounds run
out. Every knob (models, rounds, threshold, synthesiser) is env-configurable.

Premium-only; free keeps the single-model path. Never raises — if the panel is
disabled or every model errors, it returns None and the caller falls back to the
normal single-model generation.
"""

from __future__ import annotations

import logging

from jobhunter import llm

log = logging.getLogger("jbhntr.panel")

_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {"content": {"type": "string"},
                   "rationale": {"type": "string",
                                 "description": "2-3 lines: why this version is strong"}},
    "required": ["content", "rationale"],
    "additionalProperties": False,
}
_VOTE_SCHEMA = {
    "type": "object",
    "properties": {"ready": {"type": "boolean",
                             "description": "true if this is genuinely application-ready"},
                   "feedback": {"type": "string",
                                "description": "the single most important fix, if not ready"}},
    "required": ["ready", "feedback"],
    "additionalProperties": False,
}
_SYNTH_SCHEMA = {
    "type": "object",
    "properties": {"content": {"type": "string"}},
    "required": ["content"],
    "additionalProperties": False,
}

_RULES = (
    "Rules, non-negotiable:\n"
    "- Never invent experience, employers, dates, titles or credentials. Use only "
    "what the candidate's materials support; re-emphasise and re-order to fit the "
    "role, never fabricate. It must be defensible line by line in an interview.\n"
    "- HONEST HEADLINE. The headline/title line and summary describe who the "
    "candidate ACTUALLY is. NEVER relabel them with the target job's title or a "
    "title they have not held just because it matches the posting — that is "
    "misrepresentation. Keep their genuine identity and seniority.\n"
    "- KEEP EACH EMPLOYER'S CONTEXT: if the source CV has a one-line description of "
    "a company under its name, keep that line.\n"
    "- REFRAME, DON'T SHORTEN. Your job is to reorder and reword the candidate's CV "
    "so the most relevant experience leads — NOT to summarise or trim it.\n"
    "- PRESERVE ALL SUBSTANCE: keep every employer, role, title and date, AND every "
    "quantified achievement the candidate states — every metric, number, percentage, "
    "monetary figure ($/EUR), deal size, team size, client/user count, market-cap and "
    "timeframe. Never drop, round away or make vague a number or an accomplishment.\n"
    "- INCLUDE EVERY position — never drop, merge or omit an employer, role or date. "
    "Keep the COMPLETE work history. Keep roughly the same depth per role as the "
    "source: do not reduce a rich role with several metric-bearing bullets to one or "
    "two generic lines.\n"
    "- The tailored CV must be at least as complete and detailed as the candidate's "
    "original. A shorter, thinner or vaguer CV than the one they uploaded is a "
    "FAILURE, however well written.\n"
    "- Write like a person, not an AI. No em/en dashes, no buzzwords, no stock "
    "phrasing (\"leverage\", \"passionate about\").\n"
    "- OUTPUT PLAIN TEXT ONLY — no markdown (**, *, _, #, backticks). Section "
    "headings on their own line in the candidate's own wording; bullets start '- '. "
    "Per employer, in order: 'Employer - Location'; then its one-line description "
    "(if any) ending in a full stop; then each position as 'Job Title (Dates)' with "
    "dates ALWAYS in parentheses (never a pipe or bare dash); then its bullets.\n"
)


def _format_guide(materials) -> str:
    """Tell the models to keep the candidate's own CV structure/formatting."""
    cv = (getattr(materials, "base_cv", "") or "").strip()
    if not cv:
        return ""
    return (
        "\n\n## Match the candidate's existing CV style\n"
        "Reproduce its FORM: the same section headings and order, the same bullet "
        "style, the same date format and layout conventions. Change the CONTENT to "
        "fit the job; keep the shape recognisably theirs.\n\n"
        "### Their current CV (for structure reference)\n" + cv[:6000]
    )


def _system(kind: str, materials) -> str:
    what = ("a tailored CV" if kind == "cv" else "a tailored cover letter")
    head = (
        f"You are an expert career writer producing {what} for a specific job, "
        "using the candidate's real background.\n" + _RULES
    )
    if kind == "cl":
        head += ("- 3-4 short paragraphs, specific to this company and role, "
                 "confident but not boastful, no clichés.\n")
    else:
        head += ("- Lead with the most relevant experience for this role and keep it "
                 "ATS-friendly — but never by removing substance.\n")
    ctx = getattr(materials, "combined_context", lambda: "")() or "(none)"
    guide = _format_guide(materials) if kind == "cv" else ""
    return head + "\n## Candidate materials\n" + ctx + guide


def _user(kind: str, job) -> str:
    return (
        f"Write {'the CV' if kind == 'cv' else 'the cover letter'} for this job.\n\n"
        f"Title: {job.title}\nCompany: {job.company}\nLocation: {job.location}\n"
        f"Description:\n{(job.description or '')[:6000] or '(no description available)'}"
    )


def _out_cap(kind: str) -> int:
    return 8000 if kind == "cv" else 4000


def _synthesise(client, system, user, drafts, feedback, model, cap) -> str:
    parts = [user, "",
             "Below are independent drafts of this document. Produce ONE final "
             "version that is the MOST COMPLETE and specific of them — the UNION of "
             "their substance, not a shortened compromise. Take the richest, most "
             "quantified phrasing available for each point. Requirements when merging "
             "a CV: keep EVERY role, employer and date that appears in ANY draft or "
             "the candidate's materials; keep EVERY distinct achievement and EVERY "
             "number/metric/figure that appears in ANY draft (if one draft states a "
             "metric another omits, KEEP the metric); match the most detailed draft's "
             "depth per role. The result must be at least as long and detailed as the "
             "longest draft. Never add anything the candidate's materials do not "
             "support, but never drop real substance either — a shorter or vaguer "
             "merge than the drafts is a failure."]
    for i, d in enumerate(drafts, 1):
        parts.append(f"\n--- Draft {i} ---\n{d}")
    if feedback:
        parts.append("\nReviewers judged the current version not yet ready. Fix:\n- "
                     + "\n- ".join(f for f in feedback if f))
    try:
        out = client.json(system=system, user="\n".join(parts), schema=_SYNTH_SCHEMA,
                          model=model, max_tokens=cap, cache_system=False)
        return (out.get("content") or "").strip() or drafts[0]
    except Exception as exc:
        log.warning("Panel synthesis failed (%s): %s", model, exc)
        return drafts[0]


def _restore(client, system, user, draft, source_cv, model, cap) -> str:
    """Last-resort guard against over-compression: rewrite a thin draft so it keeps
    every role and every quantified achievement from the candidate's original CV."""
    prompt = (
        user + "\n\nThe tailored draft below has lost substance compared with the "
        "candidate's original CV. Rewrite it so it keeps EVERY role and EVERY "
        "quantified achievement (numbers, %, $, EUR, deal/team/client sizes, "
        "timeframes) that the original contains, reworded and reordered to target "
        "this job. Add nothing the original does not support; it must end up at "
        "least as detailed as the original.\n\n"
        "--- Candidate's original CV ---\n" + (source_cv or "")[:6000] +
        "\n\n--- Tailored draft to fix ---\n" + draft
    )
    try:
        out = client.json(system=system, user=prompt, schema=_SYNTH_SCHEMA,
                          model=model, max_tokens=cap, cache_system=False)
        return (out.get("content") or "").strip() or draft
    except Exception as exc:
        log.warning("Panel restore pass failed (%s): %s", model, exc)
        return draft


def deliberate(kind: str, materials, job, settings, config) -> dict | None:
    """Run the panel. Returns {content, agreement, models, rounds} or None to
    signal the caller should fall back to single-model generation."""
    models = [m for m in (config.panel_models or []) if m]
    if not (config.panel_enabled and len(models) >= 2):
        return None

    client = llm.get_client(settings)
    system, user, cap = _system(kind, materials), _user(kind, job), _out_cap(kind)

    # Round 0 — each model drafts independently.
    drafts: list[str] = []
    for m in models:
        try:
            d = client.json(system=system, user=user, schema=_DRAFT_SCHEMA,
                            model=m, max_tokens=cap, cache_system=False)
            content = (d.get("content") or "").strip()
            if content:
                drafts.append(content)
        except Exception as exc:
            log.warning("Panel draft failed (%s): %s", m, exc)
    if not drafts:
        return None                      # every model failed -> caller falls back

    synth_model = config.panel_synth_model or models[0]
    candidate = _synthesise(client, system, user, drafts, [], synth_model, cap)

    # Rounds — vote on the candidate; revise until agreement or rounds run out.
    if kind == "cv":
        review_sys = (
            "You are a demanding reviewer of a tailored CV. It is ready only if it is "
            "truthful, honest, well-targeted, AND fully preserves the candidate's "
            "substance. Mark ready=false if ANY of these hold: (a) the headline, title "
            "line or summary claims a role or title the candidate has not actually "
            "held (e.g. it borrows the target job's title) — this is the most serious "
            "failure; (b) it drops any role or employer, or an employer's one-line "
            "description that the source has; (c) it omits quantified achievements "
            "(numbers, %, $, EUR, deal/team/client sizes, timeframes) the materials "
            "contain, or reduces a rich role to one or two generic lines; (d) it reads "
            "thinner, vaguer or shorter than a strong CV for this person would. A clean "
            "but hollow, or subtly dishonest, CV is NOT ready. Return ready=true/false "
            "and, if false, the single most important fix."
        )
    else:
        review_sys = (
            "You are a demanding reviewer of a tailored cover letter. Judge whether it "
            "is genuinely application-ready: truthful, specific to this company and "
            "role, and better than a generic AI draft. Return ready=true/false and, "
            "if false, the single most important fix."
        )
    agreement = 1.0
    for _ in range(max(0, int(config.panel_rounds))):
        votes: list[bool] = []
        fixes: list[str] = []
        for m in models:                 # one review pass gives vote + feedback
            try:
                v = client.json(system=review_sys,
                               user=f"Job: {job.title} at {job.company}\n\n"
                                    f"Document:\n{candidate[:8000]}",
                               schema=_VOTE_SCHEMA, model=m, max_tokens=600,
                               cache_system=False)
                ready = bool(v.get("ready"))
                votes.append(ready)
                if not ready and v.get("feedback"):
                    fixes.append(v["feedback"])
            except Exception:
                pass
        if not votes:
            break
        agreement = sum(votes) / len(votes)
        if agreement >= float(config.panel_threshold):
            break
        candidate = _synthesise(client, system, user, drafts, fixes, synth_model, cap)

    # Completeness guard: a tailored CV must never come out markedly thinner than
    # the source. If it did, the panel over-compressed — restore against the
    # original once. (Length is a crude proxy, but a big drop reliably means lost
    # roles/metrics, which is exactly the failure this catches.)
    if kind == "cv":
        source_cv = (getattr(materials, "base_cv", "") or "").strip()
        if source_cv and len(candidate) < 0.8 * len(source_cv):
            candidate = _restore(client, system, user, candidate, source_cv,
                                 synth_model, cap)

    return {"content": candidate, "agreement": round(agreement, 2),
            "models": len(drafts), "rounds": int(config.panel_rounds)}
