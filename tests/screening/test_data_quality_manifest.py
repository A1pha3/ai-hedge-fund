from datetime import date

from src.screening.data_quality_manifest import validate_ticker_readiness


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
