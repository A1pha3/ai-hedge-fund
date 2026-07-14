from dataclasses import FrozenInstanceError
from datetime import date, datetime
from types import MappingProxyType
from typing import Any

import pytest

from src.screening.data_quality_manifest import RunManifest, TickerReadiness, validate_ticker_readiness


TRADE_DATE = date(2026, 7, 10)


def _valid_inputs() -> dict[str, Any]:
    return {
        "ticker": "000001",
        "trade_date": TRADE_DATE,
        "ohlcv_date": TRADE_DATE,
        "ohlcv_finite": True,
        "fund_flow_date": TRADE_DATE,
        "fund_flow_history_days": 20,
        "industry_date": TRADE_DATE,
        "security_status": "listed",
        "st_status": False,
        "board_rule_version": "sse-szse-202607",
        "cache_fingerprint": "sha256:abc",
    }


def test_complete_btst_ticker_is_trade_ready() -> None:
    result = validate_ticker_readiness(
        ticker="000001",
        trade_date=date(2026, 7, 10),
        ohlcv_date=date(2026, 7, 10),
        ohlcv_finite=True,
        fund_flow_date=date(2026, 7, 10),
        fund_flow_history_days=20,
        industry_date=date(2026, 7, 10),
        security_status="listed",
        st_status=False,
        board_rule_version="sse-szse-202607",
        cache_fingerprint="sha256:abc",
    )
    assert result.trade_ready is True
    assert result.block_reasons == ()


def test_short_fund_flow_history_blocks_trade() -> None:
    result = validate_ticker_readiness(
        ticker="000001",
        trade_date=date(2026, 7, 10),
        ohlcv_date=date(2026, 7, 10),
        ohlcv_finite=True,
        fund_flow_date=date(2026, 7, 10),
        fund_flow_history_days=4,
        industry_date=date(2026, 7, 10),
        security_status="listed",
        st_status=False,
        board_rule_version="sse-szse-202607",
        cache_fingerprint="sha256:abc",
    )
    assert result.trade_ready is False
    assert result.block_reasons == ("fund_flow_history:4<20",)


def test_unknown_st_status_fails_closed() -> None:
    result = validate_ticker_readiness(
        ticker="000001",
        trade_date=date(2026, 7, 10),
        ohlcv_date=date(2026, 7, 10),
        ohlcv_finite=True,
        fund_flow_date=date(2026, 7, 10),
        fund_flow_history_days=20,
        industry_date=date(2026, 7, 10),
        security_status="listed",
        st_status=None,
        board_rule_version="sse-szse-202607",
        cache_fingerprint="sha256:abc",
    )
    assert "st_status:unknown" in result.block_reasons


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("ohlcv_date", None, "ohlcv_date:None!=2026-07-10"),
        ("ohlcv_date", "2026-07-10", "ohlcv_date:2026-07-10!=2026-07-10"),
        ("ohlcv_date", datetime(2026, 7, 10), "ohlcv_date:2026-07-10 00:00:00!=2026-07-10"),
        ("ohlcv_finite", False, "ohlcv:nonfinite"),
        ("ohlcv_finite", None, "ohlcv:nonfinite"),
        ("ohlcv_finite", 1, "ohlcv:nonfinite"),
        ("fund_flow_date", None, "fund_flow_date:None!=2026-07-10"),
        ("fund_flow_history_days", 19, "fund_flow_history:19<20"),
        ("fund_flow_history_days", 0, "fund_flow_history:0<20"),
        ("fund_flow_history_days", -1, "fund_flow_history:unknown<20"),
        ("fund_flow_history_days", True, "fund_flow_history:unknown<20"),
        ("fund_flow_history_days", 20.0, "fund_flow_history:unknown<20"),
        ("fund_flow_history_days", float("nan"), "fund_flow_history:unknown<20"),
        ("fund_flow_history_days", float("inf"), "fund_flow_history:unknown<20"),
        ("fund_flow_history_days", None, "fund_flow_history:unknown<20"),
        ("fund_flow_history_days", "20", "fund_flow_history:unknown<20"),
        ("industry_date", date(2026, 7, 9), "industry_date:2026-07-09!=2026-07-10"),
        ("security_status", None, "security_status:unknown"),
        ("security_status", "", "security_status:unknown"),
        ("security_status", "   ", "security_status:unknown"),
        ("security_status", 0, "security_status:unknown"),
        ("security_status", "delisted", "security_status:delisted"),
        ("st_status", None, "st_status:unknown"),
        ("st_status", 0, "st_status:unknown"),
        ("st_status", 1, "st_status:unknown"),
        ("st_status", "false", "st_status:unknown"),
        ("st_status", True, "st_status:st"),
        ("board_rule_version", None, "board_rule_version:unknown"),
        ("board_rule_version", "", "board_rule_version:unknown"),
        ("board_rule_version", "  ", "board_rule_version:unknown"),
        ("board_rule_version", 1, "board_rule_version:unknown"),
        ("cache_fingerprint", None, "cache_fingerprint:missing"),
        ("cache_fingerprint", "", "cache_fingerprint:missing"),
        ("cache_fingerprint", "  ", "cache_fingerprint:missing"),
        ("cache_fingerprint", 1, "cache_fingerprint:missing"),
    ],
)
def test_each_invalid_evidence_field_fails_closed(field: str, value: Any, reason: str) -> None:
    inputs = _valid_inputs()
    inputs[field] = value

    result = validate_ticker_readiness(**inputs)

    assert result.trade_ready is False
    assert result.block_reasons == (reason,)


