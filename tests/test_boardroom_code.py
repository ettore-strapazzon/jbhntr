"""R3-48 — Boardroom chat: code vs prose. Port of BT "code vs prose (R1-122)": the splitter runs
in node; each command becomes its own copyable block, prose stays text, DOM + textContent only;
server-rendered first-load bodies are re-rendered by the same JS so both paths split identically."""

import html
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
AUTH = ("admin", "r348-admin-token")


def _block(start: str, end: str) -> str:
    m = re.search(re.escape(start) + r".*?" + re.escape(end), JS.read_text(encoding="utf-8"), re.S)
    assert m, f"boardroom.js must keep the block between {start!r} and {end!r}"
    return m.group(0)


def _code() -> str:
    return _block("// ---- Code vs prose (R3-48)", "// ---- end code")


def _js(calls: list[str]):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    script = _code() + "\nprocess.stdout.write(JSON.stringify([" + ",".join(calls) + "]))"
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True, timeout=20)
    return json.loads(out.stdout)


R044 = "\n".join([
    "Step 3. PC PowerShell: connect to the VM.",
    "  ssh -i $HOME\\.ssh\\jbhntr_key ubuntu@203.0.113.7",
    "  sudo -iu jbhntr",
    "  Verify: date -u +%Z",
    '  Expect: prompt jbhntr@vm:~$ and "UTC".',
    "  /sim 301 https://jbhntr.app/ ·",
    "   git -C ~/jbhntr pull --ff-only",
    '  $b="https://jbhntr.app"; foreach($p in "/"){ $p }',
])


def test_r1_122_each_command_is_its_own_block_prose_stays_text():
    got = _js([
        f"parts({json.dumps(R044)})",
        'parts("Run this:\\n```\\ngit pull\\nnode --test x\\n```\\nthen tell me")',
        'parts("```\\nhello world\\nsecond line\\n```")',
        'parts("Hi Founder.\\n  free tier is fine.\\nbye")',
        'isCommand("git -C ~/jbhntr log -1")',
        'isCommand("<0, push line>")',
        'isCommand("cat the logs.")',
        'parts("```\\nunterminated\\n")',
        'parts("Ok.\\n  date is fine.\\n  cat the logs and tell me\\n  echo hello world")',
    ])
    assert got[0] == [
        {"k": "text", "v": "Step 3. PC PowerShell: connect to the VM."},
        {"k": "block", "v": "ssh -i $HOME\\.ssh\\jbhntr_key ubuntu@203.0.113.7"},
        {"k": "block", "v": "sudo -iu jbhntr"},
        {"k": "text", "v": "  Verify:"},
        {"k": "block", "v": "date -u +%Z"},
        {"k": "text", "v": '  Expect: prompt jbhntr@vm:~$ and "UTC".\n  /sim 301 https://jbhntr.app/ ·'},
        {"k": "block", "v": "git -C ~/jbhntr pull --ff-only"},
        {"k": "block", "v": '$b="https://jbhntr.app"; foreach($p in "/"){ $p }'},
    ]
    # a fence of commands -> one block per command; a fence of anything else stays one block
    assert got[1] == [{"k": "text", "v": "Run this:"}, {"k": "block", "v": "git pull"},
                      {"k": "block", "v": "node --test x"}, {"k": "text", "v": "then tell me"}]
    assert got[2] == [{"k": "block", "v": "hello world\nsecond line"}]
    # plain prose (even indented) is untouched
    assert got[3] == [{"k": "text", "v": "Hi Founder.\n  free tier is fine.\nbye"}]
    assert got[4:7] == [True, False, False]
    assert got[7] == [{"k": "block", "v": "unterminated\n"}]   # unclosed fence: the rest is one block, nothing lost
    # indented English that starts with a command word stays prose (conservative isCommand)
    assert got[8] == [{"k": "text", "v": "Ok.\n  date is fine.\n  cat the logs and tell me\n  echo hello world"}]


def test_dom_and_textcontent_only_with_copy_button_and_fallback():
    code = _code()
    chat = _block("// ---- Live chat", "setInterval(poll, 2000);")
    for src in (code, chat):
        assert not re.search(r"innerHTML|insertAdjacentHTML|outerHTML|document\.write", src)
    assert "textContent" in code and "createElement" in code
    assert "navigator.clipboard" in code and "execCommand(\"copy\")" in code and "1500" in code
    assert '"copied"' in code
    # live messages and the server-rendered first load go through the same rich()
    assert "rich(body, m.body)" in chat
    assert re.search(r'querySelectorAll\("#thread \.msg-body"\).*?rich\(', chat, re.S)


def test_first_load_body_is_the_same_text_the_js_renders_live(monkeypatch):
    from web.app.config import config
    from web.app.db import SessionLocal
    from web.app.models import BoardroomMessage
    monkeypatch.setattr(config, "admin_token", AUTH[1])
    body = "r348 Run this:\n  git pull --ff-only\n```\nnpm test\n```\n<b>not html</b> & done"
    with TestClient(app) as c:
        with SessionLocal() as db:
            db.add(BoardroomMessage(role="ceo", body=body))
            db.commit()
        live = [m["body"] for m in c.get("/boardroom/messages.json", auth=AUTH).json() if m["body"].startswith("r348")]
        page = c.get("/boardroom", auth=AUTH).text
    first = [html.unescape(b) for b in re.findall(r'<div class="msg-body">(r348.*?)</div>', page, re.S)]
    assert live == [body] and first == [body], "template must emit the raw (escaped) body for rich() to split"
    assert "<b>not html</b>" not in page
    got = _js([f"parts({json.dumps(first[0])})", f"parts({json.dumps(live[0])})"])
    assert got[0] == got[1] and [p["v"] for p in got[0] if p["k"] == "block"] == ["git pull --ff-only", "npm test"]
