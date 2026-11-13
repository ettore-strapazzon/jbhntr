"""R3-19 — Boardroom CSRF.

/boardroom is gated by the same HTTP Basic auth as /admin, which a browser re-sends
on a cross-site POST. So:
  * /boardroom/send (the Founder's browser form) needs the admin CSRF token, exactly
    like every /admin POST (require_admin_csrf);
  * /boardroom/log and /boardroom/reply are called by the VM cycle with curl (Basic
    auth, form-encoded, no Origin / Sec-Fetch-* headers). They keep working for that
    caller unchanged, but refuse a browser cross-site POST (foreign or `null` Origin,
    Sec-Fetch-Site cross-site / same-site). Basic auth is still checked first.
"""

import os
import sys
import tempfile
from urllib.parse import quote

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

from web.app.main import app  # noqa: E402
from web.app.routes import admin as admin_mod  # noqa: E402
from web.app.routes import boardroom as boardroom_mod  # noqa: E402

TOKEN = "r319-admin-token"
AUTH = ("admin", TOKEN)
SCRIPT_ROUTES = ["/boardroom/log", "/boardroom/reply"]
SCRIPT_BODY = {"/boardroom/log": {"agent": "CTO", "task": "R3-19", "status": "started"},
               "/boardroom/reply": {"body": "r319 reply"}}
FORGED = {"foreign-origin": {"Origin": "https://evil.example"},
          "null-origin": {"Origin": "null"},
          "sec-fetch-cross-site": {"Sec-Fetch-Site": "cross-site"},
          "sec-fetch-same-site": {"Sec-Fetch-Site": "same-site"},
          "foreign-origin-plus-same-origin-fetch": {"Origin": "https://evil.example",
                                                    "Sec-Fetch-Site": "same-origin"}}


@pytest.fixture(scope="module", autouse=True)
def _app_started():
    with TestClient(app):
        yield


@pytest.fixture
def client(monkeypatch):
    from web.app.config import config
    monkeypatch.setattr(config, "admin_token", TOKEN)
    return TestClient(app)


def _curl_body(fields: dict) -> str:
    """What `curl --data-urlencode k=v ...` puts on the wire: k=urlencoded(v) joined by &."""
    return "&".join(f"{k}={quote(v, safe='')}" for k, v in fields.items())


# ---- the CEO's live call: must never break ----

