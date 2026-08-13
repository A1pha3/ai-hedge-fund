"""Authority-free shadow admission and the one shared shadow decision path.

The official paired trial never manufactures a grant: the shadow admission
maps the Trial-bound ``PolicySnapshot`` (Champion ``IGNORE`` / Challenger
``NORMAL_ONLY``) directly into ``DecisionConstraints``. Regime is the only
arm-specific admission gate: with ``NORMAL_ONLY`` a non-NORMAL canonical
regime observation blocks every BTST candidate; ``IGNORE`` continues with the
same downstream economics. The projection step is deterministic — no call
order, no store sequence, no wall clock — and always sets
``execution_authority="NONE"``.
"""

from __future__ import annotations

from datetime import timedelta

from src.screening.offensive.v3.contracts import ArtifactKind, ExecutionMode, Sha256
from src.screening.offensive.v3.contracts.base import content_hash
from src.screening.offensive.v3.contracts.decision import (
    CounterfactualDecisionKey,
    ShadowDecision,
    ShadowIssuerBinding,
    ShadowOrderLine,
    ShadowStageBinding,
    ShadowTradingScheduleBinding,
)
from src.screening.offensive.v3.contracts.regime import (
    RegimeAdmissionMode,
    RegimeState,
)
from src.screening.offensive.v3.kernel.core import (
    CoreError,
    DecisionConstraints,
    decide_core,
)
from src.screening.offensive.v3.kernel.models import (
    BlockReason,
    CoreNoTrade,
    CorePortfolioDecision,
    NoTradeDecision,
    ShadowKernelInput,
)
from src.screening.offensive.v3.kernel.sizing import LOT_UNITS, MICROS_PER_CENT

FAMILY_ID = "btst.limit-up-breakout"
LOT_RULE_VERSION = "cn-a-share-lot.v1"
PRICE_BOUNDARY_VERSION = "cn-price-limit.v1"
TIME_IN_FORCE = "OPEN_AUCTION"
ORDER_TYPE = "LIMIT"
EXIT_SESSION_ORDINAL = 10
SHADOW_ISSUER_ID = "growth-kernel.shadow.service"
SHADOW_ISSUER_KEY_ID = "shadow-key-1"
SHADOW_CAPABILITY_VERSION = "growth-kernel-shadow.v3"
SHADOW_NAMESPACE = "growth-kernel.shadow.v3"


def _admission_blocked(policy, shared) -> bool:
    """The one arm-specific shadow admission gate: regime only.

    Regime decides whether candidates enter the same downstream flow; it
    never changes strength, never multiplies size, never re-ranks. The
    capital checkpoint's freshness/completeness/latches are the shared risk
    evaluation's job, computed exactly once inside ``decide_core`` — the
    regime gate runs after the risk gate so both arms report a stale/halted
    truth identically.
    """

    if policy.producers.btst_regime_admission_mode is RegimeAdmissionMode.IGNORE:
        return False
    return shared.regime_observation.state is not RegimeState.NORMAL


def _constraints_by_lineage(
    policy, capital_checkpoint, config, candidates
) -> DecisionConstraints:
    """Map the Trial-bound PolicySnapshot into frozen integer constraints.

    The policy fractions are the only ceiling; the producer's self-reported
    target can only clamp DOWN, never lift a cap. The kernel's frozen sizing
    configuration stays authoritative for the per-ticker/industry/day caps.
    """

    nav = capital_checkpoint.capital_snapshot.as_observed_nav_cents
    lineage_cap = int(nav * policy.capital.portfolio_gross_cap)
    by_lineage: dict[str, int] = {}
    for candidate in candidates:
        by_lineage[candidate.economic_lineage_id] = lineage_cap
    return DecisionConstraints(
        lineage_gross_cap_cents=by_lineage,
        sizing_config=config,
        portfolio_gross_cap_cents=int(nav * policy.capital.portfolio_gross_cap),
        policy_epoch=policy.policy_epoch,
    )


def decide_shadow(
    kernel_input: ShadowKernelInput,
) -> ShadowDecision | NoTradeDecision:
    """One arm decision: shared core economics, arm-specific regime gate.

    Deterministic: the same canonical input produces the same canonical
    output bytes/hash across processes and candidate orderings. The frozen
    trusted time lives inside ``ShadowSharedInput``, so both arm calls
    consume exactly one observation.

    Ordering matches the executable path: the shared core's risk gate runs
    BEFORE the arm admission gate, so a stale or halted capital truth is
    reported identically by both arms and the regime gate is the only
    arm-differentiating observation.
    """

    shared = kernel_input.shared
    policy = kernel_input.policy_snapshot
    checkpoint = kernel_input.capital_checkpoint
    candidates = kernel_input.raw_candidates

    constraints = _constraints_by_lineage(
        policy, checkpoint, kernel_input.sizing_config, candidates
    )
    result = decide_core(
        candidates=candidates,
        constraints=constraints,
        capital=checkpoint.capital_snapshot,
        prices=dict(kernel_input.price_micros_by_candidate),
        industries=dict(kernel_input.industry_by_candidate),
        deadlines=kernel_input.deadlines,
        trusted_at=shared.trusted_at,
    )
    if isinstance(result, CoreNoTrade):
        return _no_trade(kernel_input, result.reason)
    if _admission_blocked(policy, shared):
        return _no_trade(kernel_input, BlockReason.REGIME_ADMISSION_BLOCKED)
    return _project_shadow_decision(kernel_input, result)


