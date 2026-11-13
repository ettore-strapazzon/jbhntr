"""Per-page data for the /compare/{slug} pages (R3-08).

One shared template (marketing/compare.html) renders every entry here. The copy is
taken verbatim from company/docs/marketing/COMPARE_COPY.md as cleared/revised by GC
(2026-10-28) and the GC source pass R3-12 (2026-11-13), with the bracketed review
annotations stripped. Do not edit a competitor cell here without the same GC
clearance and a fresh dated source check (Compliance Card C4).

Deliberately absent:
- "teal": its "Last reviewed" date waits on Founder request R-012 (Teal blocks
  automated reads), so /compare/teal must stay a 404 until GC dates it.
- Indeed: its "Apply for me" status is HELD (no readable dated source), so it is
  named nowhere on the auto-apply page, including the sources list.
"""

from __future__ import annotations

from typing import Any

REVIEWED_ON = "13 November 2026"        # set by GC in R3-12; shown on every page
REVIEWED_ISO = "2026-11-13"

DISCLOSURE = ("Disclosure: we build a tool in this space. JBHNTR is our product, "
              "so read this as a vendor's comparison.")

CTA = [("Start a free scan", "/signup", "btn"),
       ("How matching works", "/how-it-works", "btn ghost")]

COMPARE_PAGES: dict[str, dict[str, Any]] = {
    "jobright": {
        "title": "JBHNTR vs Jobright | AI Job Search Tools Compared",
        "description": (
            "Jobright is an AI job-search assistant with an agent that can apply "
            "for you. JBHNTR scores each role in both directions and stops at the "
            "shortlist. Where they differ."),
        "h1": "JBHNTR and Jobright, compared",
        "competitor": "Jobright",
        "lede": (
            "Jobright is an AI job-search assistant with a matching feed, resume "
            "tailoring, and an agent that can apply to roles for you. JBHNTR reads "
            "across many sources and scores each role in both directions, then stops "
            "at the shortlist and leaves the applying to you. The two tools make the "
            "opposite bet about where your effort pays off: automating the applying, "
            "or sharpening the deciding."),
        "rows": [
            ["Automating the application",
             "Offers an AI apply/agent flow and resume tailoring, strong if volume is the goal",
             "No auto-apply by design; we return the few worth a considered application"],
            ["Fit signal",
             "A match score toward each role",
             "Two scores, role fit and requirements fit, with the reasons for and against"],
            ["Where roles come from",
             "Its own large job board",
             "25+ sources, including direct employer career pages"],
            ["Geography",
             "US market focus",
             "EU and UK first, every geography open; our GDPR posture is deliberate"],
            ["Privacy and openness",
             "Proprietary",
             "Source-available shell on GitHub, matching engine private; your profile private by default"],
        ],
        "sections": [
            ("When Jobright is the better tool", [
                "If you want to send a high volume of applications quickly and want "
                "the tool to do the applying, an apply agent does something we "
                "deliberately do not. JBHNTR makes the opposite bet: fewer, "
                "better-chosen applications that you send yourself. Pick Jobright when "
                "throughput is the point. Pick JBHNTR when the problem is deciding "
                "which roles are worth your time at all."]),
        ],
        "sources": [
            ("Jobright AI agent", "https://jobright.ai/ai-agent"),
            ("Jobright autofill and resume tailoring", "https://jobright.ai/job-autofill"),
            ("Jobright match score", "https://jobright.ai/ai-job-match"),
            ("Jobright Terms of Service", "https://jobright.ai/legal/service"),
            ("Jobright job search", "https://jobright.ai/"),
            ("Jobright H1B jobs", "https://jobright.ai/h1b-jobs"),
        ],
    },
    "simplify": {
        "title": "JBHNTR vs Simplify | Job Search Tools Compared",
        "description": (
            "Simplify autofills applications and also has its own job search. "
            "JBHNTR works a step earlier: it decides which roles are worth applying "
            "to at all, with reasons."),
        "h1": "JBHNTR and Simplify, compared",
        "competitor": "Simplify",
        "lede": (
            "Simplify is a browser extension that autofills and speeds up "
            "applications across job boards, with a tracker alongside it. It also has "
            "its own job search with AI matching and a separate auto-apply product. "
            "JBHNTR works a step earlier: it decides which roles are worth applying "
            "to at all, with reasons, before you spend effort on any of them. One "
            "tool makes applying faster. The other makes you apply less."),
        "rows": [
            ["Speed of applying",
             "One-click autofill on supported career sites and application systems, "
             "plus a separate AI auto-apply product",
             "We do not fill or submit applications; we choose which few deserve one"],
            ["Where it acts in the funnel",
             "Mainly at the application step; it also has a job search",
             "At the decision step, before you apply"],
            ["Fit signal",
             "AI job matching in its job search",
             "A two-way fit score with the reasons for and against"],
            ["Coverage",
             "Its own job search, plus autofill on the career sites you visit",
             "We scan 25+ sources for you, including career pages you would not check"],
            ["Control",
             "Built to cut the time per application; its Autopilot product can submit "
             "applications for you",
             "Built so you apply deliberately; nothing is sent without you"],
        ],
        "sections": [
            ("When Simplify is the better tool", [
                "If you have already chosen the roles and want to cut the time per "
                "application, an autofill extension saves real minutes on every form. "
                "JBHNTR does not speed applying up. It reduces how many applications "
                "you need to send in the first place, which is a different kind of "
                "saving. Use both and they stack: pick the shortlist with us, fill the "
                "forms faster with Simplify."]),
        ],
        "sources": [
            ("Simplify Copilot extension", "https://simplify.jobs/copilot"),
            ("Simplify home page", "https://simplify.jobs/"),
            ("Simplify product summary (llms.txt)", "https://simplify.jobs/llms.txt"),
        ],
    },
    "auto-apply-tools": {
        "title": "JBHNTR vs Auto-Apply Tools | Shortlist or Mass-Apply",
        "description": (
            "Auto-apply tools send applications for you, at volume. JBHNTR returns "
            "the short list of roles actually worth applying to and leaves the "
            "applying to you."),
        "h1": "JBHNTR and auto-apply tools",
        "competitor": "Auto-apply tools",
        "lede": (
            "Auto-apply tools send applications for you, at volume. JBHNTR is a "
            "deliberate bet against that. We return the short list of roles actually "
            "worth applying to and leave the applying to you. Here is the honest case "
            "for each approach, so you can decide which problem you are trying to "
            "solve."),
        "rows": [
            ["What they are great at",
             "Throughput: hundreds of applications with little effort",
             "Precision: the few roles worth a considered application"],
            ["How fit is judged",
             "Filters such as role, location, salary and keywords, to send "
             "applications fast",
             "A two-way fit score with the reasons for and against"],
            ["Platform rules",
             "Mass-apply can run against platform terms, for example LinkedIn's terms "
             "on automated activity",
             "We never apply on your behalf, so there is nothing to run against the rules"],
            ["Effect on the recruiter side",
             "A high volume of low-fit applications can weaken how you are received",
             "Fewer, better-targeted applications protect your signal"],
        ],
        "sections": [
            ("Our position", [
                "We think most of the value is in the first handful of well-chosen "
                "applications, not the hundredth. Automating more of them optimises "
                "the wrong number. We optimise which few to send. That is the whole "
                "bet, and it is why we will never add an apply agent."]),
            ("When an auto-apply tool is the better choice", [
                "If you have decided that casting the widest possible net is your "
                "strategy, and you accept the platform-terms risk that can come with "
                "it, a mass-apply tool does that at a scale no human can. We are "
                "built for the opposite candidate: the mid-senior professional who "
                "would rather send fifteen strong applications than three hundred "
                "weak ones."]),
        ],
        # Indeed deliberately absent (HELD). Sonara deliberately absent (status
        # unverified in R3-12). Add a product only after a fresh dated GC check.
        "sources": [
            ("LazyApply plans", "https://lazyapply.com/"),
            ("LazyApply pricing", "https://lazyapply.com/pricing"),
            ("LoopCV home page", "https://www.loopcv.pro/"),
            ("LoopCV pricing", "https://www.loopcv.pro/pricing"),
            ("AIApply home page", "https://aiapply.co/"),
            ("LinkedIn User Agreement, section 8.2",
             "https://www.linkedin.com/legal/user-agreement"),
            ("LinkedIn Help: prohibited software and extensions",
             "https://www.linkedin.com/help/linkedin/answer/a1341387"),
        ],
    },
}

# Every live comparison, in display order, for the cross-links block. The LinkedIn
# page has its own template (compare_linkedin_jobs.html) and is listed here too.
COMPARE_LINKS: tuple[tuple[str, str], ...] = (
    ("/compare/linkedin-jobs", "JBHNTR vs LinkedIn Jobs"),
    ("/compare/jobright", "JBHNTR vs Jobright"),
    ("/compare/simplify", "JBHNTR vs Simplify"),
    ("/compare/auto-apply-tools", "JBHNTR vs auto-apply tools"),
)

COMPARE_PATHS: tuple[str, ...] = tuple(f"/compare/{s}" for s in COMPARE_PAGES)
