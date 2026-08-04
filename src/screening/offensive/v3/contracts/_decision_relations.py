"""Pure relation checks shared by public decision-domain models."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Hashable


def ensure_equal_bindings(
    bindings: Mapping[str, tuple[object, object]], *, prefix: str
) -> None:
    """Require every duplicated identity/version to be exactly equal."""

    for label, (actual, expected) in bindings.items():
        if actual != expected:
            raise ValueError(f"{prefix} {label} binding mismatch")


def ensure_unique_canonical(
    identities: Iterable[Hashable], *, label: str
) -> tuple[Hashable, ...]:
    """Freeze one deterministic sequence while rejecting duplicates."""

    frozen = tuple(identities)
    if len(frozen) != len(set(frozen)):
        raise ValueError(f"{label} identities must be unique")
    if frozen != tuple(sorted(frozen)):
        raise ValueError(f"{label} identities must use canonical order")
    return frozen


def ensure_unique_stage_budget_mapping(items: Iterable[object], *, label: str) -> None:
    """Require a one-to-one mapping between stage identity and loss budget."""

    identities = [
        (
            getattr(item, "research_program_id"),
            getattr(item, "economic_lineage_id"),
            getattr(item, "stage_id"),
            getattr(item, "stage_loss_budget_id"),
        )
        for item in items
    ]
    ensure_unique_canonical(identities, label=label)
    stage_identities = [identity[:3] for identity in identities]
    if len(stage_identities) != len(set(stage_identities)):
        raise ValueError(f"{label} stage identities must be unique")
    budget_ids = [identity[3] for identity in identities]
    if len(budget_ids) != len(set(budget_ids)):
        raise ValueError(f"{label} budget identities must be unique")


def ensure_seal_time_chain(
    *,
    close_finalized_at: datetime,
    decision_cutoff: datetime,
    proposal_created_at: datetime,
    seal_created_at: datetime,
    seal_creation_deadline: datetime,
) -> None:
    """Reject historical reconstruction of an executable seal."""

    if not (
        close_finalized_at
        <= decision_cutoff
        < proposal_created_at
        <= seal_created_at
        <= seal_creation_deadline
    ):
        raise ValueError(
            "seal time chain requires close <= decision cutoff < proposal created "
            "<= seal created <= seal deadline"
        )
