"""Public SEO context and structured-data helpers (Guide v2, FND-003 / SEO-*).

Dependency-free. Every value here is a constant or derived from config.base_url —
never from the incoming request URL (tracking params and alternate hosts would
create duplicate canonicals) and never from user, profile or job-result data
(schema must not carry private text).
"""

from __future__ import annotations

from typing import Any

from .config import config

DEFAULT_TITLE = "JBHNTR | AI Job Search Agent Across Job Boards and Career Pages"
DEFAULT_DESCRIPTION = (
    "JBHNTR scans job boards and company career pages, scores fit in both "
    "directions and returns a reasoned shortlist of jobs worth reviewing."
)
PUBLIC_ROBOTS = (
    "index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1"
)
PRIVATE_ROBOTS = "noindex,nofollow,noarchive"

# The canonical set of public, indexable pages. The sitemap is generated from
# this tuple, not from route introspection, so private routes can never leak in.
# Add "/job-sources" and "/about" in the second pass.
PUBLIC_PATHS: tuple[str, ...] = (
    "/", "/how-it-works", "/security", "/pricing", "/compare/linkedin-jobs",
    "/privacy", "/terms", "/cookies",
)

# Homepage FAQ. Defined once so the visible <details> block and the FAQPage
# JSON-LD render from the same strings and can never drift (SEO-006 / HOME-010).
FAQ_PAIRS: tuple[tuple[str, str], ...] = (
    ("What is JBHNTR?",
     "JBHNTR is an AI job-search agent. It scans job boards and company career "
     "pages, filters and ranks roles against your profile, and returns a "
     "shortlist with the reasons for and against each match."),
    ("Where does JBHNTR search?",
     "It uses broad job feeds, niche and remote boards, and direct employer "
     "career pages, including ATS platforms such as Greenhouse, Lever and Ashby. "
     "Coverage varies by country, sector and source availability."),
    ("Does JBHNTR scrape LinkedIn?",
     "No. The public product does not scrape LinkedIn. It relies on other job "
     "sources, aggregators and employer career pages."),
    ("How does matching work?",
     "JBHNTR first applies hard constraints such as location and working mode, "
     "then uses semantic retrieval to find relevant work beyond exact titles. "
     "The strongest candidates are assessed in two directions: how well the role "
     "fits what you want and how well your background fits the requirements."),
    ("Does JBHNTR apply automatically?",
     "No. It helps you find and evaluate roles and can draft application "
     "materials. You review the original posting, edit every draft and submit the "
     "application yourself."),
    ("How fresh are the jobs?",
     "The shared job corpus is refreshed on a schedule and tracks when listings "
     "were last seen. JBHNTR also removes dead or stale listings where its checks "
     "identify them, but no aggregator can guarantee that every employer page is "
     "updated immediately."),
    ("Who can see my CV?",
     "Your profile is private by default. Employers and recruiters cannot browse "
     "it. The services required to operate JBHNTR process career text as "
     "described in the Privacy Policy; any future recruiter discoverability "
     "feature must be explicit and optional."),
    ("Can JBHNTR guarantee that a job is still open?",
     "No. Always verify the original employer posting before applying. JBHNTR "
     "tracks freshness and checks listings, but employers and job sources can "
     "change without notice."),
    ("Is JBHNTR for a particular profession?",
     "No. The profile supports different sectors, seniority levels, company "
     "types, contract types and locations. Result quality still depends on source "
     "coverage in your market and the detail in your profile."),
    ("What will Premium add?",
     "Premium is planned to add automatic recurring scans, more frequent "
     "freshness, useful digests and expanded application workflow. The free "
     "product uses the same core approach and is intended to be good enough to "
     "judge the product honestly."),
)


def origin() -> str:
    return config.base_url.rstrip("/")


def absolute_url(path: str = "/") -> str:
    path = "/" + path.lstrip("/")
    return origin() + path


def public_seo(*, title: str, description: str, path: str,
               og_title: str | None = None,
               og_description: str | None = None,
               schema: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Template context that marks a page public + indexable and gives it its
    own title, description, canonical and Open Graph fields."""
    return {
        "meta_title": title,
        "meta_description": description,
        "canonical_url": absolute_url(path),
        "meta_robots": PUBLIC_ROBOTS,
        "og_title": og_title or title,
        "og_description": og_description or description,
        "og_url": absolute_url(path),
        "structured_data": schema or [],
    }


# --- structured data (schema.org) ------------------------------------------ #
# Built only from constants and config; safe to embed as JSON-LD.

def organization_schema() -> dict[str, Any]:
    same_as = [config.repo_url] if config.repo_url else []
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": config.site_name,
        "url": absolute_url("/"),
        "logo": absolute_url("/static/logo.svg"),
        "founder": {"@type": "Person", "name": config.founder_name},
        "sameAs": same_as,
    }


def website_schema() -> dict[str, Any]:
    # No SearchAction: JBHNTR has no public site search.
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": config.site_name,
        "url": absolute_url("/"),
        "description": (
            "An AI job-search agent that scans job boards and company career "
            "pages and returns a reasoned shortlist."
        ),
    }


def software_application_schema() -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": config.site_name,
        "applicationCategory": "BusinessApplication",
        "applicationSubCategory": "Job search software",
        "operatingSystem": "Web",
        "url": absolute_url("/"),
        "description": (
            "JBHNTR scans job boards and company career pages, then ranks each "
            "role against both what the candidate wants and what the employer "
            "requires."
        ),
        "featureList": [
            "Cross-source job search",
            "Semantic job retrieval",
            "Two-way fit scoring",
            "Reasons for and against each match",
            "Tailored CV and cover-letter drafts",
            "Application tracking",
        ],
        "offers": {
            "@type": "Offer",
            "price": "0",
            "priceCurrency": "USD",
            "description": (
                "A limited number of complete searches are available free; no "
                "payment card is required."
            ),
        },
    }


def faq_schema(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    """FAQPage built from the exact visible Q/A strings on the page."""
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            }
            for q, a in pairs
        ],
    }
