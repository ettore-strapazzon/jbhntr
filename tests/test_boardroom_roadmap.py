"""R3-52 — Roadmap epic progress cards (port of Plainfleet BT "R1-185 parseEpics" x3 + "epicCard").
Epics = the 7-column table in company/docs/strategy/ROADMAP.md; tasks = the active (top) sprint rows of
company/state/BACKLOG.md whose task cell starts with [E#]. Built % is computed, never typed."""

import os
import re
import sys
import tempfile

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
from web.app.templating import templates  # noqa: E402

AUTH = ("admin", "r352-admin-token")

ROADMAP_FIX = "\n".join([
    "# Roadmap", "", "Intro text with a | pipe that is not a table row.", "",
    "| # | Epic | Outcome in plain words | Owner | Live | Top roadblocks | Expected live |",
    "|---|---|---|---|---|---|---|",
    "| E1 | **Wallet cards + follow bot** | Anyone can open cards | CTO + CPO | Not live | Card gate (R1-182); `/survey` 404 | 2026-11-21 (proposed) |",
    "| E3 | **Content engine** | Daily brief | CMO + CTO | Paused | All posting paused (R-058) | after R-059 answers |",
    "| E7 | **Company ops** | Founder runs the company | CEO | Live | Unit clean-up | ongoing |",
    "", "## What is in each epic", "| x | y |", "|---|---|", "| E9 | not the epic table |",
])
BACKLOG_FIX = "\n".join([
    "# Backlog", "", "## Sprint T1 — active", "",
    "| id | owner | task | acceptance criteria | deps | status |", "|---|---|---|---|---|---|",
    "| R1-01 | CEO | [E1] Apply **the approved** decisions: see [CHARTER](../CHARTER.md) and `x` | ok | — | **done (c22)** 1225 green |",
    "| R1-02 | CTO | [E1] Second task | ok | — | todo |",
    "| R1-03 | CTO | [E1] Third task with a `a | b` pipe in code | ok `c | d` | — | doing (c30) |",
    "| R1-04 | CMO | [E1] Dropped task | ok | — | cancelled (Founder) |",
    "| R1-05 | CMO | [E1] Replaced task | ok | — | superseded by R1-06 |",
    "| R1-05b | CMO | [E1] Pulled task | ok | — | withdrawn |",
    "| R1-06 | CTO | [E1] Replacement | ok | — | **done** 11-15 ✅ |",
    "| R1-07 | CMO | [E3] Content one | ok | — | blocked on R-059 |",
    "| R1-08 | CTO | No tag at all | ok | — | doing |",
    "| R1-09 | CTO | [E9] Unknown epic tag | ok | — | done |",
    "| R1-10 | CTO | [E7] " + "word " * 60 + "| ok | — | done |",
    "", "## Sprint R3 — older, also says active", "",
    "| id | owner | task | acceptance criteria | deps | status |", "|---|---|---|---|---|---|",
    "| R1-99 | CTO | [E1] older sprint row must not count | ok | — | done |",
])


def test_r1_185_parse_epics_reads_the_7_column_table_in_order_names_plain():
    r = br._parse_epics(ROADMAP_FIX, BACKLOG_FIX)
    assert [e["id"] for e in r["epics"]] == ["E1", "E3", "E7"], "only the epic table (E9 elsewhere ignored)"
    e1 = r["epics"][0]
    assert e1["name"] == "Wallet cards + follow bot"
    assert (e1["outcome"], e1["owner"], e1["live"]) == ("Anyone can open cards", "CTO + CPO", "Not live")
    assert e1["roadblocks"] == "Card gate (R1-182); `/survey` 404", "roadblocks keep inline Markdown"
    assert e1["expected_live"] == "2026-11-21 (proposed)"
    assert [e["live"] for e in r["epics"][1:]] == ["Paused", "Live"]


def test_r1_185_parse_epics_percent_counted_from_active_sprint_only():
    r = br._parse_epics(ROADMAP_FIX, BACKLOG_FIX)
    e1 = r["epics"][0]
    assert [t["id"] for t in e1["tasks"]] == ["R1-01", "R1-02", "R1-03", "R1-06"], \
        "cancelled/superseded/withdrawn not listed; the next ## Sprint section is cut"
    assert [t["status"] for t in e1["tasks"]] == ["done", "todo", "doing", "done"]
    assert (e1["done"], e1["total"], e1["pct"]) == (2, 4, 50)
    assert [r["epics"][1][k] for k in ("done", "total", "pct")] == [0, 1, 0]
    assert br._parse_epics(ROADMAP_FIX, "")["epics"][0]["pct"] == 0, "no tasks: 0 %, never a ZeroDivisionError"
    assert br._parse_epics(ROADMAP_FIX, BACKLOG_FIX.replace("| todo |", "| done |"))["epics"][0]["pct"] == 75


