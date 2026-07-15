"""Adversarial tests for Daily Action readiness manifest v2."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from src.screening.offensive.cache_readiness import (
    DailyActionRefreshResult,
    FundFlowStatus,
    PriceStatus,
    SuspensionEvidence,
    TickerRefreshOutcome,
    derive_stats_from_outcomes,
    universe_fingerprint,
)
from src.screening.offensive.daily_action_readiness import (
    ManifestValidationError,
    SharedReadinessEvidence,
    build_daily_action_readiness,
    parse_manifest_v2,
    publish_daily_action_attempt,
    publish_daily_action_readiness,
)
from src.screening.offensive.pit_evidence import canonical_fingerprint
from src.utils.date_utils import SIGNAL_SESSION_POLICY_VERSION


SIGNAL_DATE = date(2026, 7, 13)


def _fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _resign(raw: dict[str, object]) -> None:
    unsigned = copy.deepcopy(raw)
    unsigned.pop("content_fingerprint", None)
    raw["content_fingerprint"] = _fingerprint(unsigned)


def _shared_evidence(tickers: tuple[str, ...]) -> SharedReadinessEvidence:
    regime_row = {"regime": "normal", "source_date": SIGNAL_DATE.isoformat()}
    industry_by_ticker = {ticker: "银行" for ticker in tickers}
    industry_day_pct = {ticker: 1.25 for ticker in tickers}
    security_status_by_ticker = {ticker: "listed" for ticker in tickers}
    return SharedReadinessEvidence(
        regime_row=regime_row,
        industry_by_ticker=industry_by_ticker,
        industry_day_pct=industry_day_pct,
        security_status_by_ticker=security_status_by_ticker,
        regime_fingerprint=_fingerprint({"regime_row": regime_row}),
        industry_fingerprint=_fingerprint(
            {
                "industry_by_ticker": industry_by_ticker,
                "industry_day_pct": industry_day_pct,
            }
        ),
        security_fingerprint=_fingerprint(
            {"security_status_by_ticker": security_status_by_ticker}
        ),
        board_rule_version="ashare-board-prefix-v1",
        normalization_version="pit-canonical-v1",
        signal_session_policy_version=SIGNAL_SESSION_POLICY_VERSION,
    )


def _refresh_result(tickers: tuple[str, ...] = ("000001",)) -> DailyActionRefreshResult:
    evidence = {
        ticker: TickerRefreshOutcome(
            ticker=ticker,
            price_status=PriceStatus.CURRENT,
            price_history_rows=35,
            fund_flow_status=FundFlowStatus.CURRENT,
            fund_flow_history_rows=20,
            evidence_fingerprints={
                "price": _fingerprint({"price": ticker}),
                "fund_flow": _fingerprint({"fund_flow": ticker}),
            },
        )
        for ticker in tickers
    }
    suspension_fingerprint = canonical_fingerprint("suspension", "*", [])
    return DailyActionRefreshResult(
        trade_date=SIGNAL_DATE,
        universe_tickers=tickers,
        universe_fingerprint=universe_fingerprint(tickers),
        daily_batch_fingerprint=_fingerprint({"daily_batch": "20260713"}),
        suspension_evidence=SuspensionEvidence.available(
            SIGNAL_DATE,
            set(),
            source_fingerprint=suspension_fingerprint,
        ),
        outcomes=evidence,
        stats=derive_stats_from_outcomes(evidence),
    )


@pytest.fixture
def valid_manifest():
    result = _refresh_result()
    return build_daily_action_readiness(
        result,
        _shared_evidence(result.universe_tickers),
        run_id="run-test-001",
    )


@pytest.fixture
def valid_manifest_dict(valid_manifest) -> dict[str, object]:
    return valid_manifest.to_dict()


def test_v2_rejects_string_booleans(valid_manifest_dict):
    raw = copy.deepcopy(valid_manifest_dict)
    raw["ticker_readiness"]["000001"]["capabilities"]["btst_breakout"][  # type: ignore[index]
        "plan_eligible"
    ] = "false"
    _resign(raw)
    with pytest.raises(ManifestValidationError, match="plan_eligible"):
        parse_manifest_v2(raw)


def test_v2_rejects_unknown_policy_and_forged_universe(valid_manifest_dict):
    unknown_policy = copy.deepcopy(valid_manifest_dict)
    unknown_policy["policy_versions"]["setup_requirements"] = "unknown"  # type: ignore[index]
    _resign(unknown_policy)
    with pytest.raises(ManifestValidationError, match="setup_requirements"):
        parse_manifest_v2(unknown_policy)

    forged_universe = copy.deepcopy(valid_manifest_dict)
    forged_universe["universe_fingerprint"] = _fingerprint({"forged": True})
    _resign(forged_universe)
    with pytest.raises(ManifestValidationError, match="universe_fingerprint"):
        parse_manifest_v2(forged_universe)


def test_v2_rejects_unknown_fields_and_capabilities(valid_manifest_dict):
    unknown_field = copy.deepcopy(valid_manifest_dict)
    unknown_field["unexpected_authority"] = True
    _resign(unknown_field)
    with pytest.raises(ManifestValidationError, match="unknown fields"):
        parse_manifest_v2(unknown_field)

    unknown_capability = copy.deepcopy(valid_manifest_dict)
    capabilities = unknown_capability["ticker_readiness"]["000001"]["capabilities"]  # type: ignore[index]
    capabilities["magic_setup"] = copy.deepcopy(capabilities["btst_breakout"])
    _resign(unknown_capability)
    with pytest.raises(ManifestValidationError, match="capabilities"):
        parse_manifest_v2(unknown_capability)


def test_v2_rejects_forged_shared_evidence_and_content(valid_manifest_dict):
    forged_evidence = copy.deepcopy(valid_manifest_dict)
    forged_evidence["shared_evidence"]["industry_day_pct"]["000001"] = 9.9  # type: ignore[index]
    _resign(forged_evidence)
    with pytest.raises(ManifestValidationError, match="industry_fingerprint"):
        parse_manifest_v2(forged_evidence)

    forged_content = copy.deepcopy(valid_manifest_dict)
    forged_content["content_fingerprint"] = _fingerprint({"forged": True})
    with pytest.raises(ManifestValidationError, match="content_fingerprint"):
        parse_manifest_v2(forged_content)


def test_v2_rejects_incomplete_or_mutable_mapping_inputs(valid_manifest_dict):
    incomplete = copy.deepcopy(valid_manifest_dict)
    incomplete["ticker_readiness"] = {}
    _resign(incomplete)
    with pytest.raises(ManifestValidationError, match="exactly cover universe"):
        parse_manifest_v2(incomplete)

    mutable = copy.deepcopy(valid_manifest_dict)
    parsed = parse_manifest_v2(mutable)
    mutable["shared_evidence"]["regime_row"]["regime"] = "crisis"  # type: ignore[index]
    mutable["ticker_readiness"]["000001"]["capabilities"]["btst_breakout"][  # type: ignore[index]
        "block_reasons"
    ].append("injected")
    assert parsed.shared_evidence.regime_row["regime"] == "normal"
    assert (
        parsed.ticker_readiness["000001"]
        .capabilities["btst_breakout"]
        .block_reasons
        == ()
    )


def test_v2_rejects_plan_eligible_contradictions(valid_manifest_dict):
    for field, value in (
        ("enabled", False),
        ("scannable", False),
        ("degraded", True),
        ("consumed_fingerprint", None),
    ):
        raw = copy.deepcopy(valid_manifest_dict)
        raw["ticker_readiness"]["000001"]["capabilities"]["btst_breakout"][  # type: ignore[index]
            field
        ] = value
        _resign(raw)
        with pytest.raises(ManifestValidationError, match="plan_eligible"):
            parse_manifest_v2(raw)


def test_v2_rejects_duplicate_and_unsorted_universe(valid_manifest_dict):
    duplicate = copy.deepcopy(valid_manifest_dict)
    duplicate["universe_tickers"] = ["000001", "000001"]
    _resign(duplicate)
    with pytest.raises(ManifestValidationError, match="duplicates"):
        parse_manifest_v2(duplicate)

    result = _refresh_result(("000001", "000002"))
    raw = build_daily_action_readiness(
        result,
        _shared_evidence(result.universe_tickers),
        run_id="run-test-002",
    ).to_dict()
    raw["universe_tickers"] = ["000002", "000001"]
    raw["universe_fingerprint"] = universe_fingerprint(tuple(raw["universe_tickers"]))
    _resign(raw)
    with pytest.raises(ManifestValidationError, match="sorted"):
        parse_manifest_v2(raw)


@pytest.mark.parametrize("run_id", ("../escape", "bad/name", ".hidden", "", "a" * 65))
def test_v2_rejects_unsafe_run_ids(valid_manifest_dict, run_id):
    raw = copy.deepcopy(valid_manifest_dict)
    raw["run_id"] = run_id
    _resign(raw)
    with pytest.raises(ManifestValidationError, match="run_id"):
        parse_manifest_v2(raw)


def test_refresh_failure_writes_attempt_and_preserves_canonical(tmp_path: Path):
    canonical = tmp_path / "daily_action_readiness_20260713.json"
    canonical.write_bytes(b'{"existing":true}')
    publication = publish_daily_action_attempt(
        trade_date=SIGNAL_DATE,
        run_id="failed-run",
        reports_dir=tmp_path,
        reasons=("refresh_failed",),
    )
    assert canonical.read_bytes() == b'{"existing":true}'
    assert publication.artifact_path.name == (
        "daily_action_readiness_attempt_20260713_failed-run.json"
    )


def test_attempt_paths_are_unique_and_run_id_cannot_escape(tmp_path: Path):
    first = publish_daily_action_attempt(
        trade_date=SIGNAL_DATE,
        run_id="failed-run",
        reports_dir=tmp_path,
        reasons=("refresh_failed",),
    )
    second = publish_daily_action_attempt(
        trade_date=SIGNAL_DATE,
        run_id="failed-run",
        reports_dir=tmp_path,
        reasons=("refresh_failed",),
    )
    assert first.artifact_path != second.artifact_path
    assert first.artifact_path.parent == tmp_path
    assert second.artifact_path.parent == tmp_path
    with pytest.raises(ManifestValidationError, match="run_id"):
        publish_daily_action_attempt(
            trade_date=SIGNAL_DATE,
            run_id="../../escape",
            reports_dir=tmp_path,
            reasons=("refresh_failed",),
        )


def test_attempt_reason_never_replaces_existing_canonical(tmp_path: Path, valid_manifest):
    canonical = tmp_path / "daily_action_readiness_20260713.json"
    canonical.write_bytes(b'{"existing":true}')
    publication = publish_daily_action_readiness(
        valid_manifest,
        tmp_path,
        attempt_reason="shared_evidence_unavailable",
    )
    assert publication.status == "degraded"
    assert "attempt" in publication.artifact_path.name
    assert canonical.read_bytes() == b'{"existing":true}'


def test_degraded_manifest_cannot_replace_canonical(tmp_path: Path, valid_manifest):
    canonical = tmp_path / "daily_action_readiness_20260713.json"
    canonical.write_bytes(b'{"existing":true}')
    degraded = replace(valid_manifest, status="degraded")
    publication = publish_daily_action_readiness(degraded, tmp_path)
    assert publication.status == "degraded"
    assert "attempt" in publication.artifact_path.name
    assert canonical.read_bytes() == b'{"existing":true}'


def test_invalid_manifest_run_id_is_quarantined_to_safe_attempt_path(
    tmp_path: Path,
    valid_manifest,
):
    canonical = tmp_path / "daily_action_readiness_20260713.json"
    canonical.write_bytes(b'{"existing":true}')
    unsafe = replace(valid_manifest, run_id="../../escape")
    publication = publish_daily_action_readiness(unsafe, tmp_path)
    assert publication.status == "degraded"
    assert publication.artifact_path.parent == tmp_path
    assert ".." not in publication.artifact_path.name
    assert canonical.read_bytes() == b'{"existing":true}'


def test_canonical_replace_failure_writes_attempt_and_preserves_bytes(
    tmp_path: Path,
    valid_manifest,
    monkeypatch,
):
    import src.screening.offensive.daily_action_readiness as module

    canonical = tmp_path / "daily_action_readiness_20260713.json"
    canonical.write_bytes(b'{"existing":true}')
    real_replace = module.os.replace

    def fail_canonical(source, target):
        if Path(target).name == canonical.name:
            raise OSError("replace denied")
        return real_replace(source, target)

    monkeypatch.setattr(module.os, "replace", fail_canonical)
    publication = publish_daily_action_readiness(valid_manifest, tmp_path)
    assert publication.status == "fatal"
    assert "attempt" in publication.artifact_path.name
    assert canonical.read_bytes() == b'{"existing":true}'
