"""Tests for the centralized scoring feature quality model.

Spec reference: section 5 of the Auto/Daily Action readiness separation
design. These tests exercise the pure ``assess_auto_quality`` decision and
the ``FeatureEvidence`` schema validator; they perform no IO.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from src.screening.scoring_feature_quality import (
    FEATURE_POLICIES,
    OPTIONAL_SCORING_FEATURES,
    REQUIRED_SCORING_FEATURES,
    FeatureEvidence,
    ObservationStatus,
    assess_auto_quality,
    ticker_set_fingerprint,
)


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------

_TICKERS = ["000001", "000002", "600000"]
_FINGERPRINT = ticker_set_fingerprint(_TICKERS)
_OTHER_FINGERPRINT = ticker_set_fingerprint(["300001", "300002", "688001"])


def _required_success_evidence(nonempty: int = 3) -> dict[str, Any]:
    """A required family with a fully successful observation."""
    return {
        "observation_status": "success",
        "attempted_count": 3,
        "requested_count": 3,
        "eligible_count": 3,
        "observed_count": 3,
        "usable_count": 3,
        "nonempty_count": nonempty,
        "stale_count": 0,
        "refresh_failed_count": 0,
        "consumption_failed_count": 0,
        "usable_rows_min": 250,
        "full_factor_target_rows": 400,
        "requested_tickers_fingerprint": _FINGERPRINT,
        "observed_tickers_fingerprint": _FINGERPRINT,
        "usable_tickers_fingerprint": _FINGERPRINT,
        "input_fingerprint": "sha256:input",
        "as_of_max": "20260713",
    }


def _optional_unavailable_evidence() -> dict[str, Any]:
    """An optional family whose source is entirely unavailable."""
    return {
        "observation_status": "unavailable",
        "attempted_count": 0,
        "requested_count": 0,
        "eligible_count": 0,
        "observed_count": 0,
        "usable_count": 0,
        "nonempty_count": 0,
        "stale_count": 0,
        "refresh_failed_count": 0,
        "consumption_failed_count": 0,
    }


def test_required_success_rejects_inconsistent_counts():
    evidence = _required_success_evidence()
    evidence.update(
        eligible_count=300,
        requested_count=1,
        observed_count=1,
        usable_count=1,
        nonempty_count=1,
    )
    with pytest.raises(ValueError, match="full eligible coverage"):
        FeatureEvidence.from_mapping(
            "price_history", evidence, trade_date="20260713"
        )


@pytest.mark.parametrize("family", ["financial_metrics", "event_inputs"])
def test_heavy_required_success_allows_eligible_subset(family):
    evidence = _required_success_evidence(nonempty=1)
    evidence.update(
        eligible_count=300,
        requested_count=1,
        observed_count=1,
        usable_count=1,
        attempted_count=1,
    )
    parsed = FeatureEvidence.from_mapping(
        family, evidence, trade_date="20260713"
    )
    assert parsed.requested_count == 1


def test_required_success_rejects_missing_input_fingerprint():
    evidence = _required_success_evidence()
    evidence["input_fingerprint"] = None
    with pytest.raises(ValueError, match="input_fingerprint"):
        FeatureEvidence.from_mapping(
            "financial_metrics", evidence, trade_date="20260713"
        )


@pytest.mark.parametrize("as_of_max", [None, "not-a-date", "20261340"])
def test_required_success_rejects_missing_or_invalid_as_of(as_of_max):
    evidence = _required_success_evidence()
    evidence["as_of_max"] = as_of_max
    with pytest.raises(ValueError, match="as_of_max"):
        FeatureEvidence.from_mapping(
            "financial_metrics", evidence, trade_date="20260713"
        )


@pytest.mark.parametrize("trade_date", ["not-a-date", "20261340"])
def test_required_success_rejects_invalid_trade_date(trade_date):
    evidence = _required_success_evidence()
    evidence["as_of_max"] = trade_date
    with pytest.raises(ValueError, match="trade_date"):
        FeatureEvidence.from_mapping(
            "financial_metrics", evidence, trade_date=trade_date
        )


@pytest.mark.parametrize("trade_date", [None, "not-a-date", "20261340"])
def test_assess_auto_quality_rejects_missing_or_invalid_trade_date(trade_date):
    payload = quality_payload()
    if trade_date is None:
        payload.pop("date")
    else:
        payload["date"] = trade_date
    for evidence in payload["data_quality"]["scoring_features"].values():
        if evidence.get("input_fingerprint"):
            evidence["as_of_max"] = trade_date

    decision = assess_auto_quality(payload)

    assert decision.healthy is False
    assert any(issue.code == "evidence_schema_invalid" for issue in decision.blockers)


def test_success_rejects_empty_request():
    evidence = _optional_unavailable_evidence()
    evidence["observation_status"] = "success"
    with pytest.raises(ValueError, match="success requires a nonempty request"):
        FeatureEvidence.from_mapping(
            "dragon_tiger_bonus", evidence, trade_date="20260713"
        )


@pytest.mark.parametrize(
    "updates",
    [
        {
            "attempted_count": 1,
            "requested_count": 1,
            "eligible_count": 1,
            "observed_count": 1,
            "usable_count": 1,
        },
        {"attempted_count": 1, "eligible_count": 1},
    ],
)
def test_partial_rejects_non_partial_state(updates):
    evidence = _optional_unavailable_evidence()
    evidence.update(observation_status="partial", **updates)
    with pytest.raises(ValueError, match="partial requires"):
        FeatureEvidence.from_mapping(
            "dragon_tiger_bonus", evidence, trade_date="20260713"
        )


@pytest.mark.parametrize(
    "updates",
    [
        {
            "attempted_count": 1,
            "requested_count": 1,
            "eligible_count": 1,
        },
        {
            "attempted_count": 1,
            "requested_count": 1,
            "eligible_count": 1,
            "observed_count": 1,
            "usable_count": 1,
            "nonempty_count": 1,
            "consumption_failed_count": 1,
        },
    ],
)
def test_failed_rejects_contradictory_state(updates):
    evidence = _optional_unavailable_evidence()
    evidence.update(observation_status="failed", **updates)
    with pytest.raises(ValueError, match="failed requires"):
        FeatureEvidence.from_mapping(
            "dragon_tiger_bonus", evidence, trade_date="20260713"
        )


@pytest.mark.parametrize("active_field", ["attempted_count", "requested_count"])
def test_unavailable_rejects_activity(active_field):
    evidence = _optional_unavailable_evidence()
    evidence["eligible_count"] = 3
    evidence[active_field] = 1
    with pytest.raises(ValueError, match="unavailable requires zero activity"):
        FeatureEvidence.from_mapping(
            "dragon_tiger_bonus", evidence, trade_date="20260713"
        )


def test_unavailable_allows_nonzero_eligible_scope():
    evidence = _optional_unavailable_evidence()
    evidence["eligible_count"] = 3
    parsed = FeatureEvidence.from_mapping(
        "dragon_tiger_bonus", evidence, trade_date="20260713"
    )
    assert parsed.observation_status is ObservationStatus.UNAVAILABLE


def quality_payload(
    required: str = "success",
    optional: str = "unavailable",
    *,
    required_evidence: dict[str, Any] | None = None,
    optional_evidence: dict[str, Any] | None = None,
    extra_scoring_features: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a valid scoring quality payload.

    Parameters
    ----------
    required:
        Status to set on every required family when ``required_evidence``
        is not provided. Use ``"success"`` / ``"partial"`` / ``"failed"``
        / ``"unavailable"``.
    optional:
        Status to set on every optional family when ``optional_evidence``
        is not provided.
    required_evidence / optional_evidence:
        Per-family overrides. When supplied, ``required`` / ``optional``
        status arguments are ignored for that family.
    extra_scoring_features:
        Additional families to merge into ``scoring_features`` (e.g. for
        fingerprint mismatch tests).
    """
    scoring_features: dict[str, dict[str, Any]] = {}

    for family in REQUIRED_SCORING_FEATURES:
        if required_evidence and family in required_evidence:
            scoring_features[family] = deepcopy(required_evidence[family])
            continue
        base = _required_success_evidence()
        base["observation_status"] = required
        scoring_features[family] = base

    for family in OPTIONAL_SCORING_FEATURES:
        if optional_evidence and family in optional_evidence:
            scoring_features[family] = deepcopy(optional_evidence[family])
            continue
        base = _optional_unavailable_evidence()
        base["observation_status"] = optional
        scoring_features[family] = base

    if extra_scoring_features:
        scoring_features.update(deepcopy(extra_scoring_features))

    return {
        "date": "20260713",
        "data_quality": {
            "scoring_features": scoring_features,
            # Compatibility projection: must NOT affect the verdict.
            "optional_features": {
                family: {"coverage": 0.0}
                for family in OPTIONAL_SCORING_FEATURES
            },
        },
        # Daily-action domain stats: must NOT affect the Auto verdict.
        "daily_action_cache_refresh": {
            "status": "failed",
            "price_failed": 999,
            "price_missing": 999,
        },
        "data_freshness": {"fresh": False},
    }


