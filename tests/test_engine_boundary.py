"""The open-core boundary (REPO_SPLIT_EXECUTION_PLAN §2/§4), enforced.

1. The shell (``web/``) reaches the engine ONLY through top-level names of the
   ``jbhntr_engine`` façade — never ``jobhunter.*``, never a backend package,
   never a ``jbhntr_engine.<submodule>``.
2. On the capability namespaces (``llm``/``geo``/``embeddings``) the shell uses
   only the attributes the façade documents (``NAMESPACE_API``).
3. The public packages (``jbhntr_engine`` contract+selector, ``jbhntr_engine_demo``)
   never import private code, so they survive the step-4 carve on their own.
4. Both backends implement the whole contract with call-compatible signatures.

Static (AST) checks — no imports of the scanned code, so they are fast and
can't be fooled by import-time side effects.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import jbhntr_engine

ROOT = Path(__file__).resolve().parent.parent
PRIVATE_ROOTS = {"jobhunter", "jbhntr_engine_real"}
BACKENDS = {"jbhntr_engine_real", "jbhntr_engine_demo"}


def _py_files(pkg: str) -> list[Path]:
    files = sorted((ROOT / pkg).rglob("*.py"))
    assert files, f"no python files found under {pkg}/ — the scan would pass vacuously"
    return files


def _imports(path: Path):
    """(lineno, module, names) for every import statement in the file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield node.lineno, a.name, []
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, node.module, [a.name for a in node.names]


def test_shell_imports_engine_only_through_the_facade():
    allowed = set(jbhntr_engine.__all__)
    violations = []
    seen_facade_imports = 0
    for path in _py_files("web"):
        rel = path.relative_to(ROOT)
        for lineno, module, names in _imports(path):
            top = module.split(".")[0]
            if top in PRIVATE_ROOTS or top == "jbhntr_engine_demo":
                violations.append(f"{rel}:{lineno} imports {module} (engine internals)")
            elif top == "jbhntr_engine":
                if module != "jbhntr_engine":
                    violations.append(f"{rel}:{lineno} imports submodule {module}")
                elif not names:
                    violations.append(f"{rel}:{lineno} bare `import jbhntr_engine` — "
                                      "import the façade names explicitly")
                for n in names:
                    seen_facade_imports += 1
                    if n not in allowed:
                        violations.append(f"{rel}:{lineno} imports {n!r}, not in "
                                          "jbhntr_engine.__all__")
    assert not violations, "engine boundary violated:\n" + "\n".join(violations)
    # Guard against a scan that silently stopped seeing anything.
    assert seen_facade_imports >= 50, seen_facade_imports


def test_shell_uses_only_documented_namespace_attributes():
    namespaces = jbhntr_engine.NAMESPACE_API
    violations = []
    checked = 0
    for path in _py_files("web"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "jbhntr_engine":
                for a in node.names:
                    if a.name in namespaces:
                        aliases[a.asname or a.name] = a.name
        if not aliases:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id in aliases):
                checked += 1
                ns = aliases[node.value.id]
                if node.attr not in namespaces[ns]:
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno} "
                                      f"{ns}.{node.attr} is not in NAMESPACE_API[{ns!r}]")
    assert not violations, "\n".join(violations)
    assert checked >= 20, checked


@pytest.mark.parametrize("pkg", ["jbhntr_engine", "jbhntr_engine_demo"])
def test_public_packages_never_import_private_code(pkg):
    bad = [f"{p.relative_to(ROOT)}:{ln} imports {m}"
           for p in _py_files(pkg) for ln, m, _ in _imports(p)
           if m.split(".")[0] in PRIVATE_ROOTS]
    assert not bad, "\n".join(bad)


@pytest.mark.parametrize("backend", sorted(BACKENDS))
def test_backend_implements_the_whole_contract(backend):
    mod = __import__(backend)
    missing = [n for n in jbhntr_engine.BACKEND_API if not hasattr(mod, n)]
    assert not missing, f"{backend} lacks {missing}"
    for ns, attrs in jbhntr_engine.NAMESPACE_API.items():
        gone = [a for a in attrs if not hasattr(getattr(mod, ns), a)]
        assert not gone, f"{backend}.{ns} lacks {gone}"
    assert mod.ENGINE_KIND == ("real" if backend == "jbhntr_engine_real" else "demo")


def _accepts(demo_fn, real_fn) -> list[str]:
    """Real-engine parameters the demo callable can't accept."""
    d = inspect.signature(demo_fn).parameters
    if any(p.kind is p.VAR_KEYWORD for p in d.values()):
        named_ok = True
    else:
        named_ok = False
    out = []
    for name, p in inspect.signature(real_fn).parameters.items():
        if name == "self" or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if name not in d and not named_ok:
            out.append(name)
    return out


