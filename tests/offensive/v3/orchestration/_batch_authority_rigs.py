"""Shared surface for the R44 dormant-guard audit (autodev 第四十四轮).

The former ``@_REQUIRES_BATCH_AUTHORITY`` cohort was audited across
``test_forward_paired_runner`` (12 superseded mechanisms removed) and the
replay/evaluation pair (rewritten to the checkpoint-v2 API). The two files
that remain skip-gated share their TRUE gate here so the reason string and
the audit note live once, not copied per file:

the decision half runs through ``commit_pair`` on the checkpoint-v2
builders, and the execution half stops at ``_reject_shadow_capital_mutation``
until the capital-local writer fencing epoch lands.
"""

from __future__ import annotations

FENCE_REASON = "future contract: requires capital-local shadow writer fencing"

NOTE = """\
R44 (autodev): the former @_REQUIRES_BATCH_AUTHORITY precondition was
RESOLVED - the official drive runs on the capital-checkpoint-v2 builders
and reaches the pair commit. The remaining blocker is the deliberate
shadow-capital write fence (_reject_shadow_capital_mutation): execution-
half assertions stay skipped under their TRUE gate until the capital-local
writer fencing epoch lands."""


__all__ = ["FENCE_REASON", "NOTE"]
