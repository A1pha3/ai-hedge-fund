"""Deletable trial assessment projection (Plan Task 13).

``TrialAssessmentProjection`` is a pure read-only projection of the frozen
paired evaluation: it holds only hashes/references to Trial/SAP/Stage,
SessionSpine, pair decisions, genesis, current/stress replay, capital
reports and consumption ledgers plus the calculated eligibility gates.
Rendering the same inputs is byte-identical; deleting the report loses no
truth because every referenced artifact is content-addressed elsewhere and
the report itself can be rebuilt from those references.

The headline is ``NOT_ELIGIBLE`` when any gate fails and at most
``INACTIVE_PROMOTION_CANDIDATE`` when all pass — a ``DAILY_BAR_PROXY``
evaluation can never promote to live capital. The projection therefore
cannot carry (at construction) or serialize (at render time) a broker
fill, an active authorization, a canary activation or a production
deployment recommendation; both layers fail closed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping

from src.screening.offensive.v3.contracts.base import CanonicalModel

#: The only serializable headline values of a proxy-mode assessment.
HEADLINE_NOT_ELIGIBLE: str = "NOT_ELIGIBLE"
HEADLINE_INACTIVE_CANDIDATE: str = "INACTIVE_PROMOTION_CANDIDATE"

#: Fields that would imply live-capital authority; never settable or
#: serializable for a ``DAILY_BAR_PROXY`` projection.
_PROXY_FORBIDDEN_FIELDS: frozenset[str] = frozenset(
    {
        "broker_fill",
        "active_authorization",
        "canary_activation",
        "production_recommendation",
    }
)


class AssessmentProjectionError(RuntimeError):
    """Fail-closed rejection of an assessment projection payload."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class EligibilityGates(CanonicalModel):
    """The calculated gate booleans; every gate is distinct, never merged."""

    mature_outcomes_sufficient: bool
    decision_days_sufficient: bool
    ess_sufficient: bool
    tickers_sufficient: bool
    months_sufficient: bool
    adverse_window_complete: bool
    itt_finality_complete: bool
    consumption_and_multiplicity_complete: bool
    current_conservation_passed: bool
    current_rebuild_passed: bool
    stress_conservation_passed: bool
    stress_rebuild_passed: bool
    current_absolute_growth_passed: bool
    stress_absolute_growth_passed: bool
    current_incremental_passed: bool
    stress_incremental_passed: bool
    tail_within_caps: bool
    liquidity_capacity_passed: bool
    zero_unresolved_breaches: bool

    def all_pass(self) -> bool:
        return all(
            (
                self.mature_outcomes_sufficient,
                self.decision_days_sufficient,
                self.ess_sufficient,
                self.tickers_sufficient,
                self.months_sufficient,
                self.adverse_window_complete,
                self.itt_finality_complete,
                self.consumption_and_multiplicity_complete,
                self.current_conservation_passed,
                self.current_rebuild_passed,
                self.stress_conservation_passed,
                self.stress_rebuild_passed,
                self.current_absolute_growth_passed,
                self.stress_absolute_growth_passed,
                self.current_incremental_passed,
                self.stress_incremental_passed,
                self.tail_within_caps,
                self.liquidity_capacity_passed,
                self.zero_unresolved_breaches,
            )
        )


@dataclass(frozen=True)
class TrialAssessmentProjection:
    """The disposable assessment view; references and gates only.

    Every hash field references an immutable content-addressed artifact
    stored elsewhere; no NAV series, decision payload or capital event
    bytes live here. ``mode`` is the sealed execution mode; for
    ``DAILY_BAR_PROXY`` the authority payload fields are forbidden at
    construction (``proxy_mode_authority_payload``) and never serialized.
    """

    trial_id: str
    research_program_id: str
    economic_lineage_id: str
    trial_manifest_hash: str
    sap_manifest_hash: str
    stage_manifest_hash: str
    session_spine_hash: str
    genesis_manifest_hash: str
    pair_decision_hashes: tuple[str, ...]
    current_replay_hash: str
    stress_replay_hash: str
    champion_capital_report_hash: str
    challenger_capital_report_hash: str
    consumption_ledger_hash: str
    mode: Literal["DAILY_BAR_PROXY"]
    eligibility: EligibilityGates
    assessed_at: datetime
    evidence_cutoff: datetime
    #: Live-capital authority payloads; settable ONLY to ``None`` in
    #: DAILY_BAR_PROXY mode (any other value fails closed at construction).
    broker_fill: Mapping[str, object] | None = None
    active_authorization: Mapping[str, object] | None = None
    canary_activation: Mapping[str, object] | None = None
    production_recommendation: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.mode != "DAILY_BAR_PROXY":
            raise AssessmentProjectionError(
                "unsupported_mode",
                "only DAILY_BAR_PROXY assessments are projection-safe",
            )
        if not isinstance(self.eligibility, EligibilityGates):
            # A plain mapping is normalized into the validated gate model
            # (every gate stays a distinct typed boolean).
            object.__setattr__(
                self, "eligibility", EligibilityGates(**self.eligibility)
            )
        # The sealed mode can never carry live-capital authority payloads.
        for field in _PROXY_FORBIDDEN_FIELDS:
            if getattr(self, field, None) is not None:
                raise AssessmentProjectionError(
                    "proxy_mode_authority_payload",
                    f"{field} is not representable in DAILY_BAR_PROXY",
                )

    def headline(self) -> str:
        if not self.eligibility.all_pass():
            return HEADLINE_NOT_ELIGIBLE
        # All gates green is still not a promotion: the proxy mode keeps
        # the outcome inactive until a separate live-capability process
        # re-validates on broker-confirmed evidence.
        return HEADLINE_INACTIVE_CANDIDATE