@pytest.mark.parametrize("history_days", [20, 21])
def test_fund_flow_history_integer_threshold_is_inclusive(history_days: int) -> None:
    inputs = _valid_inputs()
    inputs["fund_flow_history_days"] = history_days
    assert validate_ticker_readiness(**inputs).trade_ready is True


def test_valid_strings_are_checked_after_stripping() -> None:
    inputs = _valid_inputs()
    inputs.update(
        ticker=" 000001 ",
        security_status=" listed ",
        board_rule_version=" sse-szse-202607 ",
        cache_fingerprint=" sha256:abc ",
    )
    assert validate_ticker_readiness(**inputs).trade_ready is True


@pytest.mark.parametrize("ticker", [None, "", "   ", 1])
def test_invalid_ticker_identity_raises_value_error(ticker: Any) -> None:
    inputs = _valid_inputs()
    inputs["ticker"] = ticker
    with pytest.raises(ValueError, match="ticker must be a nonempty string"):
        validate_ticker_readiness(**inputs)


@pytest.mark.parametrize("trade_date", [None, "2026-07-10", datetime(2026, 7, 10)])
def test_invalid_trade_date_control_raises_value_error(trade_date: Any) -> None:
    inputs = _valid_inputs()
    inputs["trade_date"] = trade_date
    with pytest.raises(ValueError, match="trade_date must be a plain date"):
        validate_ticker_readiness(**inputs)


def test_multiple_block_reasons_follow_field_order() -> None:
    inputs = _valid_inputs()
    inputs.update(
        ohlcv_date=None,
        ohlcv_finite=1,
        fund_flow_date=None,
        fund_flow_history_days=float("nan"),
        industry_date=None,
        security_status=0,
        st_status=0,
        board_rule_version=" ",
        cache_fingerprint=[],
    )
    result = validate_ticker_readiness(**inputs)
    assert result.block_reasons == (
        "ohlcv_date:None!=2026-07-10",
        "ohlcv:nonfinite",
        "fund_flow_date:None!=2026-07-10",
        "fund_flow_history:unknown<20",
        "industry_date:None!=2026-07-10",
        "security_status:unknown",
        "st_status:unknown",
        "board_rule_version:unknown",
        "cache_fingerprint:missing",
    )


def test_run_manifest_defensively_copies_and_freezes_ticker_mapping() -> None:
    readiness = validate_ticker_readiness(**_valid_inputs())
    source = {readiness.ticker: readiness}
    manifest = RunManifest(
        run_id="run-1",
        trade_date=TRADE_DATE,
        status="complete",
        created_at=datetime(2026, 7, 10, 16),
        tickers=source,
    )
    source.clear()

    assert isinstance(manifest.tickers, MappingProxyType)
    assert manifest.tickers == {"000001": readiness}
    with pytest.raises(TypeError):
        manifest.tickers["000002"] = readiness  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        readiness.trade_ready = False  # type: ignore[misc]


def test_run_manifest_rejects_mutable_or_wrong_ticker_values() -> None:
    with pytest.raises(TypeError, match="TickerReadiness"):
        RunManifest(
            run_id="run-1",
            trade_date=TRADE_DATE,
            status="complete",
            created_at=datetime(2026, 7, 10, 16),
            tickers={"000001": object()},  # type: ignore[dict-item]
        )


@pytest.mark.parametrize("key", [None, 1, "", "   ", "000002"])
def test_run_manifest_rejects_invalid_or_mismatched_ticker_keys(key: Any) -> None:
    readiness = validate_ticker_readiness(**_valid_inputs())
    with pytest.raises(ValueError, match="ticker key"):
        RunManifest(
            run_id="run-1",
            trade_date=TRADE_DATE,
            status="complete",
            created_at=datetime(2026, 7, 10, 16),
            tickers={key: readiness},
        )


def test_string_subclasses_fail_exact_type_validation() -> None:
    class StringSubclass(str):
        pass

    inputs = _valid_inputs()
    inputs["ticker"] = StringSubclass("000001")
    with pytest.raises(ValueError, match="ticker must be a nonempty string"):
        validate_ticker_readiness(**inputs)

    inputs = _valid_inputs()
    inputs.update(
        security_status=StringSubclass("listed"),
        board_rule_version=StringSubclass("sse-szse-202607"),
        cache_fingerprint=StringSubclass("sha256:abc"),
    )
    assert validate_ticker_readiness(**inputs).block_reasons == (
        "security_status:unknown",
        "board_rule_version:unknown",
        "cache_fingerprint:missing",
    )


def test_run_manifest_rejects_string_subclass_ticker_key() -> None:
    class StringSubclass(str):
        pass

    readiness = validate_ticker_readiness(**_valid_inputs())
    with pytest.raises(ValueError, match="ticker key"):
        RunManifest(
            run_id="run-1",
            trade_date=TRADE_DATE,
            status="complete",
            created_at=datetime(2026, 7, 10, 16),
            tickers={StringSubclass("000001"): readiness},
        )
