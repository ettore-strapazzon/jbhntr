"""R3-49 — Boardroom times in the Founder's zone: one JS helper (fmt_time, run in node),
server sends ISO UTC, and no raw UTC slices left in the template/JS."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

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

WEB = Path(__file__).resolve().parents[1] / "web" / "app"
JS = WEB / "static" / "boardroom.js"
TPL = WEB / "templates" / "boardroom.html"
AUTH = ("admin", "r349-admin-token")


def _times_block() -> str:
    m = re.search(r"// ---- Times \(R3-49\).*?// ---- end times", JS.read_text(encoding="utf-8"), re.S)
    assert m, "boardroom.js must keep the time helpers between the R3-49 markers"
    return m.group(0)


def _js(calls: list[str], tz_env: str | None = None) -> list[str]:
    """Evaluate each JS expression against boardroom.js's own time helpers in node."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    script = _times_block() + "\nprocess.stdout.write(JSON.stringify([" + ",".join(calls) + "]))"
    env = dict(os.environ, **({"TZ": tz_env} if tz_env else {}))
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True, timeout=20, env=env)
    return json.loads(out.stdout)


def test_r1_152_fmt_time_local_zone_24h_short_name_and_utc_fallbacks():
    got = _js([
        'fmt_time("2026-11-17T09:05:00.123456+00:00", "Europe/Rome")',
        'fmt_time("2026-07-01T22:30:00Z", "Europe/Rome")',
        'fmt_time("2026-11-17T09:05:00Z", "America/New_York")',
        'fmt_time("2026-11-17T09:05:00Z", "UTC")',
        'utc_time("2026-11-17T09:05:00.5+00:00")',
        'fmt_time("garbage")', 'fmt_time("")', 'fmt_time(undefined)', 'utc_time("garbage")',
    ])
    assert got == [
        "2026-11-17 10:05 CET",
        "2026-07-02 00:30 CEST",   # date rolls over, 00 not 24
        "2026-11-17 04:05 EST",
        "2026-11-17 09:05 UTC",
        "2026-11-17 09:05 UTC",
        "garbage UTC", "", "", "garbage UTC",
    ]


def test_r1_152_no_zone_argument_uses_the_browser_zone():
    assert _js(['fmt_time("2026-11-17T09:05:00Z")'], tz_env="Europe/Rome") == ["2026-11-17 10:05 CET"]


def test_no_raw_utc_slices_left_every_timestamp_goes_through_fmt_time():
    js = JS.read_text(encoding="utf-8")
    tpl = TPL.read_text(encoding="utf-8")
    outside = js.replace(_times_block(), "")
    # No hand-formatting of UTC strings anywhere in the client or template.
    for pat in (r"\.slice\(\s*0\s*,\s*1\d\s*\)", r"\.substr(ing)?\(", r"replace\(\s*[\"']T[\"']",
                r"toISOString", r"toUTCString", r"getUTC\w+\(", r"[\"'] UTC[\"']"):
        assert not re.search(pat, outside), f"boardroom.js formats a time by hand: {pat}"
    for pat in (r"\.ts\s*\[", r"\|\s*replace\(\s*[\"']T", r"strftime", r"\bUTC\b"):
        assert not re.search(pat, tpl), f"boardroom.html formats a time by hand: {pat}"
    # JS: a row's ts is only ever handed to timeEl() (or truth-tested).
    for m in re.finditer(r"\b\w+\.ts\b", outside):
        before = outside[max(0, m.start() - 8):m.start()]
        assert before.endswith(("timeEl(", "if (")), f"raw ts use in boardroom.js: …{before}{m.group(0)}"
    # Template: every ts is a <time datetime> the JS localises on load.
    uses = re.findall(r"\{\{\s*\w+\.ts\s*\}\}", tpl)
    wrapped = re.findall(r'<time datetime="\{\{ (\w+)\.ts \}\}">\{\{ \1\.ts \}\}</time>', tpl)
    assert uses and len(uses) == 2 * len(wrapped), "every server-rendered ts must sit in <time datetime>"
    assert re.search(r'querySelectorAll\("time\[datetime\]"\)', outside), "first load must be localised"


def test_server_sends_iso_utc_in_json_and_first_render(monkeypatch):
    from web.app.config import config
    from web.app.db import SessionLocal
    from web.app.models import BoardroomMessage, TeamLogEntry
    monkeypatch.setattr(config, "admin_token", AUTH[1])
    with TestClient(app) as c:
        with SessionLocal() as db:
            db.add(BoardroomMessage(role="founder", body="r349 hello"))
            db.add(TeamLogEntry(agent="CTO", task="R3-49 times", status="started", summary="s", cycle="27"))
            db.commit()
        iso = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?\+00:00$")
        msgs = c.get("/boardroom/messages.json", auth=AUTH).json()
        team = c.get("/boardroom/team.json", auth=AUTH).json()
        assert msgs and all(iso.match(m["ts"]) for m in msgs), msgs[-1]["ts"]
        assert team and all(iso.match(e["ts"]) for e in team), team[0]["ts"]
        page = c.get("/boardroom", auth=AUTH).text
    stamps = re.findall(r'<time datetime="([^"]+)">([^<]+)</time>', page)
    assert len(stamps) >= 2 and all(iso.match(dt) and dt == txt for dt, txt in stamps)