def rebuild_trial_assessment(
    *,
    trial_id: str,
    research_program_id: str,
    economic_lineage_id: str,
    trial_manifest_hash: str,
    sap_manifest_hash: str,
    stage_manifest_hash: str,
    session_spine_hash: str,
    genesis_manifest_hash: str,
    pair_decision_hashes: tuple[str, ...],
    current_replay_hash: str,
    stress_replay_hash: str,
    champion_capital_report_hash: str,
    challenger_capital_report_hash: str,
    consumption_ledger_hash: str,
    eligibility: EligibilityGates,
    mode: Literal["DAILY_BAR_PROXY"],
    assessed_at: datetime,
    evidence_cutoff: datetime,
) -> TrialAssessmentProjection:
    """Rebuild the projection from its referenced artifact hashes.

    Deleting the report loses no truth: the same referenced artifacts
    deterministically reproduce the same projection.
    """

    return TrialAssessmentProjection(
        trial_id=trial_id,
        research_program_id=research_program_id,
        economic_lineage_id=economic_lineage_id,
        trial_manifest_hash=trial_manifest_hash,
        sap_manifest_hash=sap_manifest_hash,
        stage_manifest_hash=stage_manifest_hash,
        session_spine_hash=session_spine_hash,
        genesis_manifest_hash=genesis_manifest_hash,
        pair_decision_hashes=pair_decision_hashes,
        current_replay_hash=current_replay_hash,
        stress_replay_hash=stress_replay_hash,
        champion_capital_report_hash=champion_capital_report_hash,
        challenger_capital_report_hash=challenger_capital_report_hash,
        consumption_ledger_hash=consumption_ledger_hash,
        mode=mode,
        eligibility=eligibility,
        assessed_at=assessed_at,
        evidence_cutoff=evidence_cutoff,
    )


def render_trial_assessment(projection: TrialAssessmentProjection) -> str:
    """Deterministic JSON rendering of the assessment projection.

    The rendered surface contains references and calculated gates only;
    the mode is disclosed so the reader can bound interpretation, and the
    serialized payload never contains an authority field of any kind.
    """

    if projection.mode != "DAILY_BAR_PROXY":
        raise AssessmentProjectionError(
            "unsupported_mode",
            "only DAILY_BAR_PROXY assessments are renderable",
        )
    payload = {
        "trial_id": projection.trial_id,
        "research_program_id": projection.research_program_id,
        "economic_lineage_id": projection.economic_lineage_id,
        "mode": projection.mode,
        "references": {
            "trial_manifest_hash": projection.trial_manifest_hash,
            "sap_manifest_hash": projection.sap_manifest_hash,
            "stage_manifest_hash": projection.stage_manifest_hash,
            "session_spine_hash": projection.session_spine_hash,
            "genesis_manifest_hash": projection.genesis_manifest_hash,
            "pair_decision_hashes": list(projection.pair_decision_hashes),
            "current_replay_hash": projection.current_replay_hash,
            "stress_replay_hash": projection.stress_replay_hash,
            "champion_capital_report_hash": projection.champion_capital_report_hash,
            "challenger_capital_report_hash": projection.challenger_capital_report_hash,
            "consumption_ledger_hash": projection.consumption_ledger_hash,
        },
        "gates": projection.eligibility.model_dump(),
        "headline": projection.headline(),
        "assessed_at": projection.assessed_at.isoformat(),
        "evidence_cutoff": projection.evidence_cutoff.isoformat(),
    }
    rendered = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    # Render-time guard: a proxy assessment never serializes authority.
    for forbidden in _PROXY_FORBIDDEN_FIELDS:
        if forbidden in rendered:
            raise AssessmentProjectionError(
                "proxy_mode_authority_payload",
                f"{forbidden} leaked into the proxy assessment render",
            )
    return rendered


__all__ = [
    "AssessmentProjectionError",
    "EligibilityGates",
    "HEADLINE_INACTIVE_CANDIDATE",
    "HEADLINE_NOT_ELIGIBLE",
    "TrialAssessmentProjection",
    "rebuild_trial_assessment",
    "render_trial_assessment",
]
