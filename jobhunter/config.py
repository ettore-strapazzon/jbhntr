"""Alias of the engine configuration contract (``jbhntr_engine.settings``).

Settings / Profile / Materials moved to the public contract package in the
open-core split (REPO_SPLIT_EXECUTION_PLAN step 1). This module *is* that
module — aliased in ``sys.modules`` — so engine code that does
``from .config import Settings`` keeps working and gets the identical classes.
"""

import sys

import jbhntr_engine.settings as _contract

sys.modules[__name__] = _contract
