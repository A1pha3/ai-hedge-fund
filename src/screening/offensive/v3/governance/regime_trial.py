"""Typed sealing and validation of the exact paired regime trial bundle.

A paired regime trial admits exactly one behavioural delta between its two
arms: ``ProducerPolicy.btst_regime_admission_mode`` (Champion ``IGNORE``,
Challenger ``NORMAL_ONLY``). This module freezes that contract as pure
governance logic: a deterministic target-policy registration hash, a
provenance-stripped semantic delta, and a validator that rejects any second
delta, wrong admission mode, wrong family, wrong runtime mode, mismatched
versions, or loose hash binding before enrolment.

Signature and capability verification of the signed envelopes happen at seal
time through ``GovernanceArtifactVerifierPort``; the immutable store is the
sealed truth, so ``validate_regime_trial_bundle`` checks semantic and hash
invariants without re-verifying signatures.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import ConfigDict

from src.screening.offensive.v3.contracts.base import (
    CanonicalModel,
    domain_hash,
    ExecutionMode,
    Sha256,
    UtcInstant,
)
from src.screening.offensive.v3.contracts.governance import (
    PolicyActivation,
    StatisticalAnalysisPlan,
    TrialManifest,
)
from src.screening.offensive.v3.contracts.regime import RegimeAdmissionMode
from src.screening.offensive.v3.contracts.trust import (
    Capability,
    CurrentTrustHeadWitness,
    SignedEnvelope,
    VerifiedIssuer,
)
from src.screening.offensive.v3.policy.models import PolicySnapshot, RuntimeMode

TARGET_POLICY_REGISTRATION_DOMAIN = "ai-hedge-fund.v3.governance.target-policy-registration.v1"

#: Provenance-only policy labels excluded from the semantic delta. Republishing
#: a policy under a new id/version/epoch must not read as a behaviour change.
_PROVENANCE_KEYS = (
    "policy_id",
    "policy_version",
    "policy_epoch",
    "authority_epoch",
    "risk_epoch",
)

#: The one semantic path a paired regime trial is allowed to differ on.
_ADMITTED_DELTA_PATH = "producers.btst_regime_admission_mode"


class RegimeTrialGovernanceError(ValueError):
    """A paired regime trial bundle failed a governance invariant."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def target_policy_registration_hash(policy: PolicySnapshot) -> str:
    """Deterministic, non-executable registration hash for one target policy."""

    return domain_hash(
        TARGET_POLICY_REGISTRATION_DOMAIN,
        policy.schema_major,
        {
            "policy_snapshot_hash": policy.content_hash(),
            "policy_fingerprint": policy.policy_fingerprint,
            "executable": False,
        },
    )


def _semantic_projection(policy: PolicySnapshot) -> dict:
    data = json.loads(policy.canonical_bytes())
    for key in _PROVENANCE_KEYS:
        data.pop(key, None)
    return data


def _diff_paths(left: object, right: object, prefix: str) -> list[str]:
    paths: list[str] = []
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                paths.append(f"{prefix}{key}")
            else:
                paths.extend(_diff_paths(left[key], right[key], f"{prefix}{key}."))
    elif left != right:
        paths.append(prefix.rstrip("."))
    return paths


def policy_semantic_delta_paths(baseline: PolicySnapshot, target: PolicySnapshot) -> tuple[str, ...]:
    """Return the sorted semantic field paths that differ between two policies.

    Provenance-only labels (id/version/epoch) are stripped first, so a
    republished policy is not a behaviour change.
    """

    return tuple(sorted(_diff_paths(_semantic_projection(baseline), _semantic_projection(target), "")))


class RegimeTrialBundle(CanonicalModel):
    """The sealed, immutable governance truth for one paired regime trial."""

    baseline_policy: PolicySnapshot
    target_policy: PolicySnapshot
    trial_manifest: TrialManifest
    sap_manifest: StatisticalAnalysisPlan
    baseline_policy_activation: PolicyActivation


#: Alias matching the plan's reader return type.
SealedRegimeTrialBundle = RegimeTrialBundle


