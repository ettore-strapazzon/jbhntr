"""Company career pages, via their ATS platforms' public JSON APIs.

Most companies host their careers page on one of a handful of applicant-tracking
systems, and each exposes a clean public JSON feed per company. That is far more
reliable (and scales to thousands of companies) than scraping careers HTML.

Companies are listed in `config/companies.yaml`:

    companies:
      - name: Acme
        ats: greenhouse
        token: acme                       # the board token / company slug
      - name: Beta
        careers_url: https://jobs.lever.co/beta   # ats + token auto-detected

Detect the ats/token for a careers URL without editing files:

    python -m jobhunter.sources.ats --detect https://jobs.lever.co/beta

Every company is fetched independently in a small thread pool; one company
failing never affects the others.
"""

from __future__ import annotations

import argparse
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html import unescape
from typing import Callable, Optional
from urllib.parse import urlparse

from ..config import Profile, Settings, load_companies
from ..models import JobPosting
from .base import http_client, strip_html

log = logging.getLogger("jobhunter.sources.ats")

MAX_WORKERS = 10       # concurrent company fetches
PER_REQUEST_TIMEOUT = 15.0
WORKDAY_PAGE = 20      # Workday hard-caps a page at 20
WORKDAY_MAX_JOBS = 200 # per company, so one huge employer can't swamp a run


# --------------------------------------------------------------------------- #
# ATS detection
# --------------------------------------------------------------------------- #
# Most companies put their careers page on their own domain and embed or link
# the real board, so URL parsing alone recognised almost nothing (23 of 30
# seeds failed, including Kraken and Scalapay, which both clearly reference an
# ATS in their HTML). These find the board inside a fetched page.
_ATS_IN_HTML = [
    r"https?://(?:boards|job-boards)\.greenhouse\.io/[A-Za-z0-9_-]+",
    r"https?://[A-Za-z0-9_-]*\.?greenhouse\.io/embed/job_board\?for=[A-Za-z0-9_-]+",
    r"https?://jobs\.lever\.co/[A-Za-z0-9_-]+",
    r"https?://jobs\.ashbyhq\.com/[A-Za-z0-9_-]+",
    r"https?://[A-Za-z0-9_-]+\.recruitee\.com",
    r"https?://apply\.workable\.com/[A-Za-z0-9_-]+",
    r"https?://careers\.smartrecruiters\.com/[A-Za-z0-9_-]+",
    r"https?://[A-Za-z0-9_-]+\.bamboohr\.com",
    r"https?://[A-Za-z0-9_-]+\.wd\d+\.myworkdayjobs\.com/[A-Za-z0-9_%-]+",
    r"https?://[A-Za-z0-9_-]+\.jobs\.personio\.(?:de|com)",
]


def _sniff(careers_url: str) -> str:
    """Fetch a careers page and return the first ATS board URL it references."""
    try:
        with http_client() as client:
            resp = client.get(careers_url, follow_redirects=True)
            resp.raise_for_status()
            html = resp.text
    except Exception as exc:
        log.debug("Could not read %s: %s", careers_url, exc)
        return ""
    for pattern in _ATS_IN_HTML:
        found = re.search(pattern, html, re.I)
        if found:
            return found.group(0)
    return ""


def detect(careers_url: str, probe: bool = True) -> tuple[str, str]:
    """Map a careers URL to (ats, token). Returns ("", "") if unrecognized.

    Parses the URL first; if that says nothing and `probe` is set, reads the
    page and looks for the board it embeds or links to.
    """
    found = _detect_from_url(careers_url)
    if found != ("", "") or not probe:
        return found
    board = _sniff(careers_url)
    if not board:
        return ("", "")
    # The greenhouse embed form carries its token in the query, not the path.
    embed = re.search(r"job_board\?for=([A-Za-z0-9_-]+)", board, re.I)
    if embed:
        return ("greenhouse", embed.group(1))
    return _detect_from_url(board)


