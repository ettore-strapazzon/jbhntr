"""R3-35 — ops/team/bridge.py Boardroom client, against a fake local HTTP server (no network, no real runtime dir)."""

import base64
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

BRIDGE = Path(__file__).resolve().parent.parent / "ops" / "team" / "bridge.py"
TOKEN = "Tk9-fake-ADMIN-token-for-tests-only-123456"


class FakeBoardroom:
    """Records every request; answers like web/app/routes/boardroom.py."""

    def __init__(self, inbox=()):
        self.requests, self.inbox = [], list(inbox)
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, obj, code=200):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _handle(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n).decode() if n else ""
                fake.requests.append({"method": self.command, "path": self.path, "auth": self.headers.get("Authorization"),
                                      "json": json.loads(raw) if raw else None})
                if "Python-urllib" in (self.headers.get("User-Agent") or ""):  # mirrors the live edge's bot block
                    return self._send({"detail": "ua"}, 403)
                if self.headers.get("Authorization") != "Basic " + base64.b64encode(f"admin:{TOKEN}".encode()).decode():
                    return self._send({"detail": "auth"}, 401)
                if self.path == "/boardroom/peek":
                    return self._send({"count": len(fake.inbox)})
                if self.path == "/boardroom/pull":
                    out, fake.inbox = fake.inbox, []
                    return self._send(out)
                return self._send({"ok": True, "id": len(fake.requests)})

            do_GET = do_POST = _handle

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake():
    f = FakeBoardroom(inbox=[{"id": 7, "body": "ship it", "created_at": None}])
    yield f
    f.close()


@pytest.fixture
def team(tmp_path, fake):
    (tmp_path / "env").write_text(f'export JBHNTR_APP_URL="{fake.url}"\nexport JBHNTR_ADMIN_TOKEN={TOKEN}\n')
    return tmp_path


def bridge(team, *args, stdin=None, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("JBHNTR_", "CHAT_FILE"))}
    env.update(JBHNTR_TEAM=str(team), **extra)
    return subprocess.run([sys.executable, str(BRIDGE), *args], input=stdin, env=env,
                          capture_output=True, text=True, timeout=30)


def test_peek_and_pull(team, fake):
    r = bridge(team, "peek")
    assert r.returncode == 0 and r.stdout.strip() == "1"
    chat = team / "inbox.json"
    r = bridge(team, "pull", CHAT_FILE=str(chat))
    assert r.returncode == 0 and r.stdout.strip() == "1"
    assert json.loads(chat.read_text()) == [{"id": 7, "body": "ship it", "created_at": None}]
    assert chat.stat().st_mode & 0o777 == 0o600
    assert bridge(team, "pull", CHAT_FILE=str(chat)).stdout.strip() == "0"
    assert json.loads(chat.read_text()) == []


def test_token_and_url_only_from_env_file(team, fake):
    # a decoy token/URL in the process env must be ignored; the token never appears in argv or output
    r = bridge(team, "peek", JBHNTR_ADMIN_TOKEN="decoy", JBHNTR_APP_URL="http://127.0.0.1:9")
    assert r.returncode == 0
    assert fake.requests[-1]["auth"] == "Basic " + base64.b64encode(f"admin:{TOKEN}".encode()).decode()
    assert TOKEN not in r.stdout + r.stderr


def test_reply_from_stdin_is_redacted(team, fake):
    body = f"Done. token={TOKEN} and password: hunter2 and key sk-ant-abcdefghijklmnopqrstuv, commit 0b59e85"
    assert bridge(team, "reply", stdin=body).returncode == 0
    sent = fake.requests[-1]
    assert sent["method"] == "POST" and sent["path"] == "/boardroom/reply"
    text = sent["json"]["body"]
    assert TOKEN not in text and "hunter2" not in text and "sk-ant" not in text
    assert text.startswith("Done.") and "0b59e85" in text and "[REDACTED]" in text


def test_log_row_with_detail(team, fake):
    detail = team / "d.md"
    detail.write_text(f"Shipped bridge.py.\nAuthorization: Bearer {TOKEN}\nBasic configuration is unchanged.\n")
    r = bridge(team, "log", "CTO", "R3-35 bridge", "shipped", f"uses {TOKEN} nowhere", "23", "--detail-file", str(detail))
    assert r.returncode == 0, r.stderr
    row = fake.requests[-1]["json"]
    assert fake.requests[-1]["path"] == "/boardroom/log"
    assert {k: row[k] for k in ("agent", "task", "status", "cycle")} == \
        {"agent": "CTO", "task": "R3-35 bridge", "status": "shipped", "cycle": "23"}
    assert row["summary"] == "uses [REDACTED] nowhere"
    assert TOKEN not in row["detail"] and "Shipped bridge.py." in row["detail"]
    assert "Basic configuration is unchanged." in row["detail"]  # plain English survives


def test_http_error_and_missing_token_fail_without_leaking(team, fake, tmp_path):
    (team / "env").write_text(f"JBHNTR_APP_URL={fake.url}\nJBHNTR_ADMIN_TOKEN=wrong-token-value\n")
    r = bridge(team, "peek")
    assert r.returncode != 0 and "401" in r.stderr and "wrong-token-value" not in r.stderr
    (team / "env").write_text(f"JBHNTR_APP_URL={fake.url}\n")
    assert bridge(team, "peek").returncode != 0


def test_redact_unit():
    sys.path.insert(0, str(BRIDGE.parent))
    try:
        import bridge as b
    finally:
        sys.path.pop(0)
    assert b.redact("api_key=abc123 ok", ()) == "api_key=[REDACTED] ok"
    assert b.redact("https://user:pw123@host/x", ()) == "https://[REDACTED]@host/x"
    assert b.redact("AKIAABCDEFGHIJKLMNOP", ()) == "[REDACTED]"
    assert b.redact("ghp_abcdefghijklmnopqrstuvwxyz0123", ()) == "[REDACTED]"
    assert b.redact("x " + "Ab1" * 12, ()) == "x [REDACTED]"
    keep = "sha 0b59e85c1d2e3f4a5b6c7d8e9f00112233445566 in R3-35, 1225 tests green"
    assert b.redact(keep, ()) == keep
    assert b.redact("secret word s3cr3tvalue", ("s3cr3tvalue",)) == "secret word [REDACTED]"
