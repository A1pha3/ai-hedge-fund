"""Plan Task 13 RED: deletable trial assessment projection.

``TrialAssessmentProjection`` is a pure read-only projection of the frozen
paired evaluation: it holds only hashes/references to Trial/SAP/Stage,
SessionSpine, pair decisions, genesis, current/stress replay, capital
reports and consumption ledgers plus the calculated eligibility gates.
Rendering the same inputs is byte-identical; deleting the report loses no
truth because every referenced artifact is content-addressed elsewhere.
The headline is ``NOT_ELIGIBLE`` when any gate fails and at most
``INACTIVE_PROMOTION_CANDIDATE`` when all pass. A ``DAILY_BAR_PROXY``
projection can never serialize a broker fill, active authorization, canary
activation or production deployment recommendation — construction and
rendering both fail closed.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
HASH = "a" * 64


def _gates(**overrides) -> object:
    """All-passing gates; any single gate can be flipped to NOT_ELIGIBLE."""

    values = {
        "mature_outcomes_sufficient": True,
        "decision_days_sufficient": True,
        "ess_sufficient": True,
        "tickers_sufficient": True,
        "months_sufficient": True,
        "adverse_window_complete": True,
        "itt_finality_complete": True,
        "consumption_and_multiplicity_complete": True,
        "current_conservation_passed": True,
        "current_rebuild_passed": True,
        "stress_conservation_passed": True,
        "stress_rebuild_passed": True,
        "current_absolute_growth_passed": True,
        "stress_absolute_growth_passed": True,
        "current_incremental_passed": True,
        "stress_incremental_passed": True,
        "tail_within_caps": True,
        "liquidity_capacity_passed": True,
        "zero_unresolved_breaches": True,
    }
    values.update(overrides)
    return values


def _projection(**overrides) -> object:
    from src.screening.offensive.v3.reporting.trial_projection import (
        TrialAssessmentProjection,
    )

    values = {
        "trial_id": "trial-regime-001",
        "research_program_id": "research.btst.regime",
        "economic_lineage_id": "lineage-1",
        "trial_manifest_hash": HASH,
        "sap_manifest_hash": HASH,
        "stage_manifest_hash": HASH,
        "session_spine_hash": HASH,
        "genesis_manifest_hash": HASH,
        "pair_decision_hashes": (HASH, HASH),
        "current_replay_hash": HASH,
        "stress_replay_hash": HASH,
        "champion_capital_report_hash": HASH,
        "challenger_capital_report_hash": HASH,
        "consumption_ledger_hash": HASH,
        "mode": "DAILY_BAR_PROXY",
        "eligibility": _gates(),
        "assessed_at": NOW,
        "evidence_cutoff": NOW,
    }
    values.update(overrides)
    return TrialAssessmentProjection(**values)


def test_projection_holds_only_references_and_calculated_gates() -> None:
    projection = _projection()
    # Every field is a hash/reference or a calculated gate; the projection
    # carries no NAV series, no decision payloads, no capital event bytes.
    assert projection.trial_manifest_hash == HASH
    assert projection.genesis_manifest_hash == HASH
    assert len(projection.pair_decision_hashes) == 2
    assert projection.eligibility.zero_unresolved_breaches is True


def test_headline_is_not_eligible_when_any_gate_fails() -> None:
    projection = _projection(
        eligibility=_gates(mature_outcomes_sufficient=False)
    )
    assert projection.eligibility.all_pass() is False
    assert projection.headline() == "NOT_ELIGIBLE"


def test_headline_at_most_inactive_promotion_candidate_when_all_pass() -> None:
    projection = _projection()
    assert projection.eligibility.all_pass() is True
    # Even with every gate green the mode keeps the promotion inactive:
    # DAILY_BAR_PROXY evidence can never promote to live capital.
    assert projection.headline() == "INACTIVE_PROMOTION_CANDIDATE"


def test_rendering_is_byte_identical_for_identical_inputs() -> None:
    from src.screening.offensive.v3.reporting.trial_projection import (
        render_trial_assessment,
    )

    projection = _projection()
    first = render_trial_assessment(projection)
    second = render_trial_assessment(projection)
    assert first == second


def test_deleting_the_report_loses_no_truth() -> None:
    from src.screening.offensive.v3.reporting.trial_projection import (
        render_trial_assessment,
        rebuild_trial_assessment,
    )

    # Rebuilding from the same referenced artifacts reproduces the exact
    # same projection and the exact same rendered bytes; the report itself
    # is a disposable view.
    original = _projection()
    rebuilt = rebuild_trial_assessment(
        trial_id=original.trial_id,
        research_program_id=original.research_program_id,
        economic_lineage_id=original.economic_lineage_id,
        trial_manifest_hash=original.trial_manifest_hash,
        sap_manifest_hash=original.sap_manifest_hash,
        stage_manifest_hash=original.stage_manifest_hash,
        session_spine_hash=original.session_spine_hash,
        genesis_manifest_hash=original.genesis_manifest_hash,
        pair_decision_hashes=original.pair_decision_hashes,
        current_replay_hash=original.current_replay_hash,
        stress_replay_hash=original.stress_replay_hash,
        champion_capital_report_hash=original.champion_capital_report_hash,
        challenger_capital_report_hash=original.challenger_capital_report_hash,
        consumption_ledger_hash=original.consumption_ledger_hash,
        eligibility=original.eligibility,
        mode=original.mode,
        assessed_at=original.assessed_at,
        evidence_cutoff=original.evidence_cutoff,
    )
    assert render_trial_assessment(rebuilt) == render_trial_assessment(original)


def test_proxy_projection_rejects_authority_payloads_at_construction() -> None:
    from src.screening.offensive.v3.reporting.trial_projection import (
        AssessmentProjectionError,
    )

    for field, payload in (
        ("broker_fill", {"execution_id": "ord-1"}),
        ("active_authorization", {"envelope_id": "auth-1"}),
        ("canary_activation", {"activation_id": "canary-1"}),
        ("production_recommendation", {"tier": "10%"}),
    ):
        with pytest.raises(
            AssessmentProjectionError, match="proxy_mode_authority_payload"
        ):
            _projection(**{field: payload})


def test_proxy_render_never_serializes_authority_fields() -> None:
    import json

    from src.screening.offensive.v3.reporting.trial_projection import (
        render_trial_assessment,
    )

    rendered = render_trial_assessment(_projection())
    parsed = json.loads(rendered)
    # The serialized surface must not contain any key or value suggesting
    # a broker fill, authorization, canary or deployment recommendation.
    flat = json.dumps(parsed)
    for forbidden in (
        "broker_fill",
        "active_authorization",
        "canary_activation",
        "production_recommendation",
        "execution_authority",
        "BROKER_CONFIRMED",
    ):
        assert forbidden not in flat
    # The mode is disclosed so the reader can bound interpretation.
    assert parsed["mode"] == "DAILY_BAR_PROXY"
    assert parsed["headline"] == "INACTIVE_PROMOTION_CANDIDATE"
