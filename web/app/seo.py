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
# Add "/how-it-works", "/security", "/pricing", "/compare/linkedin-jobs" when
# those pages ship; add "/job-sources" and "/about" in the second pass.
PUBLIC_PATHS: tuple[str, ...] = ("/", "/privacy", "/terms", "/cookies")


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
