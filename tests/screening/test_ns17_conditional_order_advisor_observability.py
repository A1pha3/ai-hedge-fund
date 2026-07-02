"""NS-17/BH-017 同族 — conditional_order_advisor.py price_provider 静默退化 observability.

AutoDev C10/Loop 11 (c280): drains 2 silent except patterns in
conditional_order_advisor.py price_provider calls.

Drain pattern (WARNING — 决策链, 止损/止盈建议, 触及风控数据质量):
- attach_conditional_orders_to_payload (L504, API path)
- run_conditional_orders_cli (L615, CLI path)

Previous behavior: price_provider raise → silent `history = []` → compute_conditional_advice
degraded advice but operator 不知是数据缺失还是 provider 异常.
Drained behavior: emit WARNING with ticker + lookback + exc, then `history = []`
(best-effort preserved).

Tests verify:
1. price_provider raise → WARNING emitted with ticker context
2. best-effort preserved (no crash, returns degraded advice / empty history)
3. Success path: no WARNING emitted
"""

from __future__ import annotations

import logging
from typing import Any


# ---------------------------------------------------------------------------
# API path: attach_conditional_orders_to_payload (L504)
# ---------------------------------------------------------------------------


def _make_payload(ticker: str = "TEST001") -> dict[str, Any]:
    """构造单标的 payload (含 current_price 让 degraded 由数据不足触发)."""
    return {
        "recommendations": [
            {
                "ticker": ticker,
                "current_price": 100.0,
                "name": f"Test Stock {ticker}",
            }
        ]
    }


def _boom_provider(ticker: str, n: int) -> list[float]:
    """Price provider that always raises — simulates 数据源异常 / 网络中断 / 解析错误."""
    raise RuntimeError(f"price_provider boom for {ticker} (n={n})")


def test_api_path_price_provider_failure_emits_warning(caplog) -> None:
    """L504 API path: price_provider raise → WARNING with ticker + lookback context.

    Best-effort preserved (history=[] → degraded advice), but now observable.
    """
    from src.screening.conditional_order_advisor import attach_conditional_orders_to_payload

    payload = _make_payload(ticker="APIFAIL")
    with caplog.at_level(logging.WARNING, logger="src.screening.conditional_order_advisor"):
        results = attach_conditional_orders_to_payload(
            payload=payload,
            price_provider=_boom_provider,
            lookback_sessions=30,
        )
    # best-effort: 不抛异常, 返回 1 条 degraded advice
    assert len(results) == 1
    advice = results[0]
    assert advice["degraded"] is True, (
        f"price_provider 失败 → history=[] → degraded advice; 实际 degraded={advice['degraded']}"
    )
    # WARNING 发出, 含 ticker + lookback + exc
    warn_records = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING
        and "price_provider failed" in r.getMessage()
        and "ticker=APIFAIL" in r.getMessage()
        and "lookback=30" in r.getMessage()
    ]
    assert len(warn_records) == 1, (
        f"expected 1 WARNING for API path price_provider failure, got {warn_records}"
    )
    # exc_info 不强制要求 (warning 文本已含 exc str)


def test_api_path_price_provider_success_no_warning(caplog) -> None:
    """L504 API path: 正常路径不应发 WARNING."""
    from src.screening.conditional_order_advisor import attach_conditional_orders_to_payload

    def _good_provider(ticker: str, n: int) -> list[float]:
        return [100.0 + i * 0.5 for i in range(n)]

    payload = _make_payload(ticker="OK001")
    with caplog.at_level(logging.WARNING, logger="src.screening.conditional_order_advisor"):
        results = attach_conditional_orders_to_payload(
            payload=payload,
            price_provider=_good_provider,
            lookback_sessions=30,
        )
    assert len(results) == 1
    # 正常路径不应发 WARNING
    warn_records = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "price_provider failed" in r.getMessage()
    ]
    assert len(warn_records) == 0, f"success path should not emit WARNING, got {warn_records}"


