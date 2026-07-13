"""Per-ticker evidence describing whether cached data is trade ready."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Mapping


@dataclass(frozen=True)
class TickerReadiness:
    ticker: str
    trade_date: date
    ohlcv_date: date | None
    ohlcv_finite: bool
    fund_flow_date: date | None
    fund_flow_history_days: int
    industry_date: date | None
    security_status: str | None
    st_status: bool | None
    board_rule_version: str | None
    cache_fingerprint: str | None
    trade_ready: bool
    block_reasons: tuple[str, ...]


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    trade_date: date
    status: str
    created_at: datetime
    tickers: Mapping[str, TickerReadiness]


def validate_ticker_readiness(
    *,
    ticker: str,
    trade_date: date,
    ohlcv_date: date | None,
    ohlcv_finite: bool,
    fund_flow_date: date | None,
    fund_flow_history_days: int,
    industry_date: date | None,
    security_status: str | None,
    st_status: bool | None,
    board_rule_version: str | None,
    cache_fingerprint: str | None,
) -> TickerReadiness:
    """Validate one ticker, failing closed when required evidence is absent."""
    reasons: list[str] = []

    if ohlcv_date != trade_date:
        reasons.append(f"ohlcv_date:{ohlcv_date!s}!={trade_date!s}")
    if not ohlcv_finite:
        reasons.append("ohlcv:nonfinite")
    if fund_flow_date != trade_date:
        reasons.append(f"fund_flow_date:{fund_flow_date!s}!={trade_date!s}")
    if fund_flow_history_days < 20:
        reasons.append(f"fund_flow_history:{fund_flow_history_days}<20")
    if industry_date != trade_date:
        reasons.append(f"industry_date:{industry_date!s}!={trade_date!s}")
    if security_status != "listed":
        reasons.append(f"security_status:{security_status or 'unknown'}")
    if st_status is None:
        reasons.append("st_status:unknown")
    elif st_status:
        reasons.append("st_status:st")
    if not board_rule_version:
        reasons.append("board_rule_version:unknown")
    if not cache_fingerprint:
        reasons.append("cache_fingerprint:missing")

    block_reasons = tuple(reasons)
    return TickerReadiness(
        ticker=ticker,
        trade_date=trade_date,
        ohlcv_date=ohlcv_date,
        ohlcv_finite=ohlcv_finite,
        fund_flow_date=fund_flow_date,
        fund_flow_history_days=fund_flow_history_days,
        industry_date=industry_date,
        security_status=security_status,
        st_status=st_status,
        board_rule_version=board_rule_version,
        cache_fingerprint=cache_fingerprint,
        trade_ready=not block_reasons,
        block_reasons=block_reasons,
    )
