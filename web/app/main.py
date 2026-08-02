"""JBHNTR web application."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from .config import ROOT, config
from .db import SessionLocal, init_db
from .models import PageView
from .routes import (
    account, admin, alpha, applications, auth_routes, documents, fields, job,
    legal, marketing, matches, onboarding, profile, search,
)
from .templating import templates

logging.basicConfig(
    level=logging.DEBUG if config.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("jbhntr")

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    problems = config.validate()
    for p in problems:
        log.warning("CONFIG: %s", p)
    if problems and not config.debug:
        # Never boot a production instance with weak secrets.
        raise RuntimeError("Refusing to start in production: " + "; ".join(problems))
    yield


app = FastAPI(title="JBHNTR", docs_url=None, redoc_url=None, openapi_url=None,
              lifespan=lifespan)

# Behind Cloudflare + Railway the request reaches us over http; trust the
# X-Forwarded-Proto/For headers so request.url is https. Without this, the OAuth
# callback reconstructs an http:// redirect_uri and Google rejects the token
# exchange ("redirect_uri mismatch"), and secure cookies misbehave.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# Needed by Authlib to hold the OAuth `state` across the Google round-trip.
# Separate from our own login cookie; short-lived and lax so it survives the
# top-level redirect back from Google. Scope the cookie to the registrable
# domain (".jbhntr.app") so the state survives even if the flow crosses between
# the apex and www — otherwise a host-only cookie is stranded and the callback
# fails with a state mismatch.
_host = urlparse(config.base_url).hostname or ""
_cookie_domain = None
if "." in _host and _host != "localhost" and not _host.replace(".", "").isdigit():
    _cookie_domain = "." + (_host[4:] if _host.startswith("www.") else _host)

app.add_middleware(
    SessionMiddleware,
    secret_key=config.secret_key or "insecure-dev-only",
    https_only=not config.debug,
    same_site="lax",
    max_age=3600,
    domain=_cookie_domain,
)

static_dir = ROOT / "web" / "app" / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# --------------------------------------------------------------------------- #
@app.middleware("http")
async def security_and_analytics(request: Request, call_next):
    response = await call_next(request)

    # Defence-in-depth headers. CSP is deliberately strict: no inline scripts,
    # no third-party origins except the analytics host.
    plausible = "https://plausible.io" if config.plausible_domain else ""
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        f"script-src 'self' {plausible} https://unpkg.com; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        f"connect-src 'self' {plausible}; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if not config.debug:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    # Minimal, privacy-preserving analytics: no IP and no user id are stored; the
    # visitor token is a daily-rotating one-way hash (see services/analytics.py).
    path = request.url.path
    if request.method == "GET" and not path.startswith(("/static", "/health")):
        try:
            from .services.analytics import client_ip, visitor_hash
            db = SessionLocal()
            db.add(PageView(
                path=path[:255],
                referrer=(request.headers.get("referer") or "")[:255],
                country=request.headers.get("cf-ipcountry", "")[:8],
                visitor=visitor_hash(client_ip(request),
                                     request.headers.get("user-agent", "")) or None,
            ))
            db.commit()
            db.close()
        except Exception:
            pass  # analytics must never break a request

    return response


# --------------------------------------------------------------------------- #
app.include_router(auth_routes.router)
app.include_router(onboarding.router)
app.include_router(fields.router)
app.include_router(profile.router)
app.include_router(matches.router)
app.include_router(applications.router)
app.include_router(documents.router)
app.include_router(search.router)
app.include_router(job.router)
app.include_router(account.router)
app.include_router(legal.router)
app.include_router(alpha.router)
app.include_router(admin.router)
app.include_router(marketing.router)   # homepage, robots.txt, sitemap.xml


@app.get("/health")
def health():
    return {"status": "ok"}
