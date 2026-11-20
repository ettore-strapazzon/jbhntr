"""R3-51 — Boardroom Documents: tree over all of company/, AND filter + live count, modal viewer whose
relative links stay inside company/, and the server path rule. Port of BT "R1-131 Documents tree",
"R1-131: relative links", "R1-131: page has a Documents tab", "safePath". The pure JS helpers run in node."""

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
AUTH = ("admin", "r351-admin-token")
# A just-enough DOM for the node run: elements are plain objects, so the output is JSON-comparable.
FAKE_DOM = """var document = {
  createElement: function (t) { return { tag: t, attrs: {}, kids: [],
    setAttribute: function (k, v) { this.attrs[k] = v; }, appendChild: function (c) { this.kids.push(c); return c; } }; },
  createTextNode: function (t) { return { tag: "#text", text: t }; } };
function plain(n) { return n.tag === "#text" ? n.text : (n.textContent != null ? n.textContent : "") + n.kids.map(plain).join(""); }
"""


def _js(calls: list[str]):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    m = re.search(r"// ---- Documents \(R3-51\).*?// ---- end documents", JS.read_text(encoding="utf-8"), re.S)
    assert m, "boardroom.js must keep the Documents helpers between the R3-51 markers"
    script = FAKE_DOM + m.group(0) + "\nprocess.stdout.write(JSON.stringify([" + ",".join(calls) + "]))"
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True, timeout=20)
    return json.loads(out.stdout)


PATHS = ["docs/tech/ARCHITECTURE.md", "state/BACKLOG.md", "README.md", "ops/team/chat.md", "CHARTER.md",
         "agents/cto.md", "updates/2026-11-16.md", "RUNBOOK.md", "state/LEDGER.csv",
         "docs/strategy/TIMELINE.md", "zeta/x.md", "docs/README.md"]


def test_documents_tree_groups_in_fixed_order_and_filter_needs_every_term():
    p = json.dumps(PATHS)
    full, readme, two, path, none, empty = _js([
        f"docTree({p}, '')", f"docTree({p}, '  ReadMe ')", f"docTree({p}, 'team chat')",
        f"docTree({p}, 'DOCS/tech')", f"docTree({p}, 'nope')", "docTree([], '')"])
    assert (full["total"], full["shown"]) == (12, 12)
    assert [g["name"] for g in full["groups"]] == ["CHARTER", "state", "updates", "agents", "docs", "ops", "zeta", "root"]
    assert sorted(f for g in full["groups"] for f in g["files"]) == sorted(PATHS), "nothing missed, nothing doubled"
    assert next(g for g in full["groups"] if g["name"] == "root")["files"] == ["README.md", "RUNBOOK.md"]
    assert (readme["total"], readme["shown"]) == (12, 2)
    assert [g["name"] for g in readme["groups"]] == ["docs", "root"], "groups without a match are hidden"
    assert [f for g in two["groups"] for f in g["files"]] == ["ops/team/chat.md"], "all terms must match"
    assert [f for g in path["groups"] for f in g["files"]] == ["docs/tech/ARCHITECTURE.md"], "matches the path, any case"
    assert none["shown"] == 0 and empty["total"] == 0
    js = JS.read_text(encoding="utf-8")
    assert '" of " + t.total + " files"' in js, "live 'N of M files' count"


def test_relative_links_resolve_inside_company_external_new_tab_other_schemes_plain():
    got = _js([
        'resolveDoc("../strategy/GTM.md", "docs/tech/ARCHITECTURE.md")',
        'resolveDoc("../../state/BACKLOG.md#r3-51", "docs/tech/ARCHITECTURE.md")',
        'resolveDoc("cycle.md?x=1", "ops/team/chat.md")',
        'resolveDoc("docs/README.md", "CHARTER.md")',
        'resolveDoc("/state/BACKLOG.md", "docs/x.md")',
        'resolveDoc("./notes.txt", "updates/2026-11-16.md")',
        'resolveDoc("../../web/app/main.md", "docs/x.md")',      # climbs out of company/
        'resolveDoc("../../../etc/passwd.md", "docs/a/b.md")',
        'resolveDoc("../web/app/main.py", "docs/x.md")',         # not a document type
        'resolveDoc("javascript:alert(1)//x.md", "docs/x.md")',
        'resolveDoc("", "docs/x.md")',
        'docLink("GTM", "../strategy/GTM.md", "docs/tech/A.md")',
        'docLink("site", "https://jbhntr.app/x", "docs/a.md")',
        'docLink("bad", "javascript:alert(1)", "docs/a.md")',
        'docLink("mail", "mailto:x@example.com", "docs/a.md")',
        'docLink("out", "../../../x.md", "docs/a.md")',
    ])
    assert got[:6] == ["docs/strategy/GTM.md", "state/BACKLOG.md", "ops/team/cycle.md", "docs/README.md",
                       "state/BACKLOG.md", "updates/notes.txt"]
    assert got[6:11] == [None] * 5
    rel, ext, js_, mail, out = got[11:]
    assert rel["tag"] == "a" and rel["attrs"]["data-doc"] == "docs/strategy/GTM.md"
    assert rel["href"] == "/boardroom/doc?path=docs%2Fstrategy%2FGTM.md"
    assert ext["tag"] == "a" and ext["href"] == "https://jbhntr.app/x" and ext["target"] == "_blank"
    assert "noopener" in ext["rel"]
    for n, label in ((js_, "bad"), (mail, "mail"), (out, "out")):
        assert n["tag"] == "span" and n["textContent"] == label and "href" not in n


