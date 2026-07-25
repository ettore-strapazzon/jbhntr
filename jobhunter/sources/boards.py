"""Niche and vertical job boards, via their public RSS / JSON feeds.

The big aggregators are generalists. Vertical boards (crypto/web3, remote-exec,
etc.) carry roles that never reach them, so a small registry of verified feeds
adds real coverage for almost no cost.

Every entry below was checked against the live feed. Boards that block
automated access are listed in UNAVAILABLE with the reason, so nobody wastes
time re-adding them.

Add your own in profile.yaml without touching code:

    sources:
      boards: [cryptocurrencyjobs, weworkremotely]     # from the registry
      custom_rss:                                       # any other RSS feed
        - url: https://example.com/jobs.rss
          name: Example
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from html import unescape
from typing import Any, Optional
from urllib.parse import quote
from xml.etree import ElementTree

from ..config import Profile, Settings
from ..models import JobPosting
from .base import http_client, strip_html

log = logging.getLogger("jobhunter.sources.boards")

# --------------------------------------------------------------------------- #
# Verified feeds. `vertical` is informational — it helps you pick.
# --------------------------------------------------------------------------- #
BOARDS: dict[str, dict[str, Any]] = {
    "cryptocurrencyjobs": {
        "type": "rss",
        "url": "https://cryptocurrencyjobs.co/index.xml",
        "vertical": "crypto / web3",
        "title_format": "role_at_company",
    },
    "weworkremotely": {
        "type": "rss",
        "url": "https://weworkremotely.com/remote-jobs.rss",
        "vertical": "remote, all sectors (large)",
        "title_format": "company_colon_role",
    },
    # Category-filtered variant — far higher signal for strategy/ops/exec
    # profiles than the firehose above.
    "weworkremotely-management": {
        "type": "rss",
        "url": "https://weworkremotely.com/categories/remote-management-and-finance-jobs.rss",
        "vertical": "remote, management & finance",
        "title_format": "company_colon_role",
    },
    "landingjobs": {
        "type": "rss",
        "url": "https://landing.jobs/feed",
        "vertical": "European tech (Atom feed)",
        "company_from_url": r"landing\.jobs/at/([^/]+)/",
    },
    "berlinstartupjobs": {
        "type": "rss",
        "url": "https://berlinstartupjobs.com/feed",
        "vertical": "Berlin/EU startups",
        "title_format": "role_slashes_company",
        # The feed carries no location field, but the board is Berlin-only.
        # Without this every listing looked location-less and slipped past the
        # location filter.
        "default_location": "Berlin, Germany",
    },
    "fourdayweek": {
        "type": "rss",
        "url": "https://4dayweek.io/feed",
        "vertical": "remote, 4-day-week companies",
    },
    "realworkfromanywhere": {
        "type": "rss",
        "url": "https://realworkfromanywhere.com/rss.xml",
        "vertical": "fully location-independent",
    },
    "nodesk": {
        "type": "rss",
        "url": "https://nodesk.co/remote-jobs/index.xml",
        "vertical": "remote, curated",
        "title_format": "role_at_company",
    },
    "himalayas": {
        "type": "json",
        "url": "https://himalayas.app/jobs/api",
        "vertical": "remote, all sectors",
        "root": "jobs",
        "map": {
            "title": "title",
            "company": "companyName",
            "description": "description",
            "url": "applicationLink",
            "date": "pubDate",
            "location_list": "locationRestrictions",
        },
    },
    "jobicy": {
        "type": "json",
        "url": "https://jobicy.com/api/v2/remote-jobs?count=100&industry=management",
        "vertical": "remote, management-filtered "
                    "(drop &industry= for all sectors)",
        "root": "jobs",
        "map": {
            "title": "jobTitle",
            "company": "companyName",
            "description": "jobDescription",
            "url": "url",
            "date": "pubDate",
            "location": "jobGeo",
        },
    },
    # --- Official aggregator APIs (no key required) --------------------- #
    "themuse": {
        "type": "json",
        # Curated companies; `category` filters hard so we skip engineering noise.
        "url": "https://www.themuse.com/api/public/jobs?page=0&location={location}"
               "&location=Flexible%20%2F%20Remote",
        "vertical": "curated companies (query-driven)",
        "root": "results",
        "map": {
            "title": "name",
            "company": "company.name",
            "description": "contents",
            "url": "refs.landing_page",
            "date": "publication_date",
            "location_list_of_dicts": "locations",
        },
    },
    "arbeitsagentur": {
        # Germany's federal employment agency — very large, free, documented
        # public client key (see jobsuche.api.bund.dev).
        "type": "json",
        "url": "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
               "?was={search}&size=50",
        "vertical": "Germany (federal agency, query-driven)",
        "root": "stellenangebote",
        "headers": {"X-API-Key": "jobboerse-jobsuche"},
        "map": {
            "title": "titel",
            "company": "arbeitgeber",
            "description": "beruf",
            "date": "aktuelleVeroeffentlichungsdatum",
            "location_nested": "arbeitsort",
        },
        "url_template": {
            "field": "refnr",
            "pattern": "https://www.arbeitsagentur.de/jobsuche/jobdetail/{}",
        },
    },
    "workingnomads": {
        "type": "json",
        "url": "https://www.workingnomads.com/api/exposed_jobs/",
        "vertical": "remote, all sectors",
        "root": None,  # top-level list
        "map": {
            "title": "title",
            "company": "company_name",
            "description": "description",
            "url": "url",
            "date": "pub_date",
            "location": "location",
        },
    },
}

# Checked and NOT usable — kept so nobody wastes time re-adding them.
# (Probed for /feed, /rss, /jobs.rss, /index.xml, /feed.xml, /api/jobs, /rss.xml.)
UNAVAILABLE = {
    # Web3
    "cryptojobslist.com": "Cloudflare challenge (403)",
    "web3.career": "no public feed; API needs a paid token",
    "sailonchain.com": "JavaScript-rendered only",
    "remote3.co": "no public feed",
    # Italy / country boards — none expose a usable feed
    "infojobs.it": "no feed (HTML only)",
    "subito.it": "RSS retired (HTTP 410)",
    "trovolavoro.it": "no feed",
    "thelocal.it": "no feed (404)",
    # Executive
    "theladders.com": "no public feed",
    "execthread.com": "no public feed (invite-only)",
    "ivyexec.com": "no usable feed (HTML)",
    "6figurejobs.com": "connection timeout",
    "bluesteps.com": "no public feed",
    # Startups / generic
    "startup.jobs": "no public feed",
    "wellfound.com": "no public feed (login required)",
    "workatastartup.com": "login required (YC)",
    "eu-startups.com": "blocks automated access (403)",
    "indeed.com": "no free API; scraping prohibited by ToS",
    "glassdoor.com": "no free API",
    "jooble.org": "API key required (free tier on request)",
    "otta.com": "no public feed (login required)",
    "builtin.com": "no public feed",
    # Verticals
    "ai-jobs.net": "no public feed on standard paths",
    "efinancialcareers.com": "no public feed",
    "climatetechlist.com": "no public feed",
    "nextleveljobs.eu": "no public feed",
    "eures.europa.eu": "no RSS at documented path",
}


# --------------------------------------------------------------------------- #
def _split_title(raw: str, fmt: Optional[str]) -> tuple[str, str]:
    """Return (title, company) from a combined feed title."""
    raw = unescape(raw or "").strip()
    if fmt == "role_at_company" and " at " in raw:
        role, _, company = raw.rpartition(" at ")
        return role.strip(), company.strip()
    if fmt == "company_colon_role" and ":" in raw:
        company, _, role = raw.partition(":")
        return role.strip(), company.strip()
    if fmt == "role_slashes_company" and "//" in raw:
        role, _, company = raw.rpartition("//")
        return role.strip(), company.strip()
    return raw, ""


def _parse_date(value) -> Optional[Any]:
    if not value:
        return None
    text = str(value)
    for parse in (
        lambda t: datetime.fromisoformat(t.replace("Z", "+00:00")).date(),
        lambda t: datetime.strptime(t[:25], "%a, %d %b %Y %H:%M:%S").date(),
        lambda t: datetime.strptime(t[:10], "%Y-%m-%d").date(),
    ):
        try:
            return parse(text)
        except Exception:
            continue
    return None


def _rss_items(raw: bytes) -> list[dict[str, str]]:
    """Parse RSS into plain dicts, tolerating malformed feeds.

    Real-world feeds are frequently invalid XML (undeclared namespace prefixes,
    stray ampersands). A strict parse would drop the whole feed over one bad
    character, so fall back to regex extraction when ElementTree refuses.
    """
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        text = raw.decode("utf-8", errors="ignore")
        items = []
        tag = "entry" if "<entry" in text else "item"
        for chunk in re.findall(rf"<{tag}[^>]*>(.*?)</{tag}>", text, re.S | re.I):
            fields: dict[str, str] = {}
            for tag in ("title", "link", "guid", "description", "summary",
                        "content", "pubDate", "published", "updated",
                        "region", "location", "author", "name"):
                m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", chunk, re.S | re.I)
                if m:
                    val = re.sub(
                        r"^<!\[CDATA\[(.*?)\]\]>$", r"\1", m.group(1).strip(), flags=re.S
                    )
                    key = {
                        "summary": "description", "content": "description",
                        "published": "pubdate", "updated": "pubdate",
                    }.get(tag.lower(), tag.lower())
                    fields.setdefault(key, val.strip())
            # Atom links are self-closing: <link href="..."/>
            if not fields.get("link"):
                m = re.search(r'<link[^>]*href="([^"]+)"', chunk, re.I)
                if m:
                    fields["link"] = m.group(1)
            if fields.get("title"):
                items.append(fields)
        return items

    items = []
    # RSS uses <item>; Atom (e.g. landing.jobs) uses <entry>.
    entries = list(root.iter("item")) or [
        e for e in root.iter() if e.tag.split("}")[-1] == "entry"
    ]
    for item in entries:
        fields: dict[str, str] = {}
        for el in item:
            tag = el.tag.split("}")[-1].lower()  # drop any namespace
            text = (el.text or "").strip()
            # Atom puts the URL in <link href="...">, not in the element text.
            if tag == "link" and not text:
                text = el.attrib.get("href", "")
            if tag in ("summary", "content"):
                tag = "description"
            if tag in ("published", "updated"):
                tag = "pubdate"
            if text and tag not in fields:
                fields[tag] = text
        if fields.get("title"):
            items.append(fields)
    return items


def _location_from_description(desc: str) -> str:
    """Recover a location when the feed has no location field.

    Many RSS boards state it only in the body ("100% remote", "based in Milan").
    Without this the posting looks location-less and bypasses the location
    filter entirely.
    """
    if not desc:
        return ""
    low = desc[:600].lower()

    if re.search(r"100%\s*remote|fully remote|remote[- ]first|work remotely from anywhere",
                 low):
        if "no geographical restriction" in low or "from anywhere" in low:
            return "Remote, Worldwide"
        return "Remote"

    m = re.search(r"\b(?:based in|located in|office in|hiring in)\s+"
                  r"([A-Z][\w.\-]+(?:\s+[A-Z][\w.\-]+){0,2})", desc[:600])
    if m:
        return m.group(1).strip(" .,")

    if "remote" in low:
        return "Remote"
    return ""


def _company_from_description(desc: str) -> str:
    """Some feeds only name the company inside the body text."""
    for pattern in (
        r"^\s*([A-Z][\w&.\-' ]{2,40}?)\s+is (?:looking|hiring|seeking)",
        r"(?:Headquarters|Company)\s*:\s*([\w&.\-' ]{2,40})",
    ):
        m = re.search(pattern, desc)
        if m:
            return m.group(1).strip()
    return ""


def _fetch_rss(name: str, cfg: dict) -> list[JobPosting]:
    with http_client(timeout=25.0) as c:
        r = c.get(cfg["url"])
        r.raise_for_status()
        raw = r.content

    out: list[JobPosting] = []
    for fields in _rss_items(raw):
        title, company = _split_title(fields.get("title", ""), cfg.get("title_format"))
        if not title:
            continue
        description = strip_html(unescape(fields.get("description", "")))
        # Fall back to " at Company" in the title, then the body, so boards that
        # don't split it out still get a company (needed for cross-source dedup).
        if not company:
            _, company = _split_title(fields.get("title", ""), "role_at_company")
        if not company:
            company = _company_from_description(description)
        url = fields.get("link") or fields.get("guid", "")
        # Last resort: some boards only name the company in the job URL path.
        if not company and cfg.get("company_from_url"):
            m = re.search(cfg["company_from_url"], url)
            if m:
                company = m.group(1).replace("-", " ").strip().title()
        location = (fields.get("region") or fields.get("location") or "").strip()
        if not location:
            location = _location_from_description(description) or cfg.get(
                "default_location", ""
            )
        out.append(
            JobPosting(
                source=f"board:{name}",
                title=title,
                company=company,
                location=location,
                description=description,
                url=url,
                posted_date=_parse_date(fields.get("pubdate")),
            )
        )
    return out


def _dig(obj: dict, path: str):
    """Read a possibly-nested field: 'company.name' or 'refs.landing_page'."""
    cur = obj
    for part in (path or "").split("."):
        if not isinstance(cur, dict):
            return ""
        cur = cur.get(part)
        if cur is None:
            return ""
    return cur


def _location_from(j: dict, m: dict) -> str:
    """Sources describe location in several shapes; normalise them all."""
    if m.get("location"):
        val = _dig(j, m["location"])
        if val:
            return str(val)
    if m.get("location_list"):  # ["Europe", "UK"]
        vals = j.get(m["location_list"]) or []
        if isinstance(vals, list):
            return ", ".join(str(v) for v in vals)
        return str(vals)
    if m.get("location_list_of_dicts"):  # [{"name": "Milan, Italy"}]
        vals = j.get(m["location_list_of_dicts"]) or []
        if isinstance(vals, list):
            return ", ".join(
                str(v.get("name", "")) for v in vals if isinstance(v, dict)
            )
    if m.get("location_nested"):  # {"ort": "Berlin", "region": "..."}
        val = j.get(m["location_nested"]) or {}
        if isinstance(val, dict):
            return ", ".join(
                str(val[k]) for k in ("ort", "region", "land") if val.get(k)
            )
        return str(val)
    return ""


def _fetch_json(name: str, cfg: dict) -> list[JobPosting]:
    with http_client(timeout=25.0) as c:
        r = c.get(cfg["url"], headers=cfg.get("headers") or None)
        r.raise_for_status()
        data = r.json()

    items = data if cfg.get("root") is None else data.get(cfg["root"], [])
    m = cfg["map"]
    out: list[JobPosting] = []
    for j in items:
        if not isinstance(j, dict):
            continue
        title = str(_dig(j, m["title"]) or "").strip()
        if not title:
            continue
        url = str(_dig(j, m.get("url", "")) or "").strip()
        if not url and cfg.get("url_template"):
            key = str(_dig(j, cfg["url_template"]["field"]) or "")
            url = cfg["url_template"]["pattern"].format(key) if key else ""
        out.append(
            JobPosting(
                source=f"board:{name}",
                title=title,
                company=str(_dig(j, m.get("company", "")) or "").strip(),
                location=_location_from(j, m).strip(),
                description=strip_html(unescape(str(_dig(j, m.get("description", "")) or ""))),
                url=url,
                posted_date=_parse_date(_dig(j, m.get("date", ""))),
            )
        )
    return out


# Boards where every listing is remote by definition. Their location text often
# says "Europe" or a city with no mention of "remote", so the flag is the only
# reliable signal.
REMOTE_ONLY = {
    "weworkremotely", "weworkremotely-management", "jobicy", "workingnomads",
    "nodesk", "himalayas", "fourdayweek", "realworkfromanywhere",
}


def _fetch_one(name: str, cfg: dict) -> list[JobPosting]:
    jobs = _fetch_rss(name, cfg) if cfg["type"] == "rss" else _fetch_json(name, cfg)
    if name in REMOTE_ONLY:
        for j in jobs:
            j.is_remote = True
    return jobs


MAX_QUERY_TERMS = 4  # per board, to bound requests


def _fetch_with_queries(name: str, cfg: dict, profile: Profile) -> list[JobPosting]:
    """Run a board, expanding {search}/{location} from the profile.

    Query-driven APIs (The Muse, Arbeitsagentur) return whatever you ask for, so
    driving them from your own search terms and locations is far higher signal
    than a hardcoded query.
    """
    url = cfg["url"]
    if "{search}" not in url and "{location}" not in url:
        return _fetch_one(name, cfg)

    # Prefer real city names; the "Remote-XX" tokens aren't valid queries.
    cities = [l for l in profile.locations if not l.lower().startswith("remote")]
    location = quote(cities[0]) if cities else ""
    terms = profile.search_terms[:MAX_QUERY_TERMS] or [""]

    out: list[JobPosting] = []
    for term in terms:
        cfg_run = dict(cfg)
        cfg_run["url"] = url.replace("{search}", quote(term)).replace(
            "{location}", location
        )
        try:
            out.extend(_fetch_one(name, cfg_run))
        except Exception as exc:
            log.warning("Board %s query %r failed: %s", name, term, exc)
    return out


def fetch(profile: Profile, settings: Settings) -> list[JobPosting]:
    jobs: list[JobPosting] = []

    for name in profile.boards:
        cfg = BOARDS.get(name)
        if cfg is None:
            log.warning(
                "Unknown board %r — available: %s", name, ", ".join(sorted(BOARDS))
            )
            continue
        try:
            found = _fetch_with_queries(name, cfg, profile)
            jobs.extend(found)
            log.info("Board %s: %d postings", name, len(found))
        except Exception as exc:
            log.warning("Board %s failed: %s", name, exc)

    for entry in profile.custom_rss:
        url = entry.get("url")
        if not url:
            continue
        name = entry.get("name") or url
        try:
            found = _fetch_rss(name, {"url": url, "title_format": entry.get("title_format")})
            jobs.extend(found)
            log.info("Custom RSS %s: %d postings", name, len(found))
        except Exception as exc:
            log.warning("Custom RSS %s failed: %s", name, exc)

    return jobs


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Verified boards:")
    for n, c in sorted(BOARDS.items()):
        print(f"  {n:22} {c['type']:5} {c['vertical']}")
    print("\nChecked and unusable:")
    for n, why in UNAVAILABLE.items():
        print(f"  {n:22} {why}")
