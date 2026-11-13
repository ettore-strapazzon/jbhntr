"""Carve the PRIVATE engine into its own installable wheel (repo-split step 3).

    python scripts/build_engine_wheel.py            # build dist/jbhntr_engine-*.whl
    python scripts/build_engine_wheel.py --verify   # ...and prove the split boots

The private ``jbhntr-engine`` distribution = ``jobhunter/`` + ``jbhntr_engine_real/``
(sources, prompts, ranking, ingestion helpers, discovery). Everything else —
the shell, the ``jbhntr_engine`` contract/selector, the demo engine — is public.
The wheel is staged in a temp dir from a generated ``pyproject.toml``, so no
packaging file lands at the repo root (Railway/Nixpacks keeps building the
monorepo exactly as today until the step-6 cut-over).

``--verify`` proves, locally and offline (no repo, no push, no token):
  1. a PUBLIC snapshot (repo minus the private packages) runs on the demo engine
     with nothing private present, and production refuses to boot on it;
  2. the same snapshot + the private wheel installed into a separate target dir
     resolves to the REAL engine — what step 6 does with ``pip install`` from the
     private repo.

Nothing here creates repos, pushes, or needs ENGINE_READ_TOKEN (steps 4-7 need a
separate Founder go).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRIVATE_PACKAGES = ("jobhunter", "jbhntr_engine_real")
PUBLIC_PATHS = ("web", "jbhntr_engine", "jbhntr_engine_demo", "config", "data")
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.sqlite", "og")

PYPROJECT = """\
[build-system]
requires = ["setuptools>=77"]
build-backend = "setuptools.build_meta"

[project]
name = "jbhntr-engine"
version = "{version}"
description = "JBHNTR private matching engine (proprietary - not for distribution)"
license = "LicenseRef-Proprietary"
requires-python = ">=3.10"
# The public contract package `jbhntr_engine` is provided by the shell repo the
# engine is installed into; third-party deps match the shell's requirements.txt.
dependencies = {deps}

[tool.setuptools.packages.find]
include = ["jobhunter", "jobhunter.*", "jbhntr_engine_real", "jbhntr_engine_real.*"]
"""


def _deps() -> list[str]:
    out = []
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            out.append(line)
    return out


def build(out_dir: Path) -> Path:
    from importlib.util import module_from_spec, spec_from_file_location
    spec = spec_from_file_location("_jh", ROOT / "jobhunter" / "__init__.py")
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    version = getattr(mod, "__version__", "0.0.0")

    with tempfile.TemporaryDirectory() as stage:
        stage_p = Path(stage)
        for pkg in PRIVATE_PACKAGES:
            shutil.copytree(ROOT / pkg, stage_p / pkg, ignore=_IGNORE)
        (stage_p / "pyproject.toml").write_text(
            PYPROJECT.format(version=version, deps=repr(_deps()).replace("'", '"')))
        out_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "-q",
                        "-w", str(out_dir), str(stage_p)], check=True)
    wheels = sorted(out_dir.glob("jbhntr_engine-*.whl"), key=lambda p: p.stat().st_mtime)
    if not wheels:
        raise SystemExit("wheel build produced no jbhntr_engine-*.whl")
    return wheels[-1]


_PROBE = """
import jbhntr_engine, json
problems = jbhntr_engine.engine_problems()
real = None
try:
    import jbhntr_engine_real as real
except ImportError:
    pass
print(json.dumps({"kind": jbhntr_engine.ENGINE_KIND, "problems": problems,
                  "real_from": getattr(real, "__file__", None)}))
"""

_BOOT = """
from fastapi.testclient import TestClient
from web.app.main import app
try:
    with TestClient(app) as c:
        print("BOOTED", c.get("/health").status_code)
except RuntimeError as exc:
    print("REFUSED", exc)
"""


def verify(wheel: Path) -> None:
    import json

    with tempfile.TemporaryDirectory() as tmp:
        tmp_p = Path(tmp)
        public = tmp_p / "public"
        public.mkdir()
        for name in PUBLIC_PATHS:
            src = ROOT / name
            if src.is_dir():
                shutil.copytree(src, public / name, ignore=_IGNORE)
        assert not any((public / p).exists() for p in PRIVATE_PACKAGES)
        target = tmp_p / "site"
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", "-q",
                        "--target", str(target), str(wheel)], check=True)

        base = {k: v for k, v in os.environ.items()
                if k not in ("PYTHONPATH", "JBHNTR_ENGINE", "DEBUG")}
        base.update(DATABASE_URL=f"sqlite:///{tmp_p}/v.sqlite", SECRET_KEY="v" * 48,
                    BASE_URL="https://jbhntr.test")
        if "FILE_ENCRYPTION_KEY" not in base:
            from cryptography.fernet import Fernet
            base["FILE_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

        def run(code: str, extra_path: Path | None = None, **env) -> str:
            e = dict(base, **env)
            if extra_path:
                e["PYTHONPATH"] = str(extra_path)
            r = subprocess.run([sys.executable, "-c", code], cwd=public, env=e,
                               capture_output=True, text=True, timeout=300)
            if r.returncode:
                raise SystemExit(f"probe failed:\n{r.stdout}\n{r.stderr[-3000:]}")
            return r.stdout.strip().splitlines()[-1]

        alone = json.loads(run(_PROBE))
        assert alone["kind"] == "demo" and alone["problems"], alone
        print(f"[1] public snapshot alone -> engine={alone['kind']} (fallback recorded)")
        refused = run(_BOOT, DEBUG="false")
        assert refused.startswith("REFUSED"), refused
        print("[1] ...and production refuses to boot on it: OK")
        dev = run(_BOOT, DEBUG="true", JBHNTR_ENGINE="demo")
        assert dev == "BOOTED 200", dev
        print("[1] ...dev boots it explicitly (JBHNTR_ENGINE=demo): OK")

        split = json.loads(run(_PROBE, extra_path=target))
        assert split["kind"] == "real" and not split["problems"], split
        assert str(target) in (split["real_from"] or ""), split
        print(f"[2] public snapshot + private wheel -> engine={split['kind']} "
              f"(from the installed wheel)")
        booted = run(_BOOT, extra_path=target, DEBUG="false")
        assert booted == "BOOTED 200", booted
        print("[2] ...production boots on it: OK")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(ROOT / "dist"), help="wheel output dir")
    ap.add_argument("--verify", action="store_true",
                    help="prove public-alone=demo and public+wheel=real")
    args = ap.parse_args()
    wheel = build(Path(args.out))
    print(f"built {wheel}")
    if args.verify:
        verify(wheel)


if __name__ == "__main__":
    main()