def _no_trade(kernel_input: ShadowKernelInput, reason: BlockReason) -> NoTradeDecision:
    return NoTradeDecision(
        portfolio_id=kernel_input.portfolio_id,
        signal_session=kernel_input.shared.signal_session,
        decision_cycle_id=kernel_input.shared.decision_cycle_id,
        reason=reason,
        kernel_input_hash=kernel_input.content_hash(),
    )


def _project_shadow_decision(
    kernel_input: ShadowKernelInput,
    result: CorePortfolioDecision,
) -> ShadowDecision:
    """Project the shared core result into a canonical ShadowDecision.

    IDs are derived from Trial/session/cycle/candidate identities — never
    from call order or store sequences — and every line carries the frozen
    candidate evidence binding, so two replays of one input produce the same
    bytes. ``execution_authority`` is always ``"NONE"``.
    """

    shared = kernel_input.shared
    policy = kernel_input.policy_snapshot
    binding = kernel_input.shadow_policy_binding
    evidence_by_candidate = {
        eb.candidate_id: eb for eb in kernel_input.candidate_evidence_bindings
    }
    trusted_at = shared.trusted_at
    signal_session = shared.signal_session
    cycle_id = shared.decision_cycle_id
    schedule = shared.trading_session_schedule
    target_entry_session = schedule.following_sessions[0]
    target_exit_session = schedule.following_sessions[EXIT_SESSION_ORDINAL - 1]

    stage_binding = ShadowStageBinding(
        research_program_id=shared.research_program_id,
        economic_lineage_id=shared.economic_lineage_id,
        stage_id=shared.stage_id,
        trial_id=shared.trial_id,
        stage_manifest_hash=shared.stage_manifest_hash,
    )
    lines = tuple(
        _project_line(
            decision_line=line,
            binding=evidence_by_candidate.get(line.candidate_id),
            family_id=FAMILY_ID,
            stage_binding=stage_binding,
            target_exit_session=target_exit_session,
            cost_version=policy.versions.cost_version,
            execution_version=policy.versions.execution_contract_version,
        )
        for line in result.lines
        if line.status == "ENTRY_PLANNED"
    )
    # canonical order: shadow lines must be sorted by shadow_line_id.
    lines = tuple(sorted(lines, key=lambda line: line.shadow_line_id))
    issuer_binding = ShadowIssuerBinding(
        issuer_id=SHADOW_ISSUER_ID,
        key_id=SHADOW_ISSUER_KEY_ID,
        capability_artifact_kind=ArtifactKind.SHADOW_DECISION,
        capability_namespace=SHADOW_NAMESPACE,
        capability_mode=shared.mode,
        capability_schema_major=4,
        capability_version=SHADOW_CAPABILITY_VERSION,
        capability_scope=f"portfolio:{kernel_input.portfolio_id}",
        verification_result="VALID",
        verified_at=trusted_at,
        valid_until=trusted_at + timedelta(days=1),
        trust_bundle_hash=shared.trust_bundle_hash,
        registry_epoch=shared.registry_epoch,
    )
    return ShadowDecision(
        artifact_kind=ArtifactKind.SHADOW_DECISION,
        artifact_namespace=SHADOW_NAMESPACE,
        schema_major=4,
        shadow_decision_id=f"shadow-{cycle_id}-{kernel_input.arm.value.lower()}",
        counterfactual_key=CounterfactualDecisionKey(
            portfolio_id=kernel_input.portfolio_id,
            signal_session=signal_session,
            counterfactual_cycle_id=cycle_id,
        ),
        portfolio_id=kernel_input.portfolio_id,
        mode=shared.mode,
        target_entry_session=target_entry_session,
        producer_namespace="btst",
        family_id=FAMILY_ID,
        research_program_id=stage_binding.research_program_id,
        economic_lineage_id=stage_binding.economic_lineage_id,
        stage_id=stage_binding.stage_id,
        trial_id=stage_binding.trial_id,
        kernel_input_hash=kernel_input.content_hash(),
        shadow_policy_binding=binding,
        trading_session_schedule_binding=ShadowTradingScheduleBinding(
            calendar_id=schedule.calendar_id,
            calendar_version=schedule.calendar_version,
            calendar_artifact_hash=schedule.calendar_artifact_hash,
            signal_session=schedule.signal_session,
            following_sessions=schedule.following_sessions,
            available_at=schedule.available_at,
            schedule_hash=schedule.content_hash(),
        ),
        policy_epoch=policy.policy_epoch,
        evidence_set_merkle_root=shared.evidence_set_merkle_root,
        shadow_stage_binding=stage_binding,
        counterfactual_lines=lines,
        cost_assumption_version=policy.versions.cost_version,
        execution_assumption_version=policy.versions.execution_contract_version,
        created_at=trusted_at,
        available_at=trusted_at,
        execution_authority="NONE",
        issuer_binding=issuer_binding,
    )


