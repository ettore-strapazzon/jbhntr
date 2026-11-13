"""Static "does this GET handler change state?" scanner (R3-23).

Shared by the no-GET-writes guards in test_admin_csrf.py, test_boardroom_csrf.py
and test_public_get_side_effects.py. Scanning only the handler's own source missed
a write hidden one call away (`def page(): _bump(db)` where `_bump` commits), so
the scanner also reads the source of every project function the handler calls
directly — ONE level deep, by design: deep enough to catch the helper-hidden write,
shallow enough that a guard failure always points at a function the handler names.

Callees followed: a bare `name(...)` or a `module.name(...)` call that resolves, in
the handler's module globals, to a plain Python function (or a module's function)
defined in project code (web.*, jobhunter.*, tests.*). Methods on objects
(`db.add`, `user.save`), builtins and library functions are not followed — the
handler's own source already shows those call sites to the marker scan.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
import types

PROJECT_PREFIXES = ("web.", "jobhunter.", "tests.")


def _source(fn) -> str:
    src = inspect.getsource(inspect.unwrap(fn))
    assert "def " in src, fn       # a source we could not read must not pass as clean
    return src


def _project_function(obj):
    obj = inspect.unwrap(obj) if callable(obj) else obj
    if isinstance(obj, types.FunctionType) and \
            (obj.__module__ or "").startswith(PROJECT_PREFIXES):
        return obj
    return None


def direct_callees(fn) -> list:
    """Project functions `fn` calls by name or via `module.name`, one level deep."""
    fn = inspect.unwrap(fn)
    tree = ast.parse(textwrap.dedent(_source(fn)))
    g = fn.__globals__
    out, seen = [], set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f, target = node.func, None
        if isinstance(f, ast.Name):
            target = g.get(f.id)
        elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            mod = g.get(f.value.id)
            if isinstance(mod, types.ModuleType):
                target = getattr(mod, f.attr, None)
        # function-local `from x import y` inside the handler:
        if target is None and isinstance(f, ast.Name):
            for imp in ast.walk(tree):
                if isinstance(imp, ast.ImportFrom) and imp.module is not None:
                    for alias in imp.names:
                        if (alias.asname or alias.name) == f.id:
                            target = _resolve_from_import(fn, imp, alias.name)
        target = _project_function(target) if target is not None else None
        if target is not None and target is not fn and id(target) not in seen:
            seen.add(id(target))
            out.append(target)
    return out


def _resolve_from_import(fn, imp: ast.ImportFrom, name: str):
    import importlib
    try:
        if imp.level:
            pkg = fn.__module__.rsplit(".", imp.level)[0]
            modname = f"{pkg}.{imp.module}" if imp.module else pkg
        else:
            modname = imp.module
        return getattr(importlib.import_module(modname), name, None)
    except Exception:
        return None


def scan(fn, marks) -> dict[str, list[str]]:
    """{where: [marks found]} for the handler itself and each direct project callee.
    `where` is "self" or the callee's qualified name, so a failure names the helper."""
    hits = {}
    own = [m for m in marks if m in _source(fn)]
    if own:
        hits["self"] = own
    for callee in direct_callees(fn):
        found = [m for m in marks if m in _source(callee)]
        if found:
            hits[f"{callee.__module__}.{callee.__qualname__}"] = found
    return hits
