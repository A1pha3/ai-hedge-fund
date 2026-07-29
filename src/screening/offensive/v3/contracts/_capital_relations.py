"""Pure aggregation and identity relations for capital-domain contracts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Hashable


EXPOSURE_COMPONENT_FIELDS = (
    "position_marked_gross_cents",
    "live_order_leaves_gross_cents",
    "reserved_entry_gross_cents",
    "pending_stress_cents",
    "corporate_action_pending_risk_cents",
)


def drawdown_ppm(nav_cents: int, high_water_mark_cents: int) -> int:
    if high_water_mark_cents == 0:
        return 0
    return ((high_water_mark_cents - nav_cents) * 1_000_000) // high_water_mark_cents


def ensure_unique_canonical(
    identities: Iterable[Hashable], *, label: str
) -> tuple[Hashable, ...]:
    frozen = tuple(identities)
    if len(frozen) != len(set(frozen)):
        raise ValueError(f"duplicate {label} identity")
    if frozen != tuple(sorted(frozen)):
        raise ValueError(f"{label} identities must be in canonical order")
    return frozen


def canonical_exposure_identities(
    components: Iterable[object],
    *,
    portfolio_id: str,
    global_scope: object,
    portfolio_scope: object,
    research_program_scope: object,
    economic_lineage_scope: object,
    stage_scope: object,
) -> tuple[tuple[object, str, str, str, str], ...]:
    """Derive a stable preorder from the canonical component collections."""

    program_lineages: dict[str, dict[str, list[str]]] = {}
    for component in components:
        program_id = getattr(component, "research_program_id")
        lineage_id = getattr(component, "economic_lineage_id")
        stage_id = getattr(component, "stage_id")
        lineages = program_lineages.setdefault(program_id, {})
        stages = lineages.setdefault(lineage_id, [])
        if stage_id not in stages:
            stages.append(stage_id)

    identities: list[tuple[object, str, str, str, str]] = [
        (global_scope, "", "", "", ""),
        (portfolio_scope, portfolio_id, "", "", ""),
    ]
    for program_id, lineages in program_lineages.items():
        identities.append((research_program_scope, portfolio_id, program_id, "", ""))
        for lineage_id, stages in lineages.items():
            identities.append(
                (
                    economic_lineage_scope,
                    portfolio_id,
                    program_id,
                    lineage_id,
                    "",
                )
            )
            identities.extend(
                (
                    stage_scope,
                    portfolio_id,
                    program_id,
                    lineage_id,
                    stage_id,
                )
                for stage_id in stages
            )
    return tuple(identities)


def component_matches_exposure(
    component: object,
    exposure: object,
    *,
    research_program_scope: object,
    economic_lineage_scope: object,
) -> bool:
    if getattr(component, "research_program_id") != getattr(
        exposure, "research_program_id"
    ):
        return False
    if getattr(exposure, "scope") is research_program_scope:
        return True
    if getattr(component, "economic_lineage_id") != getattr(
        exposure, "economic_lineage_id"
    ):
        return False
    if getattr(exposure, "scope") is economic_lineage_scope:
        return True
    return getattr(component, "stage_id") == getattr(exposure, "stage_id")


def validate_exposure_children(
    by_identity: Mapping[tuple[object, str, str, str, str], object],
    *,
    research_program_scope: object,
    economic_lineage_scope: object,
    stage_scope: object,
    global_scope: object,
    portfolio_scope: object,
) -> None:
    for identity, parent in by_identity.items():
        scope, portfolio_id, program_id, lineage_id, _ = identity
        if scope is research_program_scope:
            children = [
                bucket
                for child_id, bucket in by_identity.items()
                if child_id[0] is economic_lineage_scope
                and child_id[1] == portfolio_id
                and child_id[2] == program_id
            ]
        elif scope is economic_lineage_scope:
            children = [
                bucket
                for child_id, bucket in by_identity.items()
                if child_id[0] is stage_scope
                and child_id[1] == portfolio_id
                and child_id[2] == program_id
                and child_id[3] == lineage_id
            ]
        else:
            continue
        for field_name in EXPOSURE_COMPONENT_FIELDS:
            if getattr(parent, field_name) != sum(
                getattr(child, field_name) for child in children
            ):
                raise ValueError("exposure child aggregate is inconsistent")
        if getattr(parent, "total_gross_cents") != (
            sum(getattr(child, "total_gross_cents") for child in children)
            + getattr(parent, "unattributed_risk_cents")
        ):
            raise ValueError("exposure hierarchy double-counts or omits risk")
    if any(
        getattr(bucket, "unattributed_risk_cents") != 0
        for bucket in by_identity.values()
        if getattr(bucket, "scope") not in {global_scope, portfolio_scope}
    ):
        raise ValueError("program, lineage, and stage risk cannot be unattributed")