def _detect_from_url(careers_url: str) -> tuple[str, str]:
    u = careers_url.strip().rstrip("/")
    host = urlparse(u).netloc.lower()
    path = urlparse(u).path.strip("/")
    seg = path.split("/") if path else []

    def last(default: str = "") -> str:
        return seg[-1] if seg else default

    if "myworkdayjobs.com" in host:
        # nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite  (or /en-US/Site)
        bits = host.split(".")
        tenant = bits[0]
        wd = next((b for b in bits if re.fullmatch(r"wd\d+", b)), "wd1")
        site = ""
        for s in seg:
            if s.lower() in {"en-us", "en_us"} or "-" in s and len(s) == 5:
                continue
            site = s
            break
        return ("workday", f"{tenant}:{wd}:{site}") if site else ("", "")
    if "bamboohr.com" in host:
        # acme.bamboohr.com/careers
        return ("bamboohr", host.split(".")[0])
    if "greenhouse.io" in host:
        # boards.greenhouse.io/acme  |  job-boards.greenhouse.io/acme
        return ("greenhouse", seg[0]) if seg else ("greenhouse", "")
    if "lever.co" in host:
        return ("lever", seg[0]) if seg else ("lever", "")
    if "ashbyhq.com" in host:
        return ("ashby", seg[0]) if seg else ("ashby", "")
    if "recruitee.com" in host:
        # acme.recruitee.com
        return ("recruitee", host.split(".")[0])
    if "workable.com" in host:
        # apply.workable.com/acme  |  acme.workable.com
        if seg:
            return ("workable", seg[0])
        return ("workable", host.split(".")[0])
    if "smartrecruiters.com" in host:
        return ("smartrecruiters", seg[0]) if seg else ("smartrecruiters", "")
    if "personio" in host:
        return ("personio", host.split(".")[0])
    return ("", "")


# --------------------------------------------------------------------------- #
# Per-ATS fetchers — each returns a list of JobPosting
# --------------------------------------------------------------------------- #
def _greenhouse(name: str, token: str) -> list[JobPosting]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    with http_client(timeout=PER_REQUEST_TIMEOUT) as c:
        data = c.get(url, params={"content": "true"}).raise_for_status().json()
    out = []
    for j in data.get("jobs", []):
        out.append(
            JobPosting(
                source=f"ats:greenhouse:{name}",
                title=j.get("title", ""),
                company=name,
                location=(j.get("location") or {}).get("name", ""),
                description=strip_html(unescape(j.get("content", ""))),
                url=j.get("absolute_url", ""),
                posted_date=_iso_date(j.get("updated_at")),
            )
        )
    return out


def _lever(name: str, token: str) -> list[JobPosting]:
    url = f"https://api.lever.co/v0/postings/{token}"
    with http_client(timeout=PER_REQUEST_TIMEOUT) as c:
        data = c.get(url, params={"mode": "json"}).raise_for_status().json()
    out = []
    for j in data:
        cats = j.get("categories") or {}
        out.append(
            JobPosting(
                source=f"ats:lever:{name}",
                title=j.get("text", ""),
                company=name,
                location=cats.get("location", ""),
                description=j.get("descriptionPlain")
                or strip_html(j.get("description", "")),
                url=j.get("hostedUrl", ""),
                posted_date=_ms_date(j.get("createdAt")),
            )
        )
    return out


def _ashby(name: str, token: str) -> list[JobPosting]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
    with http_client(timeout=PER_REQUEST_TIMEOUT) as c:
        data = c.get(url).raise_for_status().json()
    out = []
    for j in data.get("jobs", []):
        out.append(
            JobPosting(
                source=f"ats:ashby:{name}",
                title=j.get("title", ""),
                company=name,
                location=j.get("location", ""),
                description=j.get("descriptionPlain")
                or strip_html(j.get("descriptionHtml", "")),
                url=j.get("jobUrl", ""),
                posted_date=_iso_date(j.get("publishedAt")),
            )
        )
    return out


def _workable(name: str, token: str) -> list[JobPosting]:
    """Workable: try the current v3 API, fall back to the legacy widget feed.

    NOTE: unlike the other fetchers, this one is not verified against a live
    board with open roles (every public account we could reach was empty), so
    both response shapes are parsed defensively. If a Workable company returns
    nothing, that is the likely cause.
    """
    items: list[dict] = []
    with http_client(timeout=PER_REQUEST_TIMEOUT) as c:
        try:
            r = c.post(
                f"https://apply.workable.com/api/v3/accounts/{token}/jobs",
                json={},
                headers={"Content-Type": "application/json"},
            )
            if r.status_code == 200:
                items = r.json().get("results") or []
        except Exception:
            items = []

        if not items:  # legacy widget feed
            try:
                r = c.get(
                    f"https://apply.workable.com/api/v1/widget/accounts/{token}",
                    params={"details": "true"},
                )
                if r.status_code == 200:
                    items = r.json().get("jobs") or []
            except Exception:
                items = []

    out = []
    for j in items:
        loc = j.get("location") or {}
        if isinstance(loc, dict):
            location = ", ".join(
                x for x in [loc.get("city"), loc.get("region"), loc.get("country")] if x
            )
        else:
            location = str(loc)
        shortcode = j.get("shortcode") or ""
        url = (
            j.get("url")
            or j.get("shortlink")
            or (f"https://apply.workable.com/{token}/j/{shortcode}/" if shortcode else "")
        )
        out.append(
            JobPosting(
                source=f"ats:workable:{name}",
                title=j.get("title", ""),
                company=name,
                location=location,
                description=strip_html(j.get("description") or j.get("full_description") or ""),
                url=url,
                posted_date=_iso_date(
                    j.get("published_on") or j.get("published") or j.get("created_at")
                ),
            )
        )
    return out


