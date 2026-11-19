"""R3-45 — Founder's tasks: Do now / Later / Recently closed grouping, header-only status word
(also behind an emoji or **markup**), one <details> per request, and the stale-header check
that also runs on the real company/state/REQUESTS.md."""

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
from web.app.routes import boardroom as br  # noqa: E402

JS = Path(__file__).resolve().parents[1] / "web" / "app" / "static" / "boardroom.js"
AUTH = ("admin", "r345-admin-token")


def _ids(blocks):
    return [b.split(" ")[1] for b in blocks]


def test_client_helpers_status_and_grouping():
    reqs = ("# R\n### R-039 · x · on hold\nA\n### R-040 · y · done 2026-10-22\nB\n"
            "### R-044 · z · open 2026-10-27\nC\n### R-045 · w · **approved**\n")
    g = br._group_requests(reqs)
    assert _ids(g["now"]) == ["R-044"]
    assert _ids(g["later"]) == ["R-039"]
    assert _ids(g["closed"]) == ["R-045", "R-040"]


def test_status_word_after_emoji_or_markup_still_closes_the_request():
    reqs = ("### R-046 · Pick · open 2026-11-16 · ✅ answered 2026-11-16\nA\n"
            "### R-047 · x · ✔️ **done**\nB\n### R-048 · y · open\nC\n")
    assert _ids(br._group_requests(reqs)["now"]) == ["R-048"]
    assert br._req_status("### R-046 · Pick · open 2026-11-16 · ✅ answered 2026-11-16") == "closed"
    assert br._req_status("### R-044 · M0 · open 2026-10-27 · **steps 1–2 done 2026-11-15**") == "open", \
        "'done' mid-segment is not a status"
    assert br._req_status("### R-050 · Done deal · open") == "open", "a status word in the title is not the status"


def test_grouped_into_do_now_later_and_last_5_closed_newest_first():
    heads = ["R-001 · a · done", "R-039 · b · on hold 2026-10-21", "R-040 · c · done", "R-041 · d · superseded by R-040",
             "R-042 · e · **approved**", "R-043 · f · cancelled", "R-044 · g · open 2026-10-27 · **steps 1–2 done**",
             "R-045 · h · parked", "R-046 · i · open · ✅ answered", "R-047 · j · no status yet",
             "R-048 · k · _withdrawn_", "R-049 · l · closed"]
    g = br._group_requests("# R\n" + "\n".join("### " + x + "\nbody\n\n---" for x in heads))
    assert _ids(g["now"]) == ["R-044", "R-047"]
    assert _ids(g["later"]) == ["R-039", "R-045"]
    assert _ids(g["closed"]) == ["R-049", "R-048", "R-046", "R-043", "R-042"]
    assert not any(b.rstrip().endswith("---") for b in g["now"] + g["later"] + g["closed"])


def test_stale_header_r1_181_fixture():
    fix = "\n".join([
        "# R",
        "### R-060 · Pause posting · open 2026-11-18", "1. paste",
        "Answer (Founder, via Boardroom, 2026-11-18): `0`, no live posting line left. ✅ done.",
        "### R-061 · Attachments · open 2026-11-16", "Answer (Founder): step 5b passed. **R-061 done.**",
        "### R-062 · Brief · parked 2026-11-18", "Closed 2026-11-18 (superseded by R-063).",
        # partial answers, reply templates, commands and already-closed headers are not offenders
        "### R-063 · Two parts · open", "Answer (Founder): Part A ✅ done; Part B still open.",
        "Claude check: R-063 = DONE except W9.", "**Update:** line 1 is already done. Only line 2 is still needed.",
        "### R-064 · Template · open", "> \"R-064 done: N1 `<…>`\"", "```", "echo DONE", "```",
        "### R-065 · Real done · done 2026-11-18", "Answer: ✅ done.",
    ])
    assert [r[0] for r in br._stale_requests(fix)] == ["R-060", "R-061", "R-062"]


def test_stale_header_r1_181_real_requests_md():
    real = (br.STATE / "REQUESTS.md").read_text(encoding="utf-8")
    stale = br._stale_requests(real)
    assert not stale, ("a body resolves the request under an open/parked header — fix the `### R-NNN` header "
                       "status word in company/state/REQUESTS.md: " + "; ".join(f"{i}: {ln}" for i, ln in stale))