def test_demo_callables_are_call_compatible_with_the_real_engine():
    import jbhntr_engine_demo as demo
    import jbhntr_engine_real as real

    problems = []
    for name in jbhntr_engine.BACKEND_API:
        r, d = getattr(real, name), getattr(demo, name)
        if inspect.isclass(r):
            pairs = [("__init__", r.__init__, d.__init__)]
            pairs += [(m, getattr(r, m), getattr(d, m, None))
                      for m in ("triage", "score", "tailor_top", "cover_letter", "refine")
                      if hasattr(r, m)]
            for m, rf, df in pairs:
                if df is None:
                    problems.append(f"{name}.{m} missing in demo")
                elif (bad := _accepts(df, rf)):
                    problems.append(f"{name}.{m}: demo can't take {bad}")
        elif callable(r) and not isinstance(r, dict):
            if (bad := _accepts(d, r)):
                problems.append(f"{name}: demo can't take {bad}")
    assert not problems, "\n".join(problems)


def test_keyed_provider_names_match_between_backends():
    import jbhntr_engine_demo as demo
    import jbhntr_engine_real as real
    assert set(demo.KEYED_PROVIDERS) == set(real.KEYED_PROVIDERS)


def test_default_resolution_is_the_real_engine_with_no_env():
    # The live deploy sets no JBHNTR_ENGINE: auto must land on the real engine.
    assert jbhntr_engine.selected_mode({}) == "auto"
    assert jbhntr_engine.ENGINE_KIND == "real"
    assert jbhntr_engine.engine_problems() == []


def test_contract_types_are_shared_with_the_engine():
    import jobhunter.config
    import jobhunter.models
    assert jobhunter.models.JobPosting is jbhntr_engine.JobPosting
    assert jobhunter.config.Settings is jbhntr_engine.Settings


def test_facade_callables_honour_engine_monkeypatches(monkeypatch):
    """The façade delegates at call time, so a patch on the engine module is seen
    through it (the shell's own tests rely on this)."""
    import jobhunter.discover
    monkeypatch.setattr(jobhunter.discover, "_slugify", lambda name: "patched")
    assert jbhntr_engine.company_slug("Acme Inc") == "patched"


def test_unknown_engine_mode_is_a_loud_error():
    with pytest.raises(ValueError):
        jbhntr_engine.selected_mode({"JBHNTR_ENGINE": "reall"})


# --------------------------------------------------------------------------- #
# R3-16: the private carve stays carved. These heuristics, tables, prompts and
# logger names moved to jbhntr_engine_real/ and are reached only through the
# façade; none may be re-defined (or pasted back) in the public shell.
# --------------------------------------------------------------------------- #
# Names that may not be DEFINED (assigned / def / class) anywhere in web/.
CARVED_DEFINITIONS = {
    # reaper dead-link / login-wall / captcha markers
    "DEAD_MARKERS", "GONE_URL_MARKERS", "CAPTCHA_MARKERS", "WALL_MARKERS",
    # cv_build structured-CV prompt
    "CV_SCHEMA", "_POSITION", "_ENTRY", "_SECTION", "_system",
    # companies_service domain-guess heuristics
    "_AGGREGATOR_HOSTS", "AGGREGATOR_HOSTS", "_COUNTRY_TLD", "_guess_domains",
    "_clearbit_domains", "_live_domain",
    # enrich_service HTML-extraction heuristics (+ corpus_service's tracker copy)
    "_DEAD_URL_BITS", "_TRACKER_BITS", "_EPHEMERAL_URL_BITS", "_CHROME", "_COMMENTS",
    "_JSONLD", "_iter_nodes", "_jsonld_description", "_extract_main",
    # aggregator_calibrate browser check
    "_CDP_HOST", "_AGG_HOSTS", "_statuses", "_DEAD_STATUSES",
}
# Names the shell may keep (call sites/tests use them) but only as values read from
# the façade — never assigned a literal table again.
CARVED_TABLES = {
    "LANE_A_AGGREGATORS", "_LOCALIZED_AGGREGATORS", "KEYED_SOURCES", "SOURCE_CADENCE",
    "SOURCE_COUNTRIES", "DEFAULT_TERMS", "DEFAULT_COUNTRIES", "TERMS_CAP", "TERMS_MAX",
    "COUNTRIES_CAP", "COUNTRIES_MAX", "_AGENCY_MARKETS", "_AGENCY_N", "AGG_SOURCES",
}
# Fingerprints of the carved content: no non-docstring string literal in web/ may
# contain one (case-insensitive). One or two per carved item, chosen so they only
# occur in the engine's copy.
CARVED_FINGERPRINTS = (
    "honest headline", "preserve all substance", "keep the same sections",  # CV prompt
    "careerjet_affid", "france_travail_id", "bundesagentur_enabled",      # ingest tables
    "founders associate",
    "no longer accepting", "offerta non più disponibile", "closedjob=true",  # reaper
    "create an account to view", "verify you are human",
    "autocomplete.clearbit.com",                                           # domains
    "jobviewtrack", "/jobs/land/",                                         # trackers
    "brd.superproxy.io", "optioncarriere.",                                # calibrate
    "jobhunter",                                                           # engine loggers
)


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


