"""Centralized scoring feature quality model and pure Auto quality decisions.

Separates required scoring evidence (blocks Auto canonical) from optional
scoring evidence (warns and disables enhancement). Quality conclusions come
from actual consumed data rows, dates, and fingerprints — not from whether
a provider call appeared to succeed.

Spec reference: section 5 of the Auto/Daily Action readiness separation
design. The authority for Auto quality is ``payload["data_quality"]
["scoring_features"]``. The compatibility ``optional_features`` projection
and ``daily_action_cache_refresh`` stats belong to other domains and must
NOT influence the Auto verdict.

This module is intentionally pure: no file IO, no network calls, and no
side effects. Callers build the evidence mapping (typically produced by
:func:`ScoringFeatureStore.build_quality_summary` or its enriched successor)
and pass it to :func:`assess_auto_quality`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ObservationStatus(StrEnum):
    """Authoritative producer observation outcome for a feature family.

    Conservation semantics (spec 5.3):

    - ``success``: ``observed_count == requested_count`` and
      ``consumption_failed_count == 0``.
    - ``partial``: source reachable but only a strict subset of requested
      tickers received an authoritative answer.
    - ``failed``: an attempt was made but no verifiable answer was obtained.
    - ``unavailable``: source, schema, or capability entirely missing; no
      authoritative attempt could even be formed.
    """

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


# 首版 required/optional 分类来自 spec 5.1，禁止通过默认值暗中修改。
REQUIRED_SCORING_FEATURES = frozenset(
    {"price_history", "financial_metrics", "event_inputs"}
)
OPTIONAL_SCORING_FEATURES = frozenset(
    {
        "industry_pe_medians",
        "dragon_tiger_bonus",
        "intraday_short_trade_metrics",
        "daily_fund_flow_metrics",
    }
)
FEATURE_POLICIES = REQUIRED_SCORING_FEATURES | OPTIONAL_SCORING_FEATURES


@dataclass(frozen=True)
class FeaturePolicy:
    """Registry entry describing how a feature family is consumed.

    ``empty_semantics`` controls whether an observed-but-empty result is
    legal. ``"illegal"`` means nonempty evidence is required for success;
    ``"legal_when_observed"`` means an authoritative empty answer is itself
    valid evidence (e.g. no insider trades filed today); ``"always_legal"``
    is reserved for families that never carry row semantics.
    """

    name: str
    required: bool
    consumer_component: str
    empty_semantics: str  # "illegal" | "legal_when_observed" | "always_legal"
    freshness_rule: str = "exact_trade_date"
    min_usable_rows: int = 0
    required_score_components: tuple[str, ...] = ()


# 集中式策略注册表：新增/删除特征必须先在此登记。
FEATURE_POLICY_TABLE: Mapping[str, FeaturePolicy] = {
    "price_history": FeaturePolicy(
        name="price_history",
        required=True,
        consumer_component="score_batch.price_history",
        empty_semantics="illegal",
        freshness_rule="exact_trade_date",
        min_usable_rows=200,
        required_score_components=("trend", "mean_reversion"),
    ),
    "financial_metrics": FeaturePolicy(
        name="financial_metrics",
        required=True,
        consumer_component="score_batch.financial_metrics",
        empty_semantics="illegal",
        freshness_rule="exact_trade_date",
        required_score_components=("fundamental",),
    ),
    "event_inputs": FeaturePolicy(
        name="event_inputs",
        required=True,
        consumer_component="score_batch.event_inputs",
        empty_semantics="legal_when_observed",
        freshness_rule="exact_trade_date",
        required_score_components=("event_sentiment",),
    ),
    "industry_pe_medians": FeaturePolicy(
        name="industry_pe_medians",
        required=False,
        consumer_component="industry_pe_bonus",
        empty_semantics="always_legal",
        freshness_rule="exact_trade_date",
    ),
    "dragon_tiger_bonus": FeaturePolicy(
        name="dragon_tiger_bonus",
        required=False,
        consumer_component="dragon_tiger_bonus",
        empty_semantics="legal_when_observed",
        freshness_rule="exact_trade_date",
    ),
    "intraday_short_trade_metrics": FeaturePolicy(
        name="intraday_short_trade_metrics",
        required=False,
        consumer_component="intraday_short_trade_metrics",
        empty_semantics="legal_when_observed",
        freshness_rule="exact_trade_date",
    ),
    "daily_fund_flow_metrics": FeaturePolicy(
        name="daily_fund_flow_metrics",
        required=False,
        consumer_component="daily_fund_flow_metrics",
        empty_semantics="legal_when_observed",
        freshness_rule="exact_trade_date",
    ),
}


@dataclass(frozen=True)
class QualityIssue:
    """A single blocker or warning emitted by :func:`assess_auto_quality`."""

    family: str
    code: str
    detail: str = ""


@dataclass(frozen=True)
class QualityDecision:
    """Structured quality verdict replacing the legacy flat boolean."""

    healthy: bool
    blockers: tuple[QualityIssue, ...] = ()
    warnings: tuple[QualityIssue, ...] = ()

    @property
    def is_healthy(self) -> bool:
        """Backwards-compatible alias for callers migrating off the boolean."""
        return self.healthy


# ---------------------------------------------------------------------------
# Evidence model
# ---------------------------------------------------------------------------

# Integer evidence fields that must reject bool (Python bool is an int subclass).
_EVIDENCE_INT_FIELDS = (
    "attempted_count",
    "requested_count",
    "eligible_count",
    "observed_count",
    "usable_count",
    "nonempty_count",
    "stale_count",
    "refresh_failed_count",
    "consumption_failed_count",
    "usable_rows_min",
    "full_factor_target_rows",
)

# Optional string fingerprint / as-of fields. ``None`` is always acceptable
# unless a policy demands a value (validated by the assessor, not here).
_EVIDENCE_STR_FIELDS = (
    "requested_tickers_fingerprint",
    "observed_tickers_fingerprint",
    "usable_tickers_fingerprint",
    "input_fingerprint",
    "as_of_max",
)


@dataclass(frozen=True)
class FeatureEvidence:
    """Verifiable per-family consumption evidence.

    Field semantics follow spec 5.3. Counts are authoritative integers;
    fingerprints bind counts to a specific ticker set so that identical
    counts over a *different* ticker set cannot masquerade as success.
    """

    family: str
    observation_status: ObservationStatus
    attempted_count: int = 0
    requested_count: int = 0
    eligible_count: int = 0
    observed_count: int = 0
    usable_count: int = 0
    nonempty_count: int = 0
    stale_count: int = 0
    refresh_failed_count: int = 0
    consumption_failed_count: int = 0
    usable_rows_min: int = 0
    full_factor_target_rows: int = 0
    requested_tickers_fingerprint: str | None = None
    observed_tickers_fingerprint: str | None = None
    usable_tickers_fingerprint: str | None = None
    input_fingerprint: str | None = None
    as_of_max: str | None = None

    @classmethod
    def from_mapping(
        cls,
        family: str,
        raw: Mapping[str, Any],
        *,
        trade_date: str,
    ) -> FeatureEvidence:
        """Parse and validate a feature family evidence mapping.

        Raises :class:`ValueError` on any schema violation: unknown family,
        invalid status, bool passed where an int is required, negative
        counts, or non-string values in string fields.
        """
        if family not in FEATURE_POLICY_TABLE:
            raise ValueError(f"unknown scoring feature family: {family!r}")
        if not isinstance(raw, Mapping):
            raise ValueError(f"evidence for {family!r} must be a mapping")

        kwargs: dict[str, Any] = {"family": family}

        # observation_status: required, must be a known enum value.
        raw_status = raw.get("observation_status")
        if not isinstance(raw_status, str):
            raise ValueError(
                f"evidence for {family!r}: observation_status must be a string"
            )
        try:
            status = ObservationStatus(raw_status)
        except ValueError as exc:
            raise ValueError(
                f"evidence for {family!r}: invalid observation_status "
                f"{raw_status!r}"
            ) from exc
        kwargs["observation_status"] = status

        # Integer counts: reject bool, reject negative, reject non-int.
        for field_name in _EVIDENCE_INT_FIELDS:
            value = raw.get(field_name, 0)
            # Explicitly reject bool — `isinstance(True, int)` is True in Python.
            if isinstance(value, bool):
                raise ValueError(
                    f"evidence for {family!r}: {field_name} must be int, got bool"
                )
            if not isinstance(value, int):
                raise ValueError(
                    f"evidence for {family!r}: {field_name} must be int, "
                    f"got {type(value).__name__}"
                )
            if value < 0:
                raise ValueError(
                    f"evidence for {family!r}: {field_name}={value} is negative"
                )
            kwargs[field_name] = value

        # String fields: must be str or None. Empty string is permitted only
        # for optional fields; required-non-empty constraints are enforced in
        # the assessor, where required/optional semantics live.
        for field_name in _EVIDENCE_STR_FIELDS:
            value = raw.get(field_name)
            if value is None:
                kwargs[field_name] = None
                continue
            if not isinstance(value, str):
                raise ValueError(
                    f"evidence for {family!r}: {field_name} must be str or None, "
                    f"got {type(value).__name__}"
                )
            kwargs[field_name] = value

        policy = FEATURE_POLICY_TABLE[family]
        nonempty = kwargs["nonempty_count"]
        usable = kwargs["usable_count"]
        observed = kwargs["observed_count"]
        requested = kwargs["requested_count"]
        eligible = kwargs["eligible_count"]
        if not (0 <= nonempty <= usable <= observed <= requested <= eligible):
            raise ValueError(f"evidence for {family!r}: count conservation failed")

        if status is ObservationStatus.SUCCESS:
            if not (requested == observed == usable):
                raise ValueError(
                    f"evidence for {family!r}: success requires full coverage"
                )
            if kwargs["stale_count"] or kwargs["consumption_failed_count"]:
                raise ValueError(
                    f"evidence for {family!r}: success cannot consume stale or failed rows"
                )
            if (
                policy.min_usable_rows > 0
                and kwargs["usable_rows_min"] < policy.min_usable_rows
            ):
                raise ValueError(
                    f"evidence for {family!r}: usable_rows_min must be at least "
                    f"{policy.min_usable_rows}"
                )

        if policy.required:
            if not kwargs["input_fingerprint"]:
                raise ValueError(
                    f"evidence for {family!r}: input_fingerprint is required"
                )
            if _compact_date(kwargs["as_of_max"]) != _compact_date(trade_date):
                raise ValueError(
                    f"evidence for {family!r}: as_of_max must equal trade_date"
                )
            requested_fp = kwargs["requested_tickers_fingerprint"]
            observed_fp = kwargs["observed_tickers_fingerprint"]
            usable_fp = kwargs["usable_tickers_fingerprint"]
            if (
                not requested_fp
                or requested_fp != observed_fp
                or observed_fp != usable_fp
            ):
                raise ValueError(
                    f"evidence for {family!r}: ticker identity mismatch"
                )

        return cls(**kwargs)


# ---------------------------------------------------------------------------
# Fingerprint helper
# ---------------------------------------------------------------------------


def ticker_set_fingerprint(tickers: Sequence[str]) -> str:
    """SHA-256 fingerprint of a sorted unique ticker set.

    Stable canonicalization: callers must pass the same normalization
    (six-digit codes, no suffix) they use elsewhere so equality reflects
    ticker identity rather than formatting.
    """
    canonical = json.dumps(sorted(set(tickers)), separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _compact_date(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    compact = raw.replace("-", "")
    return compact if len(compact) == 8 and compact.isdigit() else None


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------


def assess_auto_quality(payload: Mapping[str, Any]) -> QualityDecision:
    """Assess Auto quality from actual consumed scoring evidence.

    Reads only ``payload["data_quality"]["scoring_features"]``. Any other
    field (``optional_features`` compatibility projection, daily-action
    cache refresh stats, freshness summary) is intentionally ignored —
    those belong to other domains per spec sections 4 and 10.

    Blocking (Auto canonical cannot publish):
      - A required feature is missing from ``scoring_features``.
      - A required feature has ``observation_status`` other than ``success``.
      - A required feature with ``success`` lacks any of the three ticker
        fingerprints, or they are not all equal (counts could correspond to
        a different ticker set).
      - A required feature with ``empty_semantics="illegal"`` reports
        ``nonempty_count == 0``.
      - A required feature actually fell back to stale data
        (``stale_count > 0``) or failed consumption
        (``consumption_failed_count > 0``).

    Warning-only (Auto canonical still healthy):
      - A required feature is fully usable now but recorded
        ``refresh_failed_count > 0``: local evidence is authoritative.
      - Any optional feature is missing or has any failure signal.
    """
    quality = payload.get("data_quality")
    if not isinstance(quality, Mapping):
        return QualityDecision(
            healthy=False,
            blockers=(QualityIssue("data_quality", "missing_data_quality_block"),),
        )
    scoring_features = quality.get("scoring_features")
    if not isinstance(scoring_features, Mapping):
        return QualityDecision(
            healthy=False,
            blockers=(
                QualityIssue("scoring_features", "missing_scoring_features_block"),
            ),
        )

    trade_date = payload.get("date")
    blockers: list[QualityIssue] = []
    warnings: list[QualityIssue] = []

    # Required features must all be present and succeed.
    for family in sorted(REQUIRED_SCORING_FEATURES):
        policy = FEATURE_POLICY_TABLE[family]
        raw = scoring_features.get(family)
        if raw is None:
            blockers.append(
                QualityIssue(family, "required_feature_missing")
            )
            continue
        try:
            evidence = FeatureEvidence.from_mapping(
                family, raw, trade_date=str(trade_date or "")
            )
        except ValueError as exc:
            blockers.extend(_required_schema_issues(family, raw, exc))
            continue

        _assess_required_family(policy, evidence, blockers, warnings)

    # Optional features only ever warn.
    for family in sorted(OPTIONAL_SCORING_FEATURES):
        policy = FEATURE_POLICY_TABLE[family]
        raw = scoring_features.get(family)
        if raw is None:
            warnings.append(
                QualityIssue(family, "optional_feature_missing")
            )
            continue
        try:
            evidence = FeatureEvidence.from_mapping(
                family, raw, trade_date=str(trade_date or "")
            )
        except ValueError as exc:
            warnings.append(
                QualityIssue(
                    family, "optional_evidence_schema_invalid", detail=str(exc)
                )
            )
            continue
        _assess_optional_family(policy, evidence, warnings)

    healthy = not blockers
    return QualityDecision(
        healthy=healthy,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )


def _required_schema_issues(
    family: str, raw: object, error: ValueError
) -> list[QualityIssue]:
    """Preserve stable diagnostic codes while validation fails at the boundary."""
    detail = str(error)
    if not isinstance(raw, Mapping):
        return [QualityIssue(family, "evidence_schema_invalid", detail=detail)]
    if "ticker identity mismatch" in detail:
        fingerprints = (
            raw.get("requested_tickers_fingerprint"),
            raw.get("observed_tickers_fingerprint"),
            raw.get("usable_tickers_fingerprint"),
        )
        code = (
            "required_ticker_fingerprint_missing"
            if any(not fingerprint for fingerprint in fingerprints)
            else "required_ticker_fingerprint_mismatch"
        )
        return [QualityIssue(family, code, detail=detail)]
    if "success cannot consume stale or failed rows" in detail:
        issues: list[QualityIssue] = []
        stale_count = raw.get("stale_count")
        failed_count = raw.get("consumption_failed_count")
        if (
            isinstance(stale_count, int)
            and not isinstance(stale_count, bool)
            and stale_count > 0
        ):
            issues.append(
                QualityIssue(family, "required_stale_fallback", detail=detail)
            )
        if (
            isinstance(failed_count, int)
            and not isinstance(failed_count, bool)
            and failed_count > 0
        ):
            issues.append(
                QualityIssue(family, "required_consumption_failed", detail=detail)
            )
        if issues:
            return issues
    return [QualityIssue(family, "evidence_schema_invalid", detail=detail)]


def _assess_required_family(
    policy: FeaturePolicy,
    evidence: FeatureEvidence,
    blockers: list[QualityIssue],
    warnings: list[QualityIssue],
) -> None:
    """Apply required-family gating rules, appending to ``blockers``/``warnings``.

    Required families must be fully observed with matching ticker identity.
    The only warning-only path for a required family is a recorded provider
    refresh failure that did not affect the local consumption evidence.
    """
    family = policy.name

    if evidence.observation_status is not ObservationStatus.SUCCESS:
        blockers.append(
            QualityIssue(
                family,
                "required_observation_not_success",
                detail=f"status={evidence.observation_status.value}",
            )
        )
        # A non-success required feature cannot be redeemed by anything below.
        return

    # Stale fallback or consumption failure on a required family is a hard
    # block: the consumed evidence itself is not verifiably current/complete.
    if evidence.stale_count > 0:
        blockers.append(
            QualityIssue(
                family,
                "required_stale_fallback",
                detail=f"stale_count={evidence.stale_count}",
            )
        )
    if evidence.consumption_failed_count > 0:
        blockers.append(
            QualityIssue(
                family,
                "required_consumption_failed",
                detail=f"consumption_failed_count={evidence.consumption_failed_count}",
            )
        )

    # Ticker identity: counts are meaningless unless they refer to the same
    # ticker set. All three fingerprints must be present and equal so that
    # "300 observed" cannot be "300 different tickers".
    fingerprints = (
        evidence.requested_tickers_fingerprint,
        evidence.observed_tickers_fingerprint,
        evidence.usable_tickers_fingerprint,
    )
    if any(fp is None for fp in fingerprints):
        blockers.append(
            QualityIssue(family, "required_ticker_fingerprint_missing")
        )
    else:
        # All three are non-None here.
        if not (
            evidence.requested_tickers_fingerprint
            == evidence.observed_tickers_fingerprint
            == evidence.usable_tickers_fingerprint
        ):
            blockers.append(
                QualityIssue(
                    family,
                    "required_ticker_fingerprint_mismatch",
                )
            )

    # Empty semantics: required families that disallow empty must show at
    # least one nonempty row. event_inputs allows legal-empty observations.
    if policy.empty_semantics == "illegal" and evidence.nonempty_count <= 0:
        blockers.append(
            QualityIssue(
                family,
                "required_empty_illegal",
                detail=f"nonempty_count={evidence.nonempty_count}",
            )
        )

    # Provider refresh failed but local consumption is current and complete:
    # the local verifiable snapshot is authoritative, so this is only a warning.
    if evidence.refresh_failed_count > 0:
        warnings.append(
            QualityIssue(
                family,
                "required_refresh_failed_current_consumed",
                detail=f"refresh_failed_count={evidence.refresh_failed_count}",
            )
        )


def _assess_optional_family(
    policy: FeaturePolicy,
    evidence: FeatureEvidence,
    warnings: list[QualityIssue],
) -> None:
    """Apply optional-family rules: any failure or staleness produces a warning."""
    family = policy.name

    if evidence.observation_status is not ObservationStatus.SUCCESS:
        warnings.append(
            QualityIssue(
                family,
                "optional_observation_not_success",
                detail=f"status={evidence.observation_status.value}",
            )
        )
        return

    if evidence.stale_count > 0:
        warnings.append(
            QualityIssue(
                family,
                "optional_stale_fallback",
                detail=f"stale_count={evidence.stale_count}",
            )
        )
    if evidence.consumption_failed_count > 0:
        warnings.append(
            QualityIssue(
                family,
                "optional_consumption_failed",
                detail=f"consumption_failed_count={evidence.consumption_failed_count}",
            )
        )
    if evidence.refresh_failed_count > 0:
        warnings.append(
            QualityIssue(
                family,
                "optional_refresh_failed",
                detail=f"refresh_failed_count={evidence.refresh_failed_count}",
            )
        )
