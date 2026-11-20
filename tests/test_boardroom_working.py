"""R3-46 — "working now · 12 min": a `started` row with no later shipped/blocked/review
row for the same task id IN THE SAME CYCLE, under 6 h old. Port of BT "R1-151 working now":
the JS rule runs in node, and the server render must agree with it on the same rows."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
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

JS = Path(__file__).resolve().parents[1] / "web" / "app" / "static" / "boardroom.js"
AUTH = ("admin", "r346-admin-token")
MIN = 60_000

# Newest first: (task, status, cycle, minutes ago). Expected badge per row ("" = none).
ROWS = [
    ("R1-151 shipped next cycle", "shipped", "6", 1),      # other cycle: does not end cycle 5's run
    ("R1-152 done", "shipped", "5", 2),                    # same cycle, later row: ends R1-152
    ("R1-154 still going", "progress", "5", 3),            # not an end status: R1-154 keeps working
    ("R1-151 working now", "started", "5", 12.5),
    ("R1-152 working now", "started", "5", 20.5),
    ("R1-153 run died", "started", "5", 6 * 60 + 0.5),     # older than 6 h: the run died
    ("R1-154 working now", "started", "5", 5 * 60 + 59.5),
]
EXPECTED = ["", "", "", "12 min", "", "", "5 h 59 min"]


def _block(name: str) -> str:
    m = re.search(rf"// ---- {name}.*?// ---- end {name.split()[0].lower()}", JS.read_text(encoding="utf-8"), re.S)
    assert m, f"boardroom.js must keep the {name} helpers between their markers"
    return m.group(0)


def _js(expr: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    script = _block(r"Times \(R3-49\)") + "\n" + _block(r"Working \(R3-46\)") + \
        "\nprocess.stdout.write(JSON.stringify(" + expr + "))"
    return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True,
                                     check=True, timeout=20).stdout)


def test_r1_151_working_now_same_cycle_later_row_and_6h():
    now = 1_800_000_000_000
    rows = [{"key": t.split()[0], "status": s, "cycle": c,
             "iso": f"new Date({now} - {m} * {MIN}).toISOString()"} for t, s, c, m in ROWS]
    lit = "[" + ",".join('{key:"%s",status:"%s",cycle:"%s",iso:%s}' % (r["key"], r["status"], r["cycle"], r["iso"])
                         for r in rows) + "]"
    assert _js(f"workingNow({lit}, {now})") == EXPECTED
    assert _js(f"[elapsed(0), elapsed(59.9*{MIN}), elapsed(60*{MIN}), elapsed(-5)]") == \
        ["0 min", "59 min", "1 h 0 min", "0 min"]


def test_server_render_and_live_poll_rule_agree(monkeypatch):
    from web.app.config import config
    from web.app.db import SessionLocal
    from web.app.models import TeamLogEntry
    monkeypatch.setattr(config, "admin_token", AUTH[1])
    now = datetime.now(timezone.utc)
    with TestClient(app) as c:
        with SessionLocal() as db:
            for t, s, cy, m in reversed(ROWS):   # insert oldest first, so ids grow with time
                db.add(TeamLogEntry(agent="CTO", task=t, status=s, cycle=cy,
                                    created_at=(now - timedelta(minutes=m)).replace(tzinfo=None)))
            db.commit()
        page = c.get("/boardroom", auth=AUTH).text
        feed = c.get("/boardroom/team.json", auth=AUTH).json()   # what the live poll receives
    rows = [r for r in page.split('<div class="tl" ')[1:] if re.search(r'data-key="R1-15[1-4]"', r)][:len(ROWS)]
    server = [(re.search(r'class="tl-working">working now · ([^<]*)<', r) or [None, ""])[1] for r in rows]
    assert server == EXPECTED
    mine = [e for e in reversed(feed) if e["key"] in ("R1-151", "R1-152", "R1-153", "R1-154")][:len(ROWS)]
    lit = json.dumps([{"key": e["key"], "status": e["status"], "cycle": e["cycle"], "iso": e["ts"]} for e in mine])
    assert _js(f"workingNow({lit}, Date.now())") == server
    # The page carries what refreshWorking() reads back from the DOM on every poll / 30 s.
    assert all('data-status="' in r and 'data-cycle="' in r for r in rows)
