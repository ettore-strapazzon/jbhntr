"""R3-42 — oversized request bodies are refused with 413 before any route parses them
(Starlette spools multipart to temp disk before require_admin runs)."""

import os
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

from web.app import security  # noqa: E402
from web.app.config import config  # noqa: E402
from web.app.main import app  # noqa: E402
from web.app.routes import admin as admin_mod  # noqa: E402
from web.app.routes import boardroom as br  # noqa: E402

TOKEN = "r342-admin-token"
AUTH = ("admin", TOKEN)
MB = 1024 * 1024


@pytest.fixture(scope="module", autouse=True)
def _app_started():
    with TestClient(app):
        yield


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "admin_token", TOKEN)
    monkeypatch.setattr(br, "ATTACH_DIR", tmp_path / "att")
    c = TestClient(app)
    c.get("/boardroom/pull", auth=AUTH)
    return c


@pytest.fixture
def no_handler(monkeypatch):
    """Fail loudly if a guarded handler ever gets to read the body."""
    async def boom(*a, **k):
        raise AssertionError("handler ran")
    monkeypatch.setattr(br, "_read_attachments", boom)


def test_caps_sit_above_the_real_upload_limits():
    assert security.BODY_LIMIT_DEFAULT > config.max_upload_bytes          # onboarding CV upload
    assert security.BODY_LIMITS["/boardroom/send"] > br.MAX_TOTAL           # 10 MB of attachments


def test_over_cap_content_length_is_413_before_auth_or_handler(client, no_handler):
    r = client.post("/boardroom/send", content=b"x" * (12 * MB),
                    headers={"content-type": "multipart/form-data; boundary=zz"})
    assert r.status_code == 413                                             # no auth sent: not 401


def test_default_cap_applies_to_other_routes(client):
    r = client.post("/upload", content=b"x" * (3 * MB),
                    headers={"content-type": "multipart/form-data; boundary=zz"})
    assert r.status_code == 413
    r = client.post("/boardroom/log", json={"agent": "CTO", "detail": "x" * (3 * MB)}, auth=AUTH)
    assert r.status_code == 413


def test_chunked_body_over_cap_is_cut_off(client):
    def chunks():
        for _ in range(4):
            yield b"x" * MB                                                 # no Content-Length
    r = client.post("/boardroom/log", content=chunks(), auth=AUTH,
                    headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_chunked_body_under_cap_passes(client):
    def chunks():
        yield b'{"agent": "CTO", '
        yield b'"task": "R3-42", "status": "started"}'
    r = client.post("/boardroom/log", content=chunks(), auth=AUTH,
                    headers={"content-type": "application/json"})
    assert r.status_code == 200


def test_under_cap_json_passes(client):
    r = client.post("/boardroom/log", json={"agent": "CTO", "task": "R3-42", "status": "started"},
                    auth=AUTH)
    assert r.status_code == 200


def test_boardroom_send_allows_ten_mb_of_attachments(client):
    pdf = b"%PDF-1.7\n" + b"x" * (5 * MB - 100)
    r = client.post("/boardroom/send", data={"body": "big", "csrf": admin_mod.admin_csrf_token()},
                    files=[("files", ("a.pdf", pdf, "application/pdf")),
                           ("files", ("b.pdf", pdf, "application/pdf"))],
                    auth=AUTH, follow_redirects=False)
    assert r.status_code == 303, r.text
    msgs = client.get("/boardroom/pull", auth=AUTH).json()
    assert len(msgs) == 1 and len(msgs[0]["attachments"]) == 2
