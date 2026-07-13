"""Per-ticker evidence describing whether cached data is trade ready."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType
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

    def __post_init__(self) -> None:
        snapshot = dict(self.tickers)
        for key, readiness in snapshot.items():
            if not isinstance(readiness, TickerReadiness):
                raise TypeError("tickers values must be TickerReadiness instances")
            if type(key) is not str or not key.strip() or key != readiness.ticker:
                raise ValueError("ticker key must be a nonempty string matching TickerReadiness.ticker")
        object.__setattr__(self, "tickers", MappingProxyType(snapshot))


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
    if type(ticker) is not str or not ticker.strip():
        raise ValueError("ticker must be a nonempty string")
    if type(trade_date) is not date:
        raise ValueError("trade_date must be a plain date")

    reasons: list[str] = []

    if type(ohlcv_date) is not date or ohlcv_date != trade_date:
        reasons.append(f"ohlcv_date:{ohlcv_date!s}!={trade_date!s}")
    if ohlcv_finite is not True:
        reasons.append("ohlcv:nonfinite")
    if type(fund_flow_date) is not date or fund_flow_date != trade_date:
        reasons.append(f"fund_flow_date:{fund_flow_date!s}!={trade_date!s}")
    history_is_valid = type(fund_flow_history_days) is int and fund_flow_history_days >= 0
    if not history_is_valid:
        reasons.append("fund_flow_history:unknown<20")
    elif fund_flow_history_days < 20:
        reasons.append(f"fund_flow_history:{fund_flow_history_days}<20")
    if type(industry_date) is not date or industry_date != trade_date:
        reasons.append(f"industry_date:{industry_date!s}!={trade_date!s}")
    normalized_security_status = security_status.strip() if type(security_status) is str else ""
    if normalized_security_status != "listed":
        reasons.append(f"security_status:{normalized_security_status or 'unknown'}")
    if type(st_status) is not bool:
        reasons.append("st_status:unknown")
    elif st_status:
        reasons.append("st_status:st")
    if type(board_rule_version) is not str or not board_rule_version.strip():
        reasons.append("board_rule_version:unknown")
    if type(cache_fingerprint) is not str or not cache_fingerprint.strip():
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