# ---------------------------------------------------------------------------
# Healthy paths
# ---------------------------------------------------------------------------


def test_complete_required_and_missing_optional_is_healthy() -> None:
    """Required complete, optional unavailable → healthy with warnings."""
    payload = quality_payload(required="success", optional="unavailable")
    decision = assess_auto_quality(payload)
    assert decision.healthy is True
    assert decision.blockers == ()
    # Every optional family is unavailable → one warning each.
    optional_warning_families = {
        issue.family for issue in decision.warnings if issue.family in OPTIONAL_SCORING_FEATURES
    }
    assert optional_warning_families == set(OPTIONAL_SCORING_FEATURES)


def test_all_optional_success_is_healthy_no_warnings() -> None:
    """When every optional family also succeeds, there are no warnings."""
    optional_success = {
        "observation_status": "success",
        "attempted_count": 3,
        "requested_count": 3,
        "eligible_count": 3,
        "observed_count": 3,
        "usable_count": 3,
        "nonempty_count": 1,
        "stale_count": 0,
        "refresh_failed_count": 0,
        "consumption_failed_count": 0,
    }
    payload = quality_payload(
        required="success",
        optional_evidence={
            family: dict(optional_success) for family in OPTIONAL_SCORING_FEATURES
        },
    )
    decision = assess_auto_quality(payload)
    assert decision.healthy is True
    assert decision.blockers == ()
    assert decision.warnings == ()