def test_api_path_warning_distinguishes_ticker(caplog) -> None:
    """L504 API path: WARNING 必须含具体 ticker 以便 operator 定位.

    多标的时, 单个标的的 provider 失败不应被其他标的的成功掩盖.
    """
    from src.screening.conditional_order_advisor import attach_conditional_orders_to_payload

    def _mixed_provider(ticker: str, n: int) -> list[float]:
        if ticker == "BADTICKER":
            raise ConnectionError("upstream feed down")
        return [100.0 + i * 0.5 for i in range(n)]

    payload = {
        "recommendations": [
            {"ticker": "GOODTICKER", "current_price": 100.0, "name": "Good"},
            {"ticker": "BADTICKER", "current_price": 100.0, "name": "Bad"},
        ]
    }
    with caplog.at_level(logging.WARNING, logger="src.screening.conditional_order_advisor"):
        results = attach_conditional_orders_to_payload(
            payload=payload,
            price_provider=_mixed_provider,
            lookback_sessions=20,
        )
    # 两条都返回 (best-effort)
    assert len(results) == 2
    # BADTICKER 应有 WARNING, GOODTICKER 不应有
    bad_warns = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "ticker=BADTICKER" in r.getMessage()
    ]
    good_warns = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "ticker=GOODTICKER" in r.getMessage()
    ]
    assert len(bad_warns) == 1, f"BADTICKER should emit WARNING, got {bad_warns}"
    assert len(good_warns) == 0, f"GOODTICKER should not emit WARNING, got {good_warns}"


# ---------------------------------------------------------------------------
# CLI path: run_conditional_orders_cli (L615)
# ---------------------------------------------------------------------------


def test_cli_path_price_provider_failure_emits_warning(
    caplog, monkeypatch
) -> None:
    """L615 CLI path: price_provider raise → WARNING with "(CLI)" prefix + ticker.

    Best-effort preserved (history=[] → degraded advice, CLI 仍输出).
    """
    from src.screening.conditional_order_advisor import run_conditional_orders_cli

    # Mock load_latest_recommendations 返回单标的, 避免依赖报告文件
    def _fake_recs(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"ticker": "CLIFAIL", "current_price": 100.0, "name": "CLI Test"}]

    monkeypatch.setattr(
        "src.screening.compare_tool.load_latest_recommendations",
        _fake_recs,
    )

    with caplog.at_level(logging.WARNING, logger="src.screening.conditional_order_advisor"):
        rc = run_conditional_orders_cli(
            top_n=5,
            price_provider=_boom_provider,
            lookback_sessions=30,
        )
    # CLI 返回 0 (成功, 虽然是 degraded advice)
    assert rc == 0, f"CLI should return 0 on best-effort degraded advice, got {rc}"
    # WARNING 发出, 含 "(CLI)" prefix + ticker
    warn_records = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING
        and "(CLI)" in r.getMessage()
        and "price_provider failed" in r.getMessage()
        and "ticker=CLIFAIL" in r.getMessage()
        and "lookback=30" in r.getMessage()
    ]
    assert len(warn_records) == 1, (
        f"expected 1 WARNING for CLI path price_provider failure with (CLI) prefix, "
        f"got {warn_records}"
    )


def test_cli_path_price_provider_success_no_warning(caplog, monkeypatch) -> None:
    """L615 CLI path: 正常路径不应发 WARNING."""
    from src.screening.conditional_order_advisor import run_conditional_orders_cli

    def _good_provider(ticker: str, n: int) -> list[float]:
        return [100.0 + i * 0.5 for i in range(n)]

    def _fake_recs(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"ticker": "CLIOK", "current_price": 100.0, "name": "CLI OK"}]

    monkeypatch.setattr(
        "src.screening.compare_tool.load_latest_recommendations",
        _fake_recs,
    )

    with caplog.at_level(logging.WARNING, logger="src.screening.conditional_order_advisor"):
        rc = run_conditional_orders_cli(
            top_n=5,
            price_provider=_good_provider,
            lookback_sessions=30,
        )
    assert rc == 0
    warn_records = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "price_provider failed" in r.getMessage()
    ]
    assert len(warn_records) == 0, f"success path should not emit WARNING, got {warn_records}"