def test_ceo_live_curl_log_post_shape_succeeds(monkeypatch):
    """Exactly the CEO's live request:
    curl -s -u admin:... https://jbhntr.app/boardroom/log --data-urlencode agent=..
         --data-urlencode task=.. status=.. cycle=.. summary=..
    i.e. POST, Basic auth, application/x-www-form-urlencoded, curl's own UA/Accept,
    Host jbhntr.app, and NO Origin / Sec-Fetch-* / Referer headers."""
    from web.app.config import config
    from web.app.db import SessionLocal
    from web.app.models import TeamLogEntry
    monkeypatch.setattr(config, "admin_token", TOKEN)
    curl = TestClient(app, base_url="https://jbhntr.app")
    fields = {"agent": "CTO", "task": "R3-19 Boardroom CSRF", "status": "shipped",
              "cycle": "10", "summary": "Origin/Sec-Fetch check on /boardroom/log & /reply; "
                                        "send needs the token. 100% = done?"}
    r = curl.post("/boardroom/log", content=_curl_body(fields), auth=AUTH,
                  headers={"Content-Type": "application/x-www-form-urlencoded",
                           "User-Agent": "curl/8.5.0", "Accept": "*/*"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    db = SessionLocal()
    try:
        e = db.get(TeamLogEntry, r.json()["id"])
        assert (e.agent, e.task, e.status, e.cycle, e.summary) == (
            "CTO", fields["task"], "shipped", "10", fields["summary"])
    finally:
        db.close()


@pytest.mark.parametrize("path", SCRIPT_ROUTES)
def test_script_style_post_succeeds(client, path):
    r = client.post(path, content=_curl_body(SCRIPT_BODY[path]), auth=AUTH,
                    headers={"Content-Type": "application/x-www-form-urlencoded",
                             "User-Agent": "curl/8.5.0", "Accept": "*/*"})
    assert r.status_code == 200, (path, r.status_code, r.text)


@pytest.mark.parametrize("path", SCRIPT_ROUTES)
def test_script_style_json_post_succeeds(client, path):
    r = client.post(path, json=SCRIPT_BODY[path], auth=AUTH)
    assert r.status_code == 200, (path, r.status_code, r.text)


@pytest.mark.parametrize("path", SCRIPT_ROUTES)
def test_same_origin_browser_post_still_allowed(client, path):
    r = client.post(path, data=SCRIPT_BODY[path], auth=AUTH,
                    headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200, (path, r.status_code)


# ---- forged browser calls ----

@pytest.mark.parametrize("path", SCRIPT_ROUTES)
@pytest.mark.parametrize("case", sorted(FORGED))
def test_forged_browser_post_to_script_route_is_403(client, path, case):
    r = client.post(path, data=SCRIPT_BODY[path], auth=AUTH, headers=FORGED[case])
    assert r.status_code == 403, (path, case, r.status_code)


@pytest.mark.parametrize("path", SCRIPT_ROUTES + ["/boardroom/send"])
def test_unauthenticated_post_is_401_before_403(client, path):
    r = client.post(path, data=SCRIPT_BODY.get(path, {"body": "x"}),
                    headers={"Origin": "https://evil.example"}, follow_redirects=False)
    assert r.status_code == 401, (path, r.status_code)


def test_forged_log_post_writes_nothing(client):
    before = client.get("/boardroom/team.json", auth=AUTH).json()
    base = before[-1]["id"] if before else 0
    r = client.post("/boardroom/log", data={"agent": "EVIL", "task": "x"}, auth=AUTH,
                    headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert client.get(f"/boardroom/team.json?after={base}", auth=AUTH).json() == []


# ---- /boardroom/send: the browser form needs the admin CSRF token ----

def test_send_route_enforces_require_admin_csrf_after_basic_auth():
    route = next(r for r in boardroom_mod.router.routes if r.path == "/boardroom/send")
    calls = [d.call for d in route.dependant.dependencies]
    assert admin_mod.require_admin_csrf in calls
    assert calls.index(admin_mod.require_admin) < calls.index(admin_mod.require_admin_csrf)


@pytest.mark.parametrize("case", ["missing", "forged", "foreign-origin", "null-origin",
                                  "sec-fetch-cross-site"])
def test_send_without_valid_token_is_403(client, case):
    data = {"body": f"r319 forged {case}"}
    headers = {}
    if case == "forged":
        data["csrf"] = "forged"
    elif case != "missing":
        data["csrf"] = admin_mod.admin_csrf_token()
        headers = {"foreign-origin": {"Origin": "https://evil.example"},
                   "null-origin": {"Origin": "null"},
                   "sec-fetch-cross-site": {"Sec-Fetch-Site": "cross-site"}}[case]
    before = client.get("/boardroom/peek", auth=AUTH).json()["count"]
    r = client.post("/boardroom/send", data=data, headers=headers, auth=AUTH,
                    follow_redirects=False)
    assert r.status_code == 403, (case, r.status_code)
    assert client.get("/boardroom/peek", auth=AUTH).json()["count"] == before


def test_send_with_token_is_accepted(client):
    before = client.get("/boardroom/peek", auth=AUTH).json()["count"]
    r = client.post("/boardroom/send",
                    data={"body": "r319 real founder message",
                          "csrf": admin_mod.admin_csrf_token()},
                    headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
                    auth=AUTH, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/boardroom"
    assert client.get("/boardroom/peek", auth=AUTH).json()["count"] == before + 1
    client.get("/boardroom/pull", auth=AUTH)   # consume, leave the queue clean


def test_rendered_boardroom_send_form_carries_the_real_token(client):
    html = client.get("/boardroom", auth=AUTH).text
    tok = admin_mod.admin_csrf_token()
    form = html[html.index('action="/boardroom/send"'):]
    form = form[:form.index("</form>")]
    assert f'name="csrf" value="{tok}"' in form


def test_boardroom_js_sends_the_csrf_field():
    """The page submits the chat form via fetch(); it must forward the hidden token."""
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "web" / "app" / "static"
          / "boardroom.js").read_text()
    assert 'body.append("csrf"' in js


# ---- R3-21: GET /boardroom/pull consumes messages -> same-origin check ----
# The VM cycle calls it as:  curl -s -u "admin:$JBHNTR_ADMIN_TOKEN" "$APP/boardroom/pull"
# (/home/ubuntu/run_cycle.sh) -- a GET with Basic auth and no Origin / Sec-Fetch-*
# headers. That shape must keep working; a browser cross-site GET must not consume.

def _queue_founder_message(client, body: str) -> int:
    r = client.post("/boardroom/send", data={"body": body, "csrf": admin_mod.admin_csrf_token()},
                    auth=AUTH, follow_redirects=False)
    assert r.status_code == 303
    return client.get("/boardroom/peek", auth=AUTH).json()["count"]


def test_pull_route_enforces_same_origin_after_basic_auth():
    route = next(r for r in boardroom_mod.router.routes if r.path == "/boardroom/pull")
    calls = [d.call for d in route.dependant.dependencies]
    assert admin_mod.require_same_origin in calls
    assert calls.index(admin_mod.require_admin) < calls.index(admin_mod.require_same_origin)


def test_vm_script_curl_pull_shape_succeeds_and_consumes(monkeypatch):
    """Exactly the VM's call: GET, Basic auth, curl UA/Accept, Host jbhntr.app, no
    Origin / Sec-Fetch-* / Referer."""
    from web.app.config import config
    monkeypatch.setattr(config, "admin_token", TOKEN)
    client = TestClient(app)
    client.get("/boardroom/pull", auth=AUTH)                    # start from an empty queue
    _queue_founder_message(client, "r321 pull me")
    curl = TestClient(app, base_url="https://jbhntr.app")
    r = curl.get("/boardroom/pull", auth=AUTH,
                 headers={"User-Agent": "curl/8.5.0", "Accept": "*/*"})
    assert r.status_code == 200, r.text
    assert [m["body"] for m in r.json()] == ["r321 pull me"]
    assert client.get("/boardroom/peek", auth=AUTH).json()["count"] == 0


@pytest.mark.parametrize("fetch_site", ["same-origin", "none"])
def test_same_origin_or_typed_url_pull_still_allowed(client, fetch_site):
    headers = {"Sec-Fetch-Site": fetch_site}
    if fetch_site == "same-origin":
        headers["Origin"] = "http://testserver"
    r = client.get("/boardroom/pull", auth=AUTH, headers=headers)
    assert r.status_code == 200, (fetch_site, r.status_code)


@pytest.mark.parametrize("case", sorted(FORGED))
def test_forged_browser_pull_is_403_and_consumes_nothing(client, case):
    client.get("/boardroom/pull", auth=AUTH)                    # start from an empty queue
    before = _queue_founder_message(client, f"r321 keep me {case}")
    assert before == 1
    r = client.get("/boardroom/pull", auth=AUTH, headers=FORGED[case])
    assert r.status_code == 403, (case, r.status_code)
    assert client.get("/boardroom/peek", auth=AUTH).json()["count"] == before
    client.get("/boardroom/pull", auth=AUTH)                    # consume, leave clean


def test_unauthenticated_cross_site_pull_is_401_before_403(client):
    r = client.get("/boardroom/pull", headers={"Origin": "https://evil.example"})
    assert r.status_code == 401


def test_no_boardroom_or_admin_get_commits_without_a_same_origin_check():
    """Sweep guard: any /admin or /boardroom GET whose handler commits must carry
    require_same_origin. Positive control: /boardroom/pull is found by the sweep."""
    import inspect

    from tests.test_admin_csrf import _api_routes, _dep_calls
    committing = []
    for path, r in _api_routes(app.routes):
        if "GET" in r.methods and path.startswith(("/admin", "/boardroom")):
            if ".commit(" in inspect.getsource(r.endpoint):
                committing.append(path)
                assert admin_mod.require_same_origin in _dep_calls(r.dependant), path
    assert "/boardroom/pull" in committing