def _literal(node: ast.AST) -> bool:
    """A hand-written table: a literal whose leaves are all constants."""
    try:
        ast.literal_eval(node)
        return True
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False


def carved_violations(files) -> list[str]:
    """Every R3-16 carve regression in ``files`` (a list of (label, source))."""
    out = []
    for label, src in files:
        tree = ast.parse(src)
        docs = _docstring_ids(tree)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name in CARVED_DEFINITIONS:
                    out.append(f"{label}:{node.lineno} defines {node.name} (carved, R3-16)")
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    if not isinstance(t, ast.Name):
                        continue
                    if t.id in CARVED_DEFINITIONS:
                        out.append(f"{label}:{node.lineno} defines {t.id} (carved, R3-16)")
                    elif t.id in CARVED_TABLES and node.value is not None and _literal(node.value):
                        out.append(f"{label}:{node.lineno} {t.id} is a literal table again "
                                   "— read it from jbhntr_engine.INGEST_PLAN / the façade")
            elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
                  and id(node) not in docs):
                low = node.value.lower()
                for fp in CARVED_FINGERPRINTS:
                    if fp in low:
                        out.append(f"{label}:{node.lineno} string contains carved "
                                   f"content {fp!r} (R3-16)")
    return out


def _shell_sources():
    return [(str(p.relative_to(ROOT)), p.read_text(encoding="utf-8"))
            for p in _py_files("web")]


def test_carved_engine_content_never_reappears_in_the_shell():
    bad = carved_violations(_shell_sources())
    assert not bad, "private carve regressed:\n" + "\n".join(bad)


def test_carved_content_lives_in_the_private_backend():
    """The carve moved the content, it didn't delete it: every fingerprint and
    every carved definition is present on the private side."""
    private = "\n".join(p.read_text(encoding="utf-8").lower()
                        for p in _py_files("jbhntr_engine_real"))
    missing = [fp for fp in CARVED_FINGERPRINTS if fp not in private]
    assert not missing, missing
    defined = set()
    for p in _py_files("jbhntr_engine_real"):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Assign):
                defined |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    # Names that were renamed on the way (public façade name instead of a private
    # one) or deliberately dropped as duplicates are listed explicitly.
    renamed = {"_AGGREGATOR_HOSTS", "_EPHEMERAL_URL_BITS", "_jsonld_description",
               "_extract_main", "AGG_SOURCES"}
    gone = sorted(CARVED_DEFINITIONS - renamed - defined)
    assert not gone, gone


@pytest.mark.parametrize("snippet", [
    "DEAD_MARKERS = ('no longer available',)\n",                       # reaper markers
    "def _guess_domains(name, code):\n    return []\n",                # domain guess
    "_JSONLD = None\n",                                                # HTML extraction
    "KEYED_SOURCES = {'reed': ('reed_key', None)}\n",                  # ingest table
    "TERMS_MAX = 40\n",                                                # ingest cap
    "PROMPT = 'HONEST HEADLINE: never the target title'\n",            # CV prompt text
    "import logging\nlg = logging.getLogger('jobhunter.sources.keyed')\n",  # logger name
    "URL = 'https://autocomplete.clearbit.com/v1/companies/suggest'\n",
    "HOST = 'brd.superproxy.io:9222'\n",                               # calibrate
])
def test_carve_guard_catches_a_reintroduction(snippet):
    """Mutation check: pasting any carved item back into a shell file trips the
    guard (so a green guard means something)."""
    files = _shell_sources()
    label, src = files[0]
    assert carved_violations([(label, src + "\n" + snippet)]), snippet


def test_carve_guard_allows_facade_reads():
    ok = ("from jbhntr_engine import INGEST_PLAN\n"
          "KEYED_SOURCES = {n: (a, None) for n, a in INGEST_PLAN['keyed_settings'].items()}\n"
          "TERMS_MAX = INGEST_PLAN['terms_max']\n"
          "def check_url(url, client):\n    '''uses jobviewtrack-aware rules'''\n"
          "    return url\n")
    assert carved_violations([("ok.py", ok)]) == []