def _recruitee(name: str, token: str) -> list[JobPosting]:
    url = f"https://{token}.recruitee.com/api/offers/"
    with http_client(timeout=PER_REQUEST_TIMEOUT) as c:
        data = c.get(url).raise_for_status().json()
    out = []
    for j in data.get("offers", []):
        out.append(
            JobPosting(
                source=f"ats:recruitee:{name}",
                title=j.get("title", ""),
                company=name,
                location=j.get("location", ""),
                description=strip_html(j.get("description", "")),
                url=j.get("careers_url") or j.get("careers_apply_url", ""),
                posted_date=_iso_date(j.get("published_at")),
            )
        )
    return out


def _smartrecruiters(name: str, token: str) -> list[JobPosting]:
    url = f"https://api.smartrecruiters.com/v1/companies/{token}/postings"
    with http_client(timeout=PER_REQUEST_TIMEOUT) as c:
        data = c.get(url, params={"limit": 100}).raise_for_status().json()
    out = []
    for j in data.get("content", []):
        loc = j.get("location") or {}
        location = ", ".join(
            x for x in [loc.get("city"), loc.get("region"), loc.get("country")] if x
        )
        job_id = j.get("id", "")
        out.append(
            JobPosting(
                source=f"ats:smartrecruiters:{name}",
                title=j.get("name", ""),
                company=name,
                location=location,
                # Listing endpoint has no body; title+location still rank usefully.
                description="",
                url=f"https://jobs.smartrecruiters.com/{token}/{job_id}",
                posted_date=_iso_date(j.get("releasedDate")),
            )
        )
    return out


def _personio(name: str, token: str) -> list[JobPosting]:
    from bs4 import BeautifulSoup

    url = f"https://{token}.jobs.personio.de/xml"
    with http_client(timeout=PER_REQUEST_TIMEOUT) as c:
        text = c.get(url).raise_for_status().text
    soup = BeautifulSoup(text, "html.parser")
    out = []
    for pos in soup.find_all("position"):
        def field(tag: str) -> str:
            el = pos.find(tag)
            return el.get_text(strip=True) if el else ""

        out.append(
            JobPosting(
                source=f"ats:personio:{name}",
                title=field("name"),
                company=name,
                location=field("office"),
                description=strip_html(unescape(field("jobdescriptions"))),
                url=field("id") and f"https://{token}.jobs.personio.de/job/{field('id')}",
            )
        )
    return out


def _workday(name: str, token: str) -> list[JobPosting]:
    """Workday. `token` is "tenant:wdN:site", e.g. "nvidia:wd5:NVIDIAExternalCareerSite".

    Workday caps each page at 20, so we page with `offset` up to
    WORKDAY_MAX_JOBS. The list endpoint carries no description — that is
    fetched lazily by `enrich_description()` only for jobs that survive the
    first scoring stage.
    """
    tenant, wd, site = _split_workday_token(token)
    if not (tenant and wd and site):
        raise ValueError(f"bad workday token {token!r}; expected tenant:wdN:site")

    base = f"https://{tenant}.{wd}.myworkdayjobs.com"
    api = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    out: list[JobPosting] = []
    with http_client(timeout=PER_REQUEST_TIMEOUT) as c:
        offset = 0
        while offset < WORKDAY_MAX_JOBS:
            r = c.post(
                api,
                json={"appliedFacets": {}, "limit": WORKDAY_PAGE, "offset": offset,
                      "searchText": ""},
                headers={"Content-Type": "application/json"},
            )
            if r.status_code != 200:
                break
            postings = r.json().get("jobPostings") or []
            if not postings:
                break
            for j in postings:
                path = j.get("externalPath", "")
                out.append(
                    JobPosting(
                        source=f"ats:workday:{name}",
                        title=j.get("title", ""),
                        company=name,
                        location=j.get("locationsText", ""),
                        description="",  # filled in later, only if it matters
                        url=f"{base}/en-US/{site}{path}" if path else "",
                        posted_date=None,
                    )
                )
            if len(postings) < WORKDAY_PAGE:
                break
            offset += WORKDAY_PAGE
    return out


def _bamboohr(name: str, token: str) -> list[JobPosting]:
    url = f"https://{token}.bamboohr.com/careers/list"
    with http_client(timeout=PER_REQUEST_TIMEOUT) as c:
        r = c.get(url)
        r.raise_for_status()
        # Inactive subdomains serve BambooHR's marketing HTML instead of JSON.
        if "application/json" not in r.headers.get("content-type", ""):
            return []
        data = r.json()

    out = []
    for j in data.get("result", []):
        loc = j.get("atsLocation") or j.get("location") or {}
        location = ", ".join(
            x for x in [loc.get("city"), loc.get("state"), loc.get("country")] if x
        )
        if j.get("isRemote"):
            location = (location + " (remote)").strip()
        job_id = j.get("id", "")
        out.append(
            JobPosting(
                source=f"ats:bamboohr:{name}",
                title=j.get("jobOpeningName", ""),
                company=name,
                location=location,
                description=j.get("departmentLabel", ""),
                url=f"https://{token}.bamboohr.com/careers/{job_id}" if job_id else "",
            )
        )
    return out