def _project_line(
    *,
    decision_line,
    binding,
    family_id: str,
    stage_binding: ShadowStageBinding,
    target_exit_session,
    cost_version: str,
    execution_version: str,
) -> ShadowOrderLine:
    """One counterfactual line derived from the shared core sizing output.

    Price converts micro-yuan to cents (MICROS_PER_CENT = 10_000); the
    worst-case fee and cash reserve are copied verbatim from the core sizing
    output (already fee-inclusive and cent-consistent), so the line satisfies
    the ``ShadowOrderLine`` self-consistency validator without recomputation.
    The evidence identity is frozen by the caller's binding, never
    synthesized: a candidate that reaches line projection without a binding is
    a kernel-input inconsistency and fails closed.
    """

    if binding is None:
        raise CoreError(
            "missing_evidence_binding",
            f"candidate {decision_line.candidate_id} reached shadow line "
            "projection without a frozen evidence binding; a shadow line's "
            "evidence identity comes from the kernel input and is never "
            "synthesized",
        )
    quantity = decision_line.quantity_units
    limit_price_cents = decision_line.limit_price_micros // MICROS_PER_CENT
    worst_case_price_cents = limit_price_cents
    fee_cents = decision_line.worst_case_fee_reserve_cents
    estimated_reserve_cents = decision_line.worst_case_reserve_cents
    return ShadowOrderLine(
        shadow_line_id=f"shadow-line-{decision_line.candidate_id}",
        security_id=decision_line.security_id,
        producer_namespace="btst",
        family_id=family_id,
        economic_lineage_id=stage_binding.economic_lineage_id,
        research_program_id=stage_binding.research_program_id,
        stage_id=stage_binding.stage_id,
        trial_id=stage_binding.trial_id,
        stage_manifest_hash=stage_binding.stage_manifest_hash,
        evidence_id=binding.evidence_id,
        evidence_artifact_hash=binding.evidence_artifact_hash,
        evidence_payload_hash=binding.evidence_payload_hash,
        target_quantity_units=quantity,
        lot_size_units=LOT_UNITS,
        lot_rule_version=LOT_RULE_VERSION,
        order_type=ORDER_TYPE,
        limit_price_cents=limit_price_cents,
        worst_case_price_cents=worst_case_price_cents,
        price_boundary_version=PRICE_BOUNDARY_VERSION,
        time_in_force=TIME_IN_FORCE,
        exit_session_ordinal=EXIT_SESSION_ORDINAL,
        estimated_fee_cents=fee_cents,
        estimated_cash_reserve_cents=estimated_reserve_cents,
        cost_assumption_version=cost_version,
        execution_assumption_version=execution_version,
        target_exit_session=target_exit_session,
    )


def economic_shadow_projection(
    decision: ShadowDecision | NoTradeDecision,
) -> bytes:
    """The economic content both arm projections share, for equality checks.

    NORMAL-world equality between the arms is byte-identical here; the
    projection excludes identity/authority provenance so a regime block never
    changes the champion's economics.
    """

    if isinstance(decision, NoTradeDecision):
        return decision.canonical_bytes()
    payload = {
        "signal_session": decision.counterfactual_key.signal_session.isoformat(),
        "portfolio_id": decision.counterfactual_key.portfolio_id,
        "policy_epoch": decision.policy_epoch,
        "lines": [
            {
                "security_id": line.security_id,
                "target_quantity_units": line.target_quantity_units,
                "limit_price_cents": line.limit_price_cents,
                "estimated_cash_reserve_cents": line.estimated_cash_reserve_cents,
                "target_exit_session": line.target_exit_session.isoformat(),
            }
            for line in decision.counterfactual_lines
        ],
        "portfolio_gross_cap_cents": sum(
            line.estimated_cash_reserve_cents
            for line in decision.counterfactual_lines
        ),
        "total_reserved_worst_case_cents": sum(
            line.estimated_cash_reserve_cents
            for line in decision.counterfactual_lines
        ),
    }
    return content_hash(payload).encode("utf-8")


__all__ = [
    "FAMILY_ID",
    "decide_shadow",
    "economic_shadow_projection",
]
