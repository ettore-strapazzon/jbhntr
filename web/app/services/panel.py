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
    "- Adjust toward the job, do not twist to match: keep every role, seniority, "
    "scope and result faithful.\n"
    "- INCLUDE EVERY position from the candidate's CV — never drop, merge or omit "
    "an employer, role or date. Keep their COMPLETE work history; tailor by "
    "re-emphasising and rewording bullets within each role, not by deleting jobs. "
    "Omitting real experience is a failure.\n"
    "- Write like a person, not an AI. No em/en dashes, no buzzwords, no stock "
    "phrasing (\"leverage\", \"passionate about\").\n"
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
        head += ("- ATS-friendly and concise; lead with the most relevant "
                 "experience for this role.\n")
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
             "version that takes the strongest, most truthful and best-written "
             "elements of each. Never add anything the candidate's materials do "
             "not support, and — for a CV — keep EVERY role/employer/date that "
             "appears in the drafts; do not drop any position when merging."]
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
    review_sys = (
        "You are a demanding reviewer of a tailored " + ("CV" if kind == "cv" else
        "cover letter") + ". Judge only whether it is genuinely application-ready: "
        "truthful, well-targeted to the job, and better than a generic AI draft. "
        "Return ready=true/false and, if false, the single most important fix."
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

    return {"content": candidate, "agreement": round(agreement, 2),
            "models": len(drafts), "rounds": int(config.panel_rounds)}
