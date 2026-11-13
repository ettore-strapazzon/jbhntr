"""Boot guard: production never runs on the demo engine (repo-split plan §5.3).

The real engine is resolved by ``jbhntr_engine`` (``JBHNTR_ENGINE``, default
``auto`` → real when importable). If the active engine is anything but the real
one — an explicit ``demo`` or a silent auto-fallback because the private engine
failed to import — a production process (``DEBUG`` off) refuses to start, the
same way ``config.validate()`` refuses weak secrets. Dev and tests (``DEBUG``
on) only log it, so ``JBHNTR_ENGINE=demo`` stays usable there.
"""

from __future__ import annotations

import logging

log = logging.getLogger("jbhntr.engine_guard")


def enforce_engine(debug: bool) -> list[str]:
    """Raise RuntimeError in production if the real engine isn't active.
    Returns the problems (empty when the real engine is active)."""
    from jbhntr_engine import engine_problems

    problems = engine_problems()
    for p in problems:
        log.warning("ENGINE: %s", p)
    if problems and not debug:
        raise RuntimeError("Refusing to start in production: " + "; ".join(problems))
    return problems