def test_viewer_body_txt_verbatim_markdown_links_and_text_only():
    txt, md_, csv = _js([
        'docBody("# not a heading\\n**raw** [x](y.md)", "updates/post.txt")',
        'docBody("# Title\\n\\nSee [GTM](../strategy/GTM.md) and <script>x</script>.\\n\\n| a | b |\\n|---|---|\\n| 1 | 2 |\\n\\n```\\nls\\n```\\n- one\\n- two", "docs/tech/A.md")',
        'docBody("a,b\\n1,2", "state/LEDGER.csv")',
    ])
    assert txt["tag"] == "pre" and txt["textContent"] == "# not a heading\n**raw** [x](y.md)" and not txt["kids"]
    assert csv["tag"] == "pre" and csv["textContent"] == "a,b\n1,2"
    tags = [k["tag"] for k in md_["kids"]]
    assert tags == ["h3", "p", "table", "pre", "ul"]
    p = md_["kids"][1]
    link = next(k for k in p["kids"] if k["tag"] == "a")
    assert link["attrs"]["data-doc"] == "docs/strategy/GTM.md"
    assert any(k.get("text", "").endswith("and <script>x</script>.") for k in p["kids"]), "HTML stays a text node"
    js = JS.read_text(encoding="utf-8")
    block = re.search(r"// ---- Documents \(R3-51\).*?// ---- end documents", js, re.S).group(0)
    assert "innerHTML" not in block


@pytest.mark.parametrize("ok", ["CHARTER.md", "agents/SKILLS.md", "state/LEDGER.csv", "docs/strategy/GTM.md",
                                "updates/2026-11-16.md", "RUNBOOK.md", "agents/x/y.md", "docs/legal/a.pdf",
                                "updates/post.txt"])
def test_safe_path_accepts_company_documents(ok):
    assert br._safe_doc_path(ok), ok


@pytest.mark.parametrize("no", ["state/.env", ".env", ".env.md", "docs/.env.local.md", ".github/w.md", "docs/../x.md",
                                "../x.md", "../web/app/main.py", "./x.md", "/x.md", "/etc/passwd", "C:/x.md",
                                "docs//x.md", "docs\\x.md", "docs/a.html", "docs/a b.md", "docs/x;y.md", "docs/x.md/",
                                "state/x.jsonl", "docs/api_secret.md", "state/token.txt", "docs/credentials.md",
                                "docs/password.csv", "d/" + "a" * 300 + ".md", "", None])
def test_safe_path_rejects_traversal_absolute_hidden_and_secret_looking(no):
    assert not br._safe_doc_path(no), repr(no)


@pytest.fixture
def client(monkeypatch):
    from web.app.config import config
    monkeypatch.setattr(config, "admin_token", AUTH[1])
    with TestClient(app) as c:  # the context runs startup, which creates the tables
        yield c


def test_doc_route_confined_to_company_and_raw_mode(client, tmp_path, monkeypatch):
    assert client.get("/boardroom/doc?path=CHARTER.md", auth=AUTH).status_code == 200
    raw = client.get("/boardroom/doc?path=CHARTER.md&raw=1", auth=AUTH)
    assert raw.status_code == 200 and raw.headers["content-type"].startswith("text/plain")
    assert raw.text == (br.COMPANY / "CHARTER.md").read_text(encoding="utf-8")
    for bad in ("../web/app/main.py", "../README.md", "/etc/passwd", "docs/../../README.md", "nope.md",
                "../company/CHARTER.md"):
        assert client.get("/boardroom/doc", params={"path": bad, "raw": 1}, auth=AUTH).status_code == 404, bad
    # A symlink inside company/ that points outside it is refused (no symlink escape).
    root = tmp_path / "company"
    (root / "docs").mkdir(parents=True)
    (tmp_path / "outside.md").write_text("secret", encoding="utf-8")
    (root / "docs" / "ok.md").write_text("fine", encoding="utf-8")
    (root / "docs" / "link.md").symlink_to(tmp_path / "outside.md")
    monkeypatch.setattr(br, "COMPANY", root)
    assert client.get("/boardroom/doc?path=docs/ok.md&raw=1", auth=AUTH).text == "fine"
    assert client.get("/boardroom/doc?path=docs/link.md&raw=1", auth=AUTH).status_code == 404
    assert br._doc_index() == ["docs/ok.md"]


def test_page_has_documents_tab_filter_count_viewer_and_the_whole_company_tree(client):
    page = client.get("/boardroom", auth=AUTH).text
    assert re.search(r'data-tab="docs"[^>]*>Documents<', page)
    docs = page.split('data-panel="docs"', 1)[1].split("</section>", 1)[0]
    assert re.search(r'<input[^>]*type="search"[^>]*id="docs-filter"[^>]*aria-label="[^"]+"', docs)
    assert re.search(r'id="docs-count"[^>]*aria-live="polite"', docs)
    assert re.search(r'id="viewer"[^>]*role="dialog"[^>]*aria-modal="true"', docs) and 'id="viewer-close"' in docs
    paths = json.loads(re.search(r"data-paths='([^']*)'", docs).group(1).replace("&#34;", '"'))
    assert {"CHARTER.md", "docs/README.md", "agents/cto.md"} <= set(paths)
    assert all(br._safe_doc_path(p) for p in paths) and not any(p.endswith(".jsonl") for p in paths)
    assert paths == br._doc_index()