FETCHERS: dict[str, Callable[[str, str], list[JobPosting]]] = {
    "greenhouse": _greenhouse,
    "lever": _lever,
    "ashby": _ashby,
    "workday": _workday,
    "bamboohr": _bamboohr,
    "workable": _workable,
    "recruitee": _recruitee,
    "smartrecruiters": _smartrecruiters,
    "personio": _personio,
}


def _split_workday_token(token: str) -> tuple[str, str, str]:
    parts = (token or "").split(":")
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    return "", "", ""


def enrich_description(job: JobPosting) -> bool:
    """Fetch a full description for sources that omit it. True if it filled one.

    Called lazily by the pipeline for jobs that survive the cheap first scoring
    stage, so we never pay to fetch descriptions we'd throw away.

    This matters more than it looks: a job scored with no description gets
    marked down simply for lacking information, which silently buried real
    matches (most LinkedIn listings arrive without a body).
    """
    if job.description or not job.url:
        return False

    if job.source.startswith("linkedin"):
        from .linkedin import _fetch_description, USER_AGENTS

        desc = _fetch_description(job.url, USER_AGENTS[0])
        if desc:
            job.description = desc
            return True
        return False

    if not job.source.startswith("ats:workday:"):
        return False
    # url looks like https://{tenant}.{wd}.myworkdayjobs.com/en-US/{site}{path}
    m = re.match(r"(https://[^/]+)/en-US/([^/]+)(/.+)$", job.url)
    if not m:
        return False
    base, site, path = m.groups()
    tenant = urlparse(base).netloc.split(".")[0]
    try:
        with http_client(timeout=PER_REQUEST_TIMEOUT) as c:
            r = c.get(f"{base}/wday/cxs/{tenant}/{site}{path}")
            if r.status_code != 200:
                return False
            info = r.json().get("jobPostingInfo") or {}
    except Exception:
        return False

    desc = strip_html(unescape(info.get("jobDescription", "")))
    if not desc:
        return False
    job.description = desc
    if info.get("location"):
        job.location = info["location"]
    job.posted_date = _iso_date(info.get("startDate")) or job.posted_date
    return True


# --------------------------------------------------------------------------- #
def fetch(profile: Profile, settings: Settings) -> list[JobPosting]:
    companies = load_companies()
    if not companies:
        return []

    targets: list[tuple[str, str, str]] = []  # (name, ats, token)
    for entry in companies:
        name = entry.get("name") or ""
        ats = (entry.get("ats") or "").lower()
        token = entry.get("token") or ""
        if not (ats and token) and entry.get("careers_url"):
            ats, token = detect(entry["careers_url"])
        if not (ats and token):
            log.warning("Skipping company %r: could not determine ats/token", name or entry)
            continue
        if ats not in FETCHERS:
            log.warning("Company %r uses unsupported ATS %r; skipping", name, ats)
            continue
        targets.append((name or token, ats, token))

    jobs: list[JobPosting] = []
    ok = failed = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(FETCHERS[ats], name, token): (name, ats)
            for name, ats, token in targets
        }
        for fut in as_completed(futures):
            name, ats = futures[fut]
            try:
                jobs.extend(fut.result())
                ok += 1
            except Exception as exc:
                failed += 1
                log.warning("ATS %s/%s failed: %s", ats, name, exc)

    log.info(
        "Career pages: %d postings from %d companies (%d failed)", len(jobs), ok, failed
    )
    return jobs


# --------------------------------------------------------------------------- #
def _iso_date(value: Optional[str]):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except Exception:
        try:
            return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
        except Exception:
            return None


def _ms_date(value):
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).date()
    except Exception:
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description="Company career-page (ATS) source")
    ap.add_argument("--detect", metavar="CAREERS_URL",
                    help="Print the ats/token for a careers URL and exit.")
    args = ap.parse_args()

    if args.detect:
        ats, token = detect(args.detect)
        if ats:
            print(f"ats: {ats}\ntoken: {token}")
        else:
            print("Could not detect a supported ATS for that URL.")
            print("Supported:", ", ".join(sorted(FETCHERS)))
    else:
        from ..config import load_profile

        for j in fetch(load_profile(), Settings.from_env())[:20]:
            print(f"{j.company:24} {j.title[:60]:60} {j.location}")