REQS = ("# Requests\n\n---\n"
        "### R-060 · Run the fix (≈ 2 min, $0) · open\nStep 1: run it\n\n- detail line\n\n---\n"
        "### R-059 · Docs visibility · done 2026-11-18\nResolved body\n\n---\n"
        "### R-058 · Later thing · parked\nParked body\n\n---\n"
        "### R-057 · Approve **X** post · open 2026-11-18\nSecond open\n")


@pytest.fixture
def page(monkeypatch, tmp_path):
    from web.app.config import config
    monkeypatch.setattr(config, "admin_token", AUTH[1])
    (tmp_path / "REQUESTS.md").write_text(REQS, encoding="utf-8")
    monkeypatch.setattr(br, "STATE", tmp_path)
    with TestClient(app) as c:
        return c.get("/boardroom", auth=AUTH).text


def _details(page_html, rid):
    m = re.search(r'<details[^>]*data-req="%s"[^>]*>\s*<summary>(.*?)</summary>' % rid, page_html, re.S)
    assert m, rid + " must render as its own <details> with the header as <summary>"
    return m.group(0), m.group(1)


def test_r1_177_each_request_is_a_details_with_header_summary(page):
    tag, summary = _details(page, "R-060")
    assert summary == "R-060 · Run the fix (≈ 2 min, $0) · open"
    assert _details(page, "R-057")[1] == "R-057 · Approve <strong>X</strong> post · open 2026-11-18"
    body = page.split('data-req="R-060"', 1)[1].split("</details>", 1)[0]
    assert "Step 1: run it" in body and "<li>detail line</li>" in body
    assert "### R-060" not in page
    for grp, title in (("later", "Later / on hold (1)"), ("closed", "Recently closed (1)")):
        m = re.search(r'<details[^>]*data-group="%s"[^>]*>\s*<summary>([^<]*)</summary>' % grp, page)
        assert m and m.group(1) == title and " open" not in m.group(0), grp + " group is collapsed"
    assert "Do now" in page


def test_r1_184_open_requests_default_expanded_later_closed_collapsed(page):
    assert " open" in _details(page, "R-060")[0] and " open" in _details(page, "R-057")[0]
    assert " open" not in _details(page, "R-059")[0].replace("data-req", "")
    assert " open" not in _details(page, "R-058")[0].replace("data-req", "")


def test_pill_counts_do_now(page):
    m = re.search(r'<button[^>]*data-tab="pending"[^>]*>([^<]*)</button>', page)
    assert m and m.group(1).strip().endswith("(2)")


def _req_toggle(mem, rid, is_open, default):
    """Evaluate boardroom.js's own reqToggle() in node."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    m = re.search(r"^ *function reqToggle\(.*\}$", JS.read_text(encoding="utf-8"), re.M)
    assert m, "boardroom.js must keep reqToggle() as a one-line pure function"
    args = ", ".join(json.dumps(a) for a in (mem, rid, is_open, default))
    out = subprocess.run([node, "-e", f"{m.group(0)}\nprocess.stdout.write(JSON.stringify(reqToggle({args})))"],
                         capture_output=True, text=True, check=True, timeout=20)
    return json.loads(out.stdout)


def test_r1_184_founder_choice_per_id_is_a_deviation_from_the_default():
    mem = _req_toggle({}, "R-060", False, True)          # collapse an open request
    assert mem == {"R-060": False}
    mem = _req_toggle(mem, "R-059", True, False)         # expand a closed one
    assert mem == {"R-060": False, "R-059": True}
    assert _req_toggle(mem, "R-060", True, True) == {"R-059": True}, "back to default -> forgotten"
    assert _req_toggle({}, "R-061", True, True) == {}, "the default expansion never counts as a choice"
    assert _req_toggle({}, "group:later", True, False) == {"group:later": True}, "group open state kept too"


def test_page_js_restores_saved_open_state():
    js = JS.read_text(encoding="utf-8")
    assert "details[data-req], details[data-group]" in js and "localStorage" in js