def test_legal_empty_events_are_healthy() -> None:
    """Events with observation_status=success, nonempty=0 → healthy (legal empty)."""
    payload = quality_payload(
        required="success",
        required_evidence={"event_inputs": {**_required_success_evidence(nonempty=0)}},
    )
    decision = assess_auto_quality(payload)
    assert decision.healthy is True
    # Other required families (price_history, financial_metrics) still report
    # nonempty evidence, so the only way this passes is event_inputs allowed
    # its legal-empty observation.
    assert decision.blockers == ()


# ---------------------------------------------------------------------------
# Blocking paths
# ---------------------------------------------------------------------------


def test_missing_required_feature_blocks() -> None:
    """Required feature missing from scoring_features → blocked."""
    payload = quality_payload(required="success")
    del payload["data_quality"]["scoring_features"]["financial_metrics"]
    decision = assess_auto_quality(payload)
    assert decision.healthy is False
    codes = {issue.code for issue in decision.blockers}
    assert "required_feature_missing" in codes
    blocker_families = {issue.family for issue in decision.blockers}
    assert "financial_metrics" in blocker_families


def test_partial_observation_blocks_required() -> None:
    """Required feature with partial observation → blocked."""
    payload = quality_payload(
        required="success",
        required_evidence={
            "price_history": {
                **_required_success_evidence(),
                "observation_status": "partial",
                "observed_count": 2,
                "usable_count": 2,
                "nonempty_count": 2,
                "consumption_failed_count": 1,
            },
        },
    )
    decision = assess_auto_quality(payload)
    assert decision.healthy is False
    codes = {issue.code for issue in decision.blockers}
    assert "required_observation_not_success" in codes


def test_failed_observation_blocks_required() -> None:
    payload = quality_payload(
        required="success",
        required_evidence={
            "financial_metrics": {
                **_required_success_evidence(),
                "observation_status": "failed",
                "observed_count": 0,
                "usable_count": 0,
                "nonempty_count": 0,
                "consumption_failed_count": 3,
            }
        },
    )
    decision = assess_auto_quality(payload)
    assert decision.healthy is False
    assert any(issue.code == "required_observation_not_success" for issue in decision.blockers)


def test_unavailable_observation_blocks_required() -> None:
    payload = quality_payload(
        required_evidence={
            "event_inputs": {
                **_required_success_evidence(nonempty=0),
                "observation_status": "unavailable",
                "attempted_count": 0,
                "requested_count": 0,
                "observed_count": 0,
                "usable_count": 0,
            }
        },
    )
    decision = assess_auto_quality(payload)
    assert decision.healthy is False
    assert any(
        issue.code == "required_observation_not_success"
        and issue.family == "event_inputs"
        for issue in decision.blockers
    )


