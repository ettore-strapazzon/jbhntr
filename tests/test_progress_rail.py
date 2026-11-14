"""R3-31: the scan progress rail (partials/progress.html) maps every stage the
worker writes to a rail step. It used to guess with keyword checks in the
template, so "Checking links…" and "Saving results…" dropped back to step 0.

The guard: enumerate every stage text `search_service.py` can write (every
`stage=` literal / f-string, and every `_Heartbeat` label in its "LABEL d/t"
form) straight from the source, and require each to match an explicit rule.
A new stage message without a rule fails here instead of falling through.
"""

from __future__ import annotations

import ast
import re
import types
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "web" / "app" / "services" / "search_service.py"


def _render_fstring(node: ast.JoinedStr) -> str:
    return "".join(v.value if isinstance(v, ast.Constant) else "12" for v in node.values)


def _worker_stages() -> set[str]:
    stages: set[str] = set()
    for node in ast.walk(ast.parse(SRC.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != "stage":
                continue
            v = kw.value
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                stages.add(v.value)
            elif isinstance(v, ast.JoinedStr):
                # The heartbeat's own f"{self.label} {done}/{total}" has no literal
                # prefix; its labels are enumerated below instead.
                if isinstance(v.values[0], ast.Constant):
                    stages.add(_render_fstring(v))
            else:
                raise AssertionError(f"line {node.lineno}: stage= is not a literal; "
                                     "add it to this test's enumeration")
        if isinstance(node.func, ast.Name) and node.func.id == "_Heartbeat":
            label = node.args[2]
            assert isinstance(label, ast.Constant), f"line {node.lineno}: label not literal"
            stages.add(f"{label.value} 3/10")
    stages.discard("")                     # failed/reaped: the rail is not shown
    return stages


def test_enumeration_finds_the_known_stages():
    stages = _worker_stages()
    for s in ("Starting…", "Checking links…", "Checking links… 3/10", "Scoring 3/10",
              "Saving results…", "Shortlisting 12 jobs…", "Shortlisting 3/10"):
        assert s in stages, s
    assert len(stages) >= 15


def test_every_worker_stage_maps_to_an_explicit_rail_step():
    from web.app.services.scan_stages import stage_step
    unmapped = sorted(s for s in _worker_stages() if stage_step(s) is None)
    assert unmapped == [], f"stage text with no rail rule: {unmapped}"


def test_only_the_opening_stages_sit_on_step_zero():
    from web.app.services.scan_stages import stage_step
    on_zero = sorted(s for s in _worker_stages() if stage_step(s) == 0)
    assert all(s.startswith(("Starting", "Understanding your profile")) for s in on_zero), on_zero


@pytest.mark.parametrize("stage,step", [
    ("Starting…", 0),
    ("Understanding your profile… 1/3", 0),
    ("Searching the job corpus…", 1),
    ("Collecting job postings… 3/7", 1),
    ("Filtering 120 jobs to your locations…", 1),
    ("Shortlisting 300 jobs…", 2),
    ("Shortlisting 125/300", 2),
    ("Scoring 40 jobs in detail…", 3),
    ("Scoring: reading job descriptions 5/40", 3),
    ("Scoring 120/300", 3),
    ("Checking links…", 3),
    ("Checking links… 4/12", 3),
    ("Saving results…", 3),
    ("Done", 3),
])
def test_stage_steps(stage, step):
    from web.app.services.scan_stages import stage_step
    assert stage_step(stage) == step


def test_unknown_or_empty_stage_is_none():
    from web.app.services.scan_stages import stage_step
    assert stage_step(None) is None and stage_step("") is None
    assert stage_step("Rebalancing the flux capacitor") is None


def _active_index(html: str) -> int:
    steps = re.findall(r'<div class="stage ([a-z ]*)">', html)
    assert len(steps) == 4, html
    return [c.strip() for c in steps].index("on")


@pytest.mark.parametrize("stage,step", [
    ("Checking links…", 3),
    ("Checking links… 4/12", 3),
    ("Saving results…", 3),
    ("Scoring 120/300", 3),
    ("Shortlisting 125/300", 2),
    ("Collecting job postings… 3/7", 1),
    (None, 0),
])
def test_rendered_rail_highlights_the_mapped_step(stage, step):
    from web.app.templating import templates
    search = types.SimpleNamespace(id=1, stage=stage, raw_count=0, located_count=0,
                                   ranked_count=0)
    html = templates.get_template("partials/progress.html").render(search=search)
    assert _active_index(html) == step
