"""R3-40 — Boardroom chat attachments: limits, magic-byte allowlist, private storage,
admin-gated download headers, pull metadata."""

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

from web.app.main import app  # noqa: E402
from web.app.routes import admin as admin_mod  # noqa: E402
from web.app.routes import boardroom as br  # noqa: E402

TOKEN = "r340-admin-token"
AUTH = ("admin", TOKEN)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
PDF = b"%PDF-1.7\n%..." + b"x" * 32
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"x" * 16


@pytest.fixture(scope="module", autouse=True)
def _app_started():
    with TestClient(app):
        yield


@pytest.fixture
def client(monkeypatch, tmp_path):
    from web.app.config import config
    monkeypatch.setattr(config, "admin_token", TOKEN)
    monkeypatch.setattr(br, "ATTACH_DIR", tmp_path / "att")
    c = TestClient(app)
    c.get("/boardroom/pull", auth=AUTH)          # start from an empty queue
    return c


def send(client, files, body="see attached"):
    return client.post("/boardroom/send", data={"body": body, "csrf": admin_mod.admin_csrf_token()},
                       files=[("files", f) for f in files], auth=AUTH, follow_redirects=False)


def pulled(client):
    return client.get("/boardroom/pull", auth=AUTH).json()


def test_valid_files_stored_privately_and_listed_in_pull(client, tmp_path):
    r = send(client, [("shot.png", PNG, "image/png"), ("spec.pdf", PDF, "application/pdf"),
                      ("a.webp", WEBP, "image/webp"), ("notes.md", b"# hi\n", "text/markdown"),
                      ("d.csv", b"a,b\n1,2\n", "text/csv")])
    assert r.status_code == 303, r.text
    [msg] = pulled(client)
    assert [(a["name"], a["type"], a["size"]) for a in msg["attachments"]] == [
        ("shot.png", "image/png", len(PNG)), ("spec.pdf", "application/pdf", len(PDF)),
        ("a.webp", "image/webp", len(WEBP)), ("notes.md", "text/plain; charset=utf-8", 5),
        ("d.csv", "text/plain; charset=utf-8", 8)]
    stored = sorted(p.name for p in (tmp_path / "att").iterdir())
    assert stored == sorted(str(a["id"]) for a in msg["attachments"])   # int ids only, no client names
    assert PNG not in (tmp_path / "att" / str(msg["attachments"][0]["id"])).read_bytes()  # encrypted at rest
    assert not str(br.ATTACH_DIR).startswith(str(br.ROOT / "web"))       # never under /static


def test_files_only_message_is_accepted(client):
    assert send(client, [("x.png", PNG, "image/png")], body="").status_code == 303
    assert pulled(client)[0]["attachments"][0]["name"] == "x.png"


def test_no_files_keeps_old_shape(client):
    assert send(client, [], body="plain").status_code == 303
    assert pulled(client)[0]["attachments"] == []


@pytest.mark.parametrize("name,raw", [
    ("evil.png", b"<html><script>alert(1)</script></html>"),   # HTML renamed .png
    ("shot.jpg", PNG),                                         # real PNG, mismatched extension
    ("page.txt", b"<!DOCTYPE html><p>x</p>"),                  # HTML posing as text
    ("x.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>"),
    ("run.exe", b"MZ\x90\x00"),
    ("bin.txt", b"\xff\xfe\x00bad"),
    ("empty.md", b""),
])
def test_bad_type_rejects_whole_message(client, name, raw):
    r = send(client, [("ok.png", PNG, "image/png"), (name, raw, "image/png")])
    assert r.status_code == 400, (name, r.status_code)
    assert pulled(client) == []                                # nothing stored


def test_more_than_five_files_rejected(client):
    r = send(client, [(f"f{i}.png", PNG, "image/png") for i in range(6)])
    assert r.status_code == 400 and "5 files" in r.text
    assert pulled(client) == []


def test_over_ten_mb_total_rejected(client):
    half = PDF + b"x" * (5 * 1024 * 1024)
    r = send(client, [("a.pdf", half, "application/pdf"), ("b.pdf", half, "application/pdf")])
    assert r.status_code == 400 and "10 MB" in r.text
    assert pulled(client) == []


def test_path_traversal_name_is_sanitised(client, tmp_path):
    assert send(client, [("../../../etc/passwd.png", PNG, "image/png"),
                         ("..\\..\\win.png", PNG, "image/png")]).status_code == 303
    names = [a["name"] for a in pulled(client)[0]["attachments"]]
    assert names == ["passwd.png", "win.png"]
    assert all(p.parent == tmp_path / "att" for p in (tmp_path / "att").rglob("*"))


def test_safe_name_unit():
    assert br._safe_name('..\\x/"; rm -rf .png') == "___rm_-rf_.png"
    assert br._safe_name("...") == "file"
    assert br._safe_name(".bashrc") == "bashrc"


def test_send_still_needs_csrf_with_files(client):
    r = client.post("/boardroom/send", data={"body": "x"}, files=[("files", ("a.png", PNG, "image/png"))],
                    auth=AUTH, follow_redirects=False)
    assert r.status_code == 403
    assert pulled(client) == []


def test_download_headers_and_bytes(client):
    send(client, [("shot.png", PNG, "image/png"), ("n.md", b"# hi", "text/markdown")])
    png, md = pulled(client)[0]["attachments"]
    r = client.get(f"/boardroom/attachment/{png['id']}", auth=AUTH)
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["content-type"] == "image/png"
    assert r.headers["content-disposition"] == 'attachment; filename="shot.png"'
    assert r.headers["x-content-type-options"] == "nosniff"
    r = client.get(f"/boardroom/attachment/{md['id']}", auth=AUTH)
    assert r.headers["content-type"] == "text/plain; charset=utf-8"


def test_download_unauthenticated_or_wrong_token_refused(client):
    send(client, [("shot.png", PNG, "image/png")])
    aid = pulled(client)[0]["attachments"][0]["id"]
    assert client.get(f"/boardroom/attachment/{aid}").status_code == 401
    assert client.get(f"/boardroom/attachment/{aid}", auth=("admin", "nope")).status_code == 401


def test_download_unknown_id_404(client):
    assert client.get("/boardroom/attachment/999999", auth=AUTH).status_code == 404


def test_messages_json_and_page_show_attachment_links(client):
    send(client, [("shot.png", PNG, "image/png")])
    aid = pulled(client)[0]["attachments"][0]["id"]
    rows = client.get("/boardroom/messages.json", auth=AUTH).json()
    assert any(a["id"] == aid for m in rows for a in m["attachments"])
    assert f'href="/boardroom/attachment/{aid}"' in client.get("/boardroom", auth=AUTH).text