def test_equal_counts_with_wrong_ticker_identity_is_blocked() -> None:
    """Same counts but different fingerprint → blocked."""
    payload = quality_payload(
        required="success",
        required_evidence={
            "price_history": {
                **_required_success_evidence(),
                "observed_tickers_fingerprint": _OTHER_FINGERPRINT,
                "usable_tickers_fingerprint": _OTHER_FINGERPRINT,
            }
        },
    )
    decision = assess_auto_quality(payload)
    assert decision.healthy is False
    codes = {issue.code for issue in decision.blockers}
    assert "required_ticker_fingerprint_mismatch" in codes


def test_missing_fingerprint_on_required_success_blocks() -> None:
    """Required success without one of the fingerprints → blocked."""
    evidence = _required_success_evidence()
    evidence["usable_tickers_fingerprint"] = None
    payload = quality_payload(
        required_evidence={"price_history": evidence},
    )
    decision = assess_auto_quality(payload)
    assert decision.healthy is False
    assert any(
        issue.code == "required_ticker_fingerprint_missing"
        and issue.family == "price_history"
        for issue in decision.blockers
    )


def test_illegal_empty_required_family_blocks() -> None:
    """price_history with nonempty_count=0 → blocked (illegal empty)."""
    payload = quality_payload(
        required_evidence={
            "price_history": {**_required_success_evidence(nonempty=0)},
        },
    )
    decision = assess_auto_quality(payload)
    assert decision.healthy is False
    assert any(
        issue.code == "required_empty_illegal"
        and issue.family == "price_history"
        for issue in decision.blockers
    )


def test_stale_required_fallback_blocks() -> None:
    """Required feature that fell back to stale data → blocked."""
    payload = quality_payload(
        required_evidence={
            "price_history": {**_required_success_evidence(), "stale_count": 1},
        },
    )
    decision = assess_auto_quality(payload)
    assert decision.healthy is False
    assert any(
        issue.code == "required_stale_fallback"
        and issue.family == "price_history"
        for issue in decision.blockers
    )


def test_required_consumption_failed_blocks() -> None:
    payload = quality_payload(
        required_evidence={
            "financial_metrics": {
                **_required_success_evidence(),
                "consumption_failed_count": 2,
            }
        },
    )
    decision = assess_auto_quality(payload)
    assert decision.healthy is False
    assert any(
        issue.code == "required_consumption_failed"
        and issue.family == "financial_metrics"
        for issue in decision.blockers
    )


# ---------------------------------------------------------------------------
# Warning-only paths for required features
# ---------------------------------------------------------------------------


def test_refresh_failure_with_current_consumption_is_warning_only() -> None:
    """refresh_failed_count > 0 but usable_count > 0 + success → warning."""
    payload = quality_payload(
        required_evidence={
            "price_history": {
                **_required_success_evidence(),
                "refresh_failed_count": 3,
            }
        },
    )
    decision = assess_auto_quality(payload)
    assert decision.healthy is True
    assert decision.blockers == ()
    assert any(
        issue.code == "required_refresh_failed_current_consumed"
        and issue.family == "price_history"
        for issue in decision.warnings
    )


# ---------------------------------------------------------------------------
# Optional family behavior
# ---------------------------------------------------------------------------


def test_optional_partial_is_warning_not_blocker() -> None:
    payload = quality_payload(
        optional_evidence={
            "dragon_tiger_bonus": {
                **_optional_unavailable_evidence(),
                "observation_status": "partial",
                "attempted_count": 1,
                "requested_count": 1,
                "eligible_count": 1,
                "consumption_failed_count": 1,
            },
        },
    )
    decision = assess_auto_quality(payload)
    assert decision.healthy is True
    assert decision.blockers == ()
    assert any(
        issue.code == "optional_observation_not_success"
        and issue.family == "dragon_tiger_bonus"
        for issue in decision.warnings
    )


def test_optional_refresh_failed_is_warning() -> None:
    payload = quality_payload(
        optional_evidence={
            "daily_fund_flow_metrics": {
                **_optional_unavailable_evidence(),
                "observation_status": "success",
                "attempted_count": 3,
                "eligible_count": 3,
                "requested_count": 3,
                "observed_count": 3,
                "usable_count": 3,
                "nonempty_count": 2,
                "refresh_failed_count": 1,
            }
        },
    )
    decision = assess_auto_quality(payload)
    assert decision.healthy is True
    assert any(
        issue.code == "optional_refresh_failed"
        and issue.family == "daily_fund_flow_metrics"
        for issue in decision.warnings
    )