class ValidatedRegimeTrialBundle(CanonicalModel):
    """The pure validation result; carries no authority beyond the bundle."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    champion_policy: PolicySnapshot
    challenger_policy: PolicySnapshot
    baseline_policy: PolicySnapshot
    target_policy: PolicySnapshot
    trial_manifest: TrialManifest
    sap_manifest: StatisticalAnalysisPlan
    admission_delta: tuple[str, ...]


@runtime_checkable
class GovernanceArtifactVerifierPort(Protocol):
    """Abstract signed-envelope + capability verifier used at seal time."""

    def verify(
        self,
        signed: SignedEnvelope,
        required: Capability,
        *,
        current_head: CurrentTrustHeadWitness,
        trusted_at: datetime,
    ) -> VerifiedIssuer: ...


def _require(condition: bool, code: str, detail: str) -> None:
    if not condition:
        raise RegimeTrialGovernanceError(code, detail)


def _require_producer_family(policy: PolicySnapshot, *, label: str) -> None:
    producers = policy.producers
    _require(
        producers.btst_enabled,
        "btst_family_required",
        f"{label} policy must keep BTST enabled for a BTST regime trial",
    )
    _require(
        not producers.oversold_bounce_enabled,
        "oversold_bounce_forbidden",
        f"{label} policy must disable OversoldBounce in a BTST regime trial",
    )
    for switch in (
        producers.regime_sizing_enabled,
        producers.streak_sizing_enabled,
        producers.trigger_strength_sizing_enabled,
        producers.composite_sizing_enabled,
    ):
        _require(
            not switch,
            "sizing_switches_forbidden",
            f"{label} policy must keep all sizing switches disabled",
        )


def validate_regime_trial_bundle(bundle: RegimeTrialBundle, *, trusted_at: datetime) -> ValidatedRegimeTrialBundle:
    """Validate the sealed bundle's semantic and hash invariants.

    Signatures were verified at seal time; the immutable bundle is the truth, so
    this checks policy semantics, family constraints, mode/version agreement,
    exact-one-delta admission, and the manifest↔policy hash bindings.
    """

    trial = bundle.trial_manifest
    sap = bundle.sap_manifest
    baseline = bundle.baseline_policy
    target = bundle.target_policy

    _require(
        trial.enrollment_start <= trusted_at < trial.enrollment_end,
        "enrollment_window_violation",
        "trusted_at must fall within [enrollment_start, enrollment_end)",
    )
    _require(
        sap.trial_manifest_hash == trial.artifact_hash(),
        "sap_trial_binding_mismatch",
        "SAP must bind the trial manifest hash",
    )
    _require(
        sap.research_program_id == trial.research_program_id and sap.economic_lineage_id == trial.economic_lineage_id,
        "sap_lineage_mismatch",
        "SAP program/lineage must match the trial manifest",
    )
    _require(
        bundle.baseline_policy_activation.policy_snapshot_hash == baseline.policy_fingerprint,
        "baseline_activation_binding_mismatch",
        "baseline activation must bind the baseline policy fingerprint",
    )
    _require(
        trial.baseline_portfolio_policy_fingerprint == baseline.policy_fingerprint,
        "baseline_fingerprint_mismatch",
        "trial manifest must bind the baseline policy fingerprint",
    )
    _require(
        trial.target_portfolio_policy_fingerprint == target.policy_fingerprint,
        "target_fingerprint_mismatch",
        "trial manifest must bind the target policy fingerprint",
    )
    _require(
        trial.target_policy_snapshot_registration_hash == target_policy_registration_hash(target),
        "target_registration_hash_mismatch",
        "trial manifest must bind the recomputed target registration hash",
    )

    _require(
        baseline.producers.btst_regime_admission_mode is RegimeAdmissionMode.IGNORE,
        "baseline_admission_mode",
        "baseline (Champion) policy must use regime admission IGNORE",
    )
    _require(
        target.producers.btst_regime_admission_mode is RegimeAdmissionMode.NORMAL_ONLY,
        "target_admission_mode",
        "target (Challenger) policy must use regime admission NORMAL_ONLY",
    )
    _require_producer_family(baseline, label="baseline")
    _require_producer_family(target, label="target")
    _require(
        baseline.runtime_mode is RuntimeMode.SHADOW and target.runtime_mode is RuntimeMode.SHADOW,
        "runtime_mode_not_shadow",
        "both arm policies must run in SHADOW runtime mode",
    )
    _require(
        baseline.versions == target.versions,
        "version_mismatch",
        "baseline and target policies must bind identical execution/cost versions",
    )
    _require(
        trial.execution_mode is ExecutionMode.DAILY_BAR_PROXY,
        "execution_mode_not_daily_bar_proxy",
        "trial manifest must run in DAILY_BAR_PROXY execution mode",
    )

    delta = policy_semantic_delta_paths(baseline, target)
    _require(
        delta == (_ADMITTED_DELTA_PATH,),
        "policy_delta_mismatch",
        "the only admitted behavioural delta is " f"{_ADMITTED_DELTA_PATH!r}; found {delta!r}",
    )

    return ValidatedRegimeTrialBundle(
        champion_policy=baseline,
        challenger_policy=target,
        baseline_policy=baseline,
        target_policy=target,
        trial_manifest=trial,
        sap_manifest=sap,
        admission_delta=delta,
    )


__all__ = [
    "GovernanceArtifactVerifierPort",
    "RegimeTrialBundle",
    "RegimeTrialGovernanceError",
    "SealedRegimeTrialBundle",
    "TARGET_POLICY_REGISTRATION_DOMAIN",
    "ValidatedRegimeTrialBundle",
    "policy_semantic_delta_paths",
    "target_policy_registration_hash",
    "validate_regime_trial_bundle",
]