def test_r1_185_parse_epics_other_bucket_titles_and_backtick_pipes():
    r = br._parse_epics(ROADMAP_FIX, BACKLOG_FIX)
    assert [t["id"] for t in r["other"]["tasks"]] == ["R1-08", "R1-09"]
    assert [r["other"][k] for k in ("done", "total", "pct")] == [1, 2, 50]
    assert r["other"]["tasks"][1]["title"] == "[E9] Unknown epic tag", "unknown tag kept visible"
    t1 = r["epics"][0]["tasks"][0]
    assert (t1["owner"], t1["title"]) == ("CEO", "Apply the approved decisions: see CHARTER and x")
    assert r["epics"][0]["tasks"][2]["title"] == "Third task with a a | b pipe in code"
    long = r["epics"][2]["tasks"][0]["title"]
    assert len(long) <= 140 and long.endswith("…")
    assert br._parse_epics("", BACKLOG_FIX)["epics"] == []
    assert len(br._parse_epics("", BACKLOG_FIX)["other"]["tasks"]) == 8


def test_cells_never_split_inside_backticks():
    assert br._cells("| a | `x | y` | **b** |") == ["a", "`x | y`", "**b**"]


def test_real_roadmap_and_backlog_parse():
    r = br._parse_epics(br._read(br.DOCS / "strategy" / "ROADMAP.md"), br._read(br.STATE / "BACKLOG.md"))
    ids = [e["id"] for e in r["epics"]]
    assert ids[:5] == ["E1", "E2", "E3", "E4", "E5"], ids
    e5 = r["epics"][4]
    assert e5["total"] > 0 and 0 <= e5["pct"] <= 100
    # the real R3-52 row has a `|` inside backticks; it must still parse as an E5 task with a status
    assert all(t["status"] for t in e5["tasks"])
    assert any(t["id"] == "R3-52" for t in e5["tasks"])


def _card(e, open_=False):
    return str(templates.env.get_template("partials/epic_card.html").module.epic_card(e))


def test_r1_185_epic_card_progressbar_text_live_label_and_collapsed_tasks():
    r = br._parse_epics(ROADMAP_FIX, BACKLOG_FIX)
    html = _card(r["epics"][0])
    assert html.count('role="progressbar"') == 1
    for attr in ('aria-valuenow="50"', 'aria-valuemin="0"', 'aria-valuemax="100"',
                 'aria-label="E1 Wallet cards + follow bot: 2 of 4 tasks done (50%)"'):
        assert attr in html, attr
    assert "2/4 done · 50%" in html
    assert re.search(r'class="epic-live epic-live-notlive">Not live<', html), "label in words, class only tints"
    assert "2026-11-21 (proposed)" in html
    assert "Card gate (R1-182); <code>/survey</code> 404" in html
    assert re.search(r'<details class="epic-tasks" data-group="epic-E1">\s*<summary>Tasks \(4\)</summary>', html), \
        "collapsed by default; data-group = open state kept by boardroom.js across refresh"
    assert re.search(r'<b>R1-02</b> <span class="epic-st">todo</span> <span class="muted">CTO</span> <span>Second task</span>', html)
    assert 'epic-live-paused">Paused<' in _card(r["epics"][1])
    assert 'aria-label="Other: 1 of 2 tasks done (50%)"' in _card(r["other"])


def test_roadmap_tab_renders_cards_and_collapsed_sources(monkeypatch):
    from web.app.config import config
    monkeypatch.setattr(config, "admin_token", AUTH[1])
    with TestClient(app) as c:
        page = c.get("/boardroom", auth=AUTH).text
    panel = page.split('data-panel="roadmap"', 1)[1]
    assert panel.count('role="progressbar"') >= 5
    for grp in ("roadmap-backlog", "roadmap-timeline", "roadmap-log"):
        assert re.search(r'<details[^>]*data-group="%s"' % grp, panel) and \
            not re.search(r'<details[^>]*data-group="%s"[^>]*\bopen\b' % grp, panel), grp