def test_optional_missing_family_is_warning_only() -> None:
    """An optional family entirely absent from scoring_features → warning."""
    payload = quality_payload(required="success", optional="success")
    # Force success evidence then delete one optional family.
    success_optional = {
        "observation_status": "success",
        "requested_count": 3,
        "observed_count": 3,
        "usable_count": 3,
        "nonempty_count": 1,
    }
    payload = quality_payload(
        optional_evidence={
            family: dict(success_optional) for family in OPTIONAL_SCORING_FEATURES
        },
    )
    del payload["data_quality"]["scoring_features"]["industry_pe_medians"]
    decision = assess_auto_quality(payload)
    assert decision.healthy is True
    assert any(
        issue.code == "optional_feature_missing"
        and issue.family == "industry_pe_medians"
        for issue in decision.warnings
    )


# ---------------------------------------------------------------------------
# Domain isolation: compatibility fields must not affect the verdict
# ---------------------------------------------------------------------------


def test_optional_features_compatibility_field_does_not_affect_verdict() -> None:
    """optional_features compatibility field cannot change the verdict."""
    base = quality_payload(required="success", optional="unavailable")
    healthy_decision = assess_auto_quality(base)

    # Now corrupt the compatibility projection to claim full coverage. The
    # authoritative scoring_features still show unavailable, so the verdict
    # and warnings must be unchanged.
    corrupted = deepcopy(base)
    corrupted["data_quality"]["optional_features"] = {
        family: {"coverage": 1.0, "provider_failures": 0}
        for family in OPTIONAL_SCORING_FEATURES
    }
    corrupted_decision = assess_auto_quality(corrupted)
    assert corrupted_decision.healthy == healthy_decision.healthy
    assert corrupted_decision.blockers == healthy_decision.blockers
    assert corrupted_decision.warnings == healthy_decision.warnings


def test_daily_action_cache_refresh_does_not_affect_verdict() -> None:
    """daily_action_cache_refresh stats do not affect Auto quality."""
    base = quality_payload(required="success", optional="unavailable")
    healthy_decision = assess_auto_quality(base)

    # Wipe the daily-action cache refresh block entirely; the verdict must
    # not change because Auto quality only reads scoring_features.
    without_refresh = deepcopy(base)
    without_refresh.pop("daily_action_cache_refresh", None)
    decision = assess_auto_quality(without_refresh)
    assert decision.healthy == healthy_decision.healthy
    assert decision.blockers == healthy_decision.blockers
    assert decision.warnings == healthy_decision.warnings

    # Also confirm a wildly failing cache refresh block does not flip it.
    failing = deepcopy(base)
    failing["daily_action_cache_refresh"] = {
        "status": "failed",
        "price_failed": 100,
        "price_missing": 100,
        "price_insufficient_history": 100,
        "fund_flow_failed": 100,
        "fund_flow_empty": 100,
        "industry_index_failed": 100,
    }
    failing_decision = assess_auto_quality(failing)
    assert failing_decision.healthy == healthy_decision.healthy


def test_data_freshness_field_does_not_affect_verdict() -> None:
    """The legacy ``data_freshness`` summary is not an Auto authority."""
    payload = quality_payload(required="success", optional="unavailable")
    # Even with data_freshness explicitly false, scoring_features governs.
    payload["data_freshness"] = {"fresh": False}
    decision = assess_auto_quality(payload)
    assert decision.healthy is True


def test_missing_data_quality_block_blocks() -> None:
    decision = assess_auto_quality({"daily_action_cache_refresh": {"status": "success"}})
    assert decision.healthy is False
    assert any(issue.code == "missing_data_quality_block" for issue in decision.blockers)


def test_missing_scoring_features_block_blocks() -> None:
    decision = assess_auto_quality({"data_quality": {"optional_features": {}}})
    assert decision.healthy is False
    assert any(issue.code == "missing_scoring_features_block" for issue in decision.blockers)


# ---------------------------------------------------------------------------
# FeatureEvidence.from_mapping schema validation
# ---------------------------------------------------------------------------


def test_evidence_rejects_unknown_family() -> None:
    with pytest.raises(ValueError, match="unknown scoring feature family"):
        FeatureEvidence.from_mapping(
            "not_a_family", {"observation_status": "success"}, trade_date="20260713"
        )


def test_evidence_rejects_invalid_status() -> None:
    with pytest.raises(ValueError, match="invalid observation_status"):
        FeatureEvidence.from_mapping(
            "price_history",
            {"observation_status": "kinda_ok"},
            trade_date="20260713",
        )


