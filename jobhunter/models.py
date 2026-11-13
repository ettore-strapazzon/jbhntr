"""Alias of the engine contract types (``jbhntr_engine.types``).

The wire types moved to the public contract package in the open-core split
(REPO_SPLIT_EXECUTION_PLAN step 1). This module *is* that module — aliased in
``sys.modules`` — so ``jobhunter.models.JobPosting is jbhntr_engine.JobPosting``
and every existing engine import keeps working unchanged.
"""

import sys

import jbhntr_engine.types as _contract

sys.modules[__name__] = _contract
