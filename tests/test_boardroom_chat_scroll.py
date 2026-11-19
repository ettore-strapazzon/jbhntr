"""R3-44 — Boardroom chat opens at the latest message: near-bottom predicate (run in node)
and the server-rendered "↓ latest" button."""

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

JS = Path(__file__).resolve().parents[1] / "web" / "app" / "static" / "boardroom.js"
AUTH = ("admin", "r344-admin-token")


def _near_bottom(box, slack=None):
    """Evaluate boardroom.js's own nearBottom() in node."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    m = re.search(r"^ *function nearBottom\(.*\}$", JS.read_text(encoding="utf-8"), re.M)
    assert m, "boardroom.js must keep nearBottom() as a one-line pure function"
    args = json.dumps(box) + ("" if slack is None else f", {slack}")
    out = subprocess.run([node, "-e", f"{m.group(0)}\nprocess.stdout.write(String(nearBottom({args})))"],
                         capture_output=True, text=True, check=True, timeout=20)
    return out.stdout == "true"


def test_near_bottom_predicate_decides_whether_a_new_message_may_auto_scroll():
    assert _near_bottom({"scrollTop": 900, "scrollHeight": 1500, "clientHeight": 560}) is True   # 40px from end
    assert _near_bottom({"scrollTop": 200, "scrollHeight": 1500, "clientHeight": 560}) is False  # reading older
    assert _near_bottom({"scrollTop": 0, "scrollHeight": 300, "clientHeight": 560}) is True      # no overflow yet


def test_near_bottom_edge_and_image_slack():
    assert _near_bottom({"scrollTop": 860, "scrollHeight": 1500, "clientHeight": 560}) is True   # exactly 80px
    assert _near_bottom({"scrollTop": 859, "scrollHeight": 1500, "clientHeight": 560}) is False
    assert _near_bottom({"scrollTop": 800, "scrollHeight": 1500, "clientHeight": 560}, 200) is True


def test_page_has_hidden_to_latest_button(monkeypatch):
    from web.app.config import config
    monkeypatch.setattr(config, "admin_token", AUTH[1])
    with TestClient(app) as c:
        page = c.get("/boardroom", auth=AUTH).text
    m = re.search(r"<button[^>]*\bid=\"to-latest\"[^>]*>", page)
    assert m and " hidden" in m.group(0) and 'type="button"' in m.group(0)
    assert "onclick" not in m.group(0).lower()