def test_evidence_rejects_bool_count() -> None:
    """Python bool is an int subclass — it must be rejected for counts."""
    raw = _required_success_evidence()
    raw["requested_count"] = True
    with pytest.raises(ValueError, match="requested_count must be int, got bool"):
        FeatureEvidence.from_mapping("price_history", raw, trade_date="20260713")


def test_evidence_rejects_negative_count() -> None:
    raw = _required_success_evidence()
    raw["observed_count"] = -1
    with pytest.raises(ValueError, match="observed_count=-1 is negative"):
        FeatureEvidence.from_mapping("price_history", raw, trade_date="20260713")


def test_evidence_rejects_non_int_count() -> None:
    raw = _required_success_evidence()
    raw["usable_count"] = 3.5
    with pytest.raises(ValueError, match="usable_count must be int"):
        FeatureEvidence.from_mapping("price_history", raw, trade_date="20260713")


def test_evidence_rejects_non_string_fingerprint() -> None:
    raw = _required_success_evidence()
    raw["requested_tickers_fingerprint"] = 12345
    with pytest.raises(ValueError, match="requested_tickers_fingerprint must be str or None"):
        FeatureEvidence.from_mapping("price_history", raw, trade_date="20260713")


def test_evidence_accepts_none_fingerprints() -> None:
    raw = _optional_unavailable_evidence()
    evidence = FeatureEvidence.from_mapping(
        "industry_pe_medians", raw, trade_date="20260713"
    )
    assert evidence.requested_tickers_fingerprint is None
    assert evidence.as_of_max is None


def test_evidence_defaults_counts_to_zero() -> None:
    evidence = FeatureEvidence.from_mapping(
        "industry_pe_medians",
        {"observation_status": "unavailable"},
        trade_date="20260713",
    )
    assert evidence.requested_count == 0
    assert evidence.usable_count == 0
    assert evidence.refresh_failed_count == 0


def test_evidence_status_is_coerced_to_enum() -> None:
    evidence = FeatureEvidence.from_mapping(
        "price_history",
        _required_success_evidence(),
        trade_date="20260713",
    )
    assert evidence.observation_status is ObservationStatus.SUCCESS


# ---------------------------------------------------------------------------
# Registry sanity
# ---------------------------------------------------------------------------


def test_feature_policies_partition_required_and_optional() -> None:
    assert FEATURE_POLICIES == REQUIRED_SCORING_FEATURES | OPTIONAL_SCORING_FEATURES
    assert REQUIRED_SCORING_FEATURES.isdisjoint(OPTIONAL_SCORING_FEATURES)


def test_required_families_match_spec() -> None:
    assert REQUIRED_SCORING_FEATURES == frozenset(
        {"price_history", "financial_metrics", "event_inputs"}
    )


def test_optional_families_match_spec() -> None:
    assert OPTIONAL_SCORING_FEATURES == frozenset(
        {
            "industry_pe_medians",
            "dragon_tiger_bonus",
            "intraday_short_trade_metrics",
            "daily_fund_flow_metrics",
        }
    )


def test_event_inputs_policy_allows_legal_empty() -> None:
    """Only event_inputs may have a successful empty observation."""
    from src.screening.scoring_feature_quality import FEATURE_POLICY_TABLE

    assert FEATURE_POLICY_TABLE["event_inputs"].empty_semantics == "legal_when_observed"
    assert FEATURE_POLICY_TABLE["price_history"].empty_semantics == "illegal"
    assert FEATURE_POLICY_TABLE["financial_metrics"].empty_semantics == "illegal"


# ---------------------------------------------------------------------------
# Fingerprint helper
# ---------------------------------------------------------------------------


def test_ticker_fingerprint_is_order_and_duplicate_invariant() -> None:
    assert ticker_set_fingerprint(["000001", "000002"]) == ticker_set_fingerprint(
        ["000002", "000001"]
    )
    assert ticker_set_fingerprint(["000001", "000001"]) == ticker_set_fingerprint(
        ["000001"]
    )


def test_ticker_fingerprint_changes_with_membership() -> None:
    assert ticker_set_fingerprint(["000001"]) != ticker_set_fingerprint(["000002"])


def test_ticker_fingerprint_has_sha256_prefix() -> None:
    fp = ticker_set_fingerprint(["000001"])
    assert fp.startswith("sha256:")
    assert len(fp) == len("sha256:") + 64
