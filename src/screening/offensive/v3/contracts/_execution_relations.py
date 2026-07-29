"""Pure identity and version relations for execution-domain contracts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Hashable


def ensure_equal_bindings(
    bindings: Mapping[str, tuple[object, object]], *, prefix: str
) -> None:
    for label, (actual, expected) in bindings.items():
        if actual != expected:
            raise ValueError(f"{prefix} {label} binding mismatch")


def stage_identity(item: object) -> tuple[str, str, str, str]:
    return (
        getattr(item, "research_program_id"),
        getattr(item, "economic_lineage_id"),
        getattr(item, "stage_id"),
        getattr(item, "stage_loss_budget_id"),
    )


def ensure_unique_canonical_stages(
    stages: Iterable[object], *, label: str
) -> tuple[tuple[str, str, str, str], ...]:
    identities = tuple(stage_identity(item) for item in stages)
    if len(identities) != len(set(identities)):
        raise ValueError(f"{label} stage identities must be unique")
    if identities != tuple(sorted(identities)):
        raise ValueError(f"{label} stage identities must use canonical order")
    stage_ids = tuple(identity[:3] for identity in identities)
    if len(stage_ids) != len(set(stage_ids)):
        raise ValueError(f"{label} stage identities must be unique")
    budget_ids = tuple(identity[3] for identity in identities)
    if len(budget_ids) != len(set(budget_ids)):
        raise ValueError(f"{label} budget identities must be unique")
    return identities


def ensure_same_identity_sequence(
    current: Iterable[object], post: Iterable[object], *, label: str
) -> None:
    current_identities = tuple(stage_identity(item) for item in current)
    post_identities = tuple(stage_identity(item) for item in post)
    if current_identities != post_identities:
        raise ValueError(f"{label} stage identity coverage mismatch")


def ensure_strict_advance(current: int, post: int, *, label: str) -> None:
    if post <= current:
        raise ValueError(f"{label} version must strictly advance")


def ensure_not_regressed(current: int, post: int, *, label: str) -> None:
    if post < current:
        raise ValueError(f"{label} version cannot regress")


def witnessed_cancel_reasons(
    *,
    authorization_failed: bool,
    stage_halted: bool,
    reconciliation_halted: bool,
    fact_integrity_failed: bool,
    fence_changed: bool,
    deadline_reached: bool,
    authorization_reason: Hashable,
    stage_reason: Hashable,
    reconciliation_reason: Hashable,
    fact_reason: Hashable,
    fence_reason: Hashable,
    deadline_reason: Hashable,
) -> frozenset[Hashable]:
    witnessed: set[Hashable] = set()
    for condition, reason in (
        (authorization_failed, authorization_reason),
        (stage_halted, stage_reason),
        (reconciliation_halted, reconciliation_reason),
        (fact_integrity_failed, fact_reason),
        (fence_changed, fence_reason),
        (deadline_reached, deadline_reason),
    ):
        if condition:
            witnessed.add(reason)
    return frozenset(witnessed)
