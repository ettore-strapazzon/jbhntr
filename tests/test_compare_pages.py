"""R3-08 — /compare/jobright, /compare/simplify, /compare/auto-apply-tools.

One shared template fed by web/app/compare_pages.py. Each page: 200, the GC review
date, the "we build a tool in this space" disclosure, its sources, its own
title/meta/canonical/og, one h1, in the sitemap. /compare/teal stays 404 (waits
R-012) and Indeed is named nowhere on the auto-apply page (HELD).
Same throwaway-SQLite setup as test_web.py; this module adds no DB rows.
"""

import json
import os
import re
import sys
import tempfile

import pytest

if "web.app.main" not in sys.modules:
    _tmp = tempfile.mkdtemp()
    os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.sqlite"
    os.environ["SECRET_KEY"] = "x" * 48
    os.environ.setdefault("FILE_ENCRYPTION_KEY", "")
    if not os.environ["FILE_ENCRYPTION_KEY"]:
        from cryptography.fernet import Fernet

        os.environ["FILE_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    os.environ["DEBUG"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from web.app import seo  # noqa: E402
from web.app.compare_pages import COMPARE_PAGES  # noqa: E402
from web.app.main import app  # noqa: E402

NEW = ("/compare/jobright", "/compare/simplify", "/compare/auto-apply-tools")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("path", NEW)
def test_page_renders_with_review_date_and_disclosure(client, path):
    r = client.get(path)
    assert r.status_code == 200
    t = r.text
    assert "Last reviewed against official sources on 13 November 2026." in t
    assert "we build a tool in this space" in t
    assert t.count("<h1") == 1
    assert "Where they differ" in t and 'class="compare-scroll"' in t
    assert 'href="/signup"' in t and 'href="/how-it-works"' in t
    main = t.split('<main id="main">', 1)[1].split("</main>", 1)[0]
    assert "<script" not in main                    # CSP: page body adds no scripts


@pytest.mark.parametrize("path", NEW)
def test_page_seo_head(client, path):
    page = COMPARE_PAGES[path.rsplit("/", 1)[1]]
    t = client.get(path).text
    assert f"<title>{page['title']}</title>" in t
    assert 'name="robots" content="index,follow' in t
    assert f'rel="canonical" href="{seo.absolute_url(path)}"' in t
    assert f'property="og:url" content="{seo.absolute_url(path)}"' in t
    assert f'property="og:title" content="{page["h1"]}"' in t
    blobs = re.findall(r'<script type="application/ld\+json">(.*?)</script>', t, re.S)
    webpage = [json.loads(b) for b in blobs if '"WebPage"' in b]
    assert webpage and webpage[0]["lastReviewed"] == "2026-11-13"
    assert webpage[0]["url"] == seo.absolute_url(path)


@pytest.mark.parametrize("path", NEW)
def test_sources_listed_and_pages_cross_linked(client, path):
    page = COMPARE_PAGES[path.rsplit("/", 1)[1]]
    t = client.get(path).text
    for _label, url in page["sources"]:
        assert f'href="{url}"' in t
    for other in ("/compare/linkedin-jobs", *NEW):
        if other != path:
            assert f'href="{other}"' in t


def test_teal_still_404(client):
    assert client.get("/compare/teal").status_code == 404
    assert "/compare/teal" not in client.get("/sitemap.xml").text


def test_auto_apply_page_never_names_indeed(client):
    t = client.get("/compare/auto-apply-tools").text
    assert "indeed" not in t.lower()
    assert "sonara" not in t.lower()                 # status unverified in R3-12


def test_own_claims_stay_inside_gc_lines(client):
    for path in NEW:
        t = client.get(path).text.lower()
        for banned in ("every live role", "whole market", "ten to twenty",
                       "close to worthless", "1-click apply"):
            assert banned not in t, (path, banned)


def test_sitemap_and_internal_links(client):
    locs = set(re.findall(r"<loc>(.*?)</loc>", client.get("/sitemap.xml").text))
    for path in NEW:
        assert seo.absolute_url(path) in locs
    for src in ("/compare/linkedin-jobs", "/how-it-works"):
        t = client.get(src).text
        for path in NEW:
            assert f'href="{path}"' in t, (src, path)
