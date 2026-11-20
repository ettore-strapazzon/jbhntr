"""R3-53 — Boardroom snapshot refresh + lazy morning updates: the admin-gated snapshot endpoint returns the
company panels re-read from the current files (stamped with an ISO UTC snapshot time), and only the newest
morning update is in the first render — older ones carry their date and load on first expand."""

import os
import re
import sys
import tempfile
from pathlib import Path

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
from web.app.routes import boardroom as br  # noqa: E402

JS = Path(__file__).resolve().parents[1] / "web" / "app" / "static" / "boardroom.js"
AUTH = ("admin", "r353-admin-token")
ISO = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?\+00:00"


def _gate(monkeypatch, tmp_path):
    from web.app.config import config
    monkeypatch.setattr(config, "admin_token", AUTH[1])
    state, updates = tmp_path / "state", tmp_path / "updates"
    state.mkdir()
    updates.mkdir()
    monkeypatch.setattr(br, "STATE", state)
    monkeypatch.setattr(br, "UPDATES", updates)
    monkeypatch.setattr(br, "COMPANY", tmp_path)  # the lazy body comes from company/updates/ via /boardroom/doc
    return state, updates


def test_snapshot_is_admin_gated(monkeypatch, tmp_path):
    _gate(monkeypatch, tmp_path)
    with TestClient(app) as c:
        assert c.get("/boardroom/snapshot").status_code in (401, 404)
        assert c.get("/boardroom/snapshot", auth=("admin", "wrong")).status_code in (401, 404)


def test_snapshot_returns_the_current_files_and_a_snapshot_time(monkeypatch, tmp_path):
    state, updates = _gate(monkeypatch, tmp_path)
    (state / "KPIS.md").write_text("Activated users: r353-before\n", encoding="utf-8")
    with TestClient(app) as c:
        first = c.get("/boardroom/snapshot", auth=AUTH)
        assert first.status_code == 200 and "r353-before" in first.text
        assert "no-store" in first.headers.get("cache-control", "")
        (state / "KPIS.md").write_text("Activated users: r353-after\n", encoding="utf-8")
        (state / "REQUESTS.md").write_text("### R-901 · r353 new ask · open\nDo the thing.\n", encoding="utf-8")
        (updates / "2026-11-20.md").write_text("r353 fresh morning\n", encoding="utf-8")
        snap = c.get("/boardroom/snapshot", auth=AUTH).text
    assert "r353-after" in snap and "r353-before" not in snap
    assert "r353 new ask" in snap and "r353 fresh morning" in snap
    # The header stamp is a <time datetime> in ISO UTC that boardroom.js localises via fmt_time (R3-49).
    m = re.search(r'data-snap="stamp".*?<time datetime="(' + ISO + r')">\1</time>', snap, re.S)
    assert m, "snapshot stamp must be an ISO UTC <time datetime>"
    # Only the company panels: no chat thread / team feed in the refresh payload.
    assert 'id="thread"' not in snap and 'id="team-log"' not in snap


def test_older_morning_updates_are_not_in_the_first_render(monkeypatch, tmp_path):
    _, updates = _gate(monkeypatch, tmp_path)
    (updates / "2026-11-20.md").write_text("r353 newest body\n", encoding="utf-8")
    (updates / "2026-11-19.md").write_text("r353 older body\n", encoding="utf-8")
    (updates / "2026-11-18.md").write_text("r353 oldest body\n", encoding="utf-8")
    with TestClient(app) as c:
        page = c.get("/boardroom", auth=AUTH).text
        lazy = c.get("/boardroom/doc", params={"path": "updates/2026-11-19.md", "raw": 1}, auth=AUTH)
    assert "r353 newest body" in page
    assert "r353 older body" not in page and "r353 oldest body" not in page
    assert re.search(r'<details open data-update="2026-11-20">', page), "newest update starts expanded"
    for d in ("2026-11-19", "2026-11-18"):
        assert re.search(r'<details data-update="%s">\s*<summary>%s</summary>' % (d, d), page), d
    # The body loads on first expand through the existing admin-gated doc endpoint (path is company/-relative).
    assert lazy.status_code == 200 and "r353 older body" in lazy.text


def test_js_refreshes_every_120s_and_lazy_loads_updates_via_dom():
    js = JS.read_text(encoding="utf-8")
    assert re.search(r'fetch\("/boardroom/snapshot"', js)
    assert re.search(r"setInterval\(\s*refreshSnapshot\s*,\s*120000\s*\)", js)
    assert re.search(r'"/boardroom/doc\?raw=1&path=" \+ encodeURIComponent\("updates/"', js)
    block = re.search(r"// ---- Snapshot \(R3-53\).*?// ---- end snapshot", js, re.S)
    assert block, "boardroom.js must keep the R3-53 code between its markers"
    assert "innerHTML" not in block.group(0) and "insertAdjacentHTML" not in block.group(0)
