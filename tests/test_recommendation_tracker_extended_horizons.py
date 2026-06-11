"""P5-1 扩展追踪周期 (T+10/T+20/T+30) — 回归测试。

验证 update_tracking_history 正确填充 day_10/day_20/day_30 字段。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.screening.recommendation_tracker import (
    DEFAULT_HORIZONS,
    HISTORY_FILENAME,
    _load_history,
    fetch_actual_returns,
    update_tracking_history,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _make_report(reports_dir: Path, date_str: str, recs: list[dict]) -> Path:
    """写入一个 auto_screening_{date}.json 报告。"""
    path = reports_dir / f"auto_screening_{date_str}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": "auto_screening",
        "date": date_str,
        "recommendations": recs,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return path


def _make_price_series(ticker: str, prices: list[tuple[str, float]]) -> list[dict]:
    """构造 fetcher 返回的原始数据。"""
    return [{"ticker": ticker, "time": date, "close": close} for date, close in prices]


def _mock_fetcher_map(mapping: dict[str, list[tuple[str, float]]]):
    """根据 mapping 构造 fetcher 函数。"""

    def fetcher(ticker: str, start_date: str, end_date: str):
        return _make_price_series(ticker, mapping.get(ticker, []))

    return fetcher


# ---------------------------------------------------------------------------
# 1. DEFAULT_HORIZONS 应该包含扩展周期
# ---------------------------------------------------------------------------


def test_default_horizons_includes_extended():
    """DEFAULT_HORIZONS 必须包含 T+10, T+20, T+30。"""
    assert DEFAULT_HORIZONS == (1, 3, 5, 10, 20, 30)


# ---------------------------------------------------------------------------
# 2. fetch_actual_returns 应该返回 T+10/T+20/T+30
# ---------------------------------------------------------------------------


def test_fetch_actual_returns_computes_day10():
    """验证 fetch_actual_returns 计算 T+10 收益。"""
    prices = [("2026-06-01", 10.0)]
    prices += [(f"2026-06-{i:02d}", 10.0) for i in range(2, 11)]
    prices.append(("2026-06-11", 12.0))  # T+10 = +20%
    mapping = {"000001": prices}
    fetcher = _mock_fetcher_map(mapping)

    result = fetch_actual_returns(["000001"], "20260601", "20260615", use_data_fetcher=fetcher)

    assert "000001" in result
    assert "day_10" in result["000001"]
    assert result["000001"]["day_10"] == pytest.approx(20.0, rel=1e-4)


def test_fetch_actual_returns_computes_day20():
    """验证 fetch_actual_returns 计算 T+20 收益。"""
    prices = []
    for i in range(1, 22):  # T+0 到 T+20 共 21 个交易日
        prices.append((f"2026-06-{i:02d}", 10.0))
    prices[20] = ("2026-06-21", 11.0)  # T+20 = +10%
    mapping = {"000002": prices}
    fetcher = _mock_fetcher_map(mapping)

    result = fetch_actual_returns(["000002"], "20260601", "20260625", use_data_fetcher=fetcher)

    assert "000002" in result
    assert "day_20" in result["000002"]
    assert result["000002"]["day_20"] == pytest.approx(10.0, rel=1e-4)


def test_fetch_actual_returns_computes_day30():
    """验证 fetch_actual_returns 计算 T+30 收益。"""
    prices = []
    for day in range(1, 32):  # T+0 到 T+30 共 31 个交易日
        month = 6 if day <= 30 else 7
        day_in_month = day if day <= 30 else day - 30
        prices.append((f"2026-{month:02d}-{day_in_month:02d}", 10.0))
    prices[30] = ("2026-07-01", 13.0)  # T+30 = +30%
    mapping = {"000003": prices}
    fetcher = _mock_fetcher_map(mapping)

    result = fetch_actual_returns(["000003"], "20260601", "20260710", use_data_fetcher=fetcher)

    assert "000003" in result
    assert "day_30" in result["000003"]
    assert result["000003"]["day_30"] == pytest.approx(30.0, rel=1e-4)


# ---------------------------------------------------------------------------
# 3. fetch_actual_returns 扩展窗口应足够覆盖 T+30
# ---------------------------------------------------------------------------


def test_fetch_actual_returns_extends_window_for_t30():
    """验证 fetch_actual_returns 拉取窗口至少延长 45 天 (容纳 T+30 交易日)。"""
    # 构造 31 个交易日的数据 (T+0 到 T+30)
    prices = []
    for i in range(1, 32):  # 06-01 到 07-01 (31 个交易日)
        month = 6 if i <= 30 else 7
        day = i if i <= 30 else i - 30
        prices.append((f"2026-{month:02d}-{day:02d}", 10.0))
    prices[30] = ("2026-07-01", 12.0)  # T+30 = +20%

    # 模拟 fetcher: 只有在请求窗口足够时才返回完整数据
    def strict_fetcher(ticker: str, start_date: str, end_date: str):
        # end_date 应该 >= "20260716" (6/1 + 45 天)
        if end_date >= "20260716":
            return _make_price_series(ticker, prices)
        # 窗口不够, 只返回部分数据 (无 T+30)
        return _make_price_series(ticker, prices[:20])

    result = fetch_actual_returns(["000004"], "20260601", "20260601", use_data_fetcher=strict_fetcher)

    # 如果窗口扩展正确, 应该能拿到 T+30
    assert "000004" in result
    assert "day_30" in result["000004"]
    assert result["000004"]["day_30"] == pytest.approx(20.0, rel=1e-4)


# ---------------------------------------------------------------------------
# 4. update_tracking_history 应该填充扩展字段
# ---------------------------------------------------------------------------


def test_update_tracking_history_populates_day10_day20_day30(tmp_path: Path):
    """核心回归: update_tracking_history 应正确填充 next_10day_return / next_20day_return / next_30day_return。"""
    # Phase 1: 注册推荐
    _make_report(
        tmp_path,
        "20260601",
        [
            {"ticker": "000888", "name": "ExtendedTest", "score_b": 0.6, "close": 100.0},
        ],
    )
    update_tracking_history(tmp_path, "20260601")

    # Phase 2: 构造 T+0 到 T+30 的价格数据 (31 个交易日)
    prices = []
    for i in range(1, 32):  # 06-01 到 07-01 共 31 天
        month = 6 if i <= 30 else 7
        day = i if i <= 30 else i - 30
        prices.append((f"2026-{month:02d}-{day:02d}", 100.0))
    # T+10 = 110.0 (+10%), T+20 = 120.0 (+20%), T+30 = 130.0 (+30%)
    prices[10] = ("2026-06-11", 110.0)
    prices[20] = ("2026-06-21", 120.0)
    prices[30] = ("2026-07-01", 130.0)

    mapping = {"000888": prices}
    fetcher = _mock_fetcher_map(mapping)

    # Phase 3: 在足够晚的日期 (T+35) 触发收益拉取
    n = update_tracking_history(tmp_path, "20260706", use_data_fetcher=fetcher)
    assert n >= 1

    # Phase 4: 验证历史记录包含扩展字段
    history = _load_history(tmp_path / HISTORY_FILENAME)
    assert len(history) == 1
    rec = history[0]
    assert rec["ticker"] == "000888"
    assert rec["next_10day_return"] is not None
    assert rec["next_10day_return"] == pytest.approx(10.0, rel=1e-4)
    assert rec["next_20day_return"] is not None
    assert rec["next_20day_return"] == pytest.approx(20.0, rel=1e-4)
    assert rec["next_30day_return"] is not None
    assert rec["next_30day_return"] == pytest.approx(30.0, rel=1e-4)


# ---------------------------------------------------------------------------
# 5. tracking_status 不应过早标记 complete
# ---------------------------------------------------------------------------


def test_tracking_status_not_complete_until_t30(tmp_path: Path):
    """验证 tracking_status 只有在 T+30 可用时才标记 complete。"""
    # Phase 1: 注册推荐
    _make_report(
        tmp_path,
        "20260601",
        [
            {"ticker": "000999", "name": "LateComplete", "score_b": 0.7, "close": 50.0},
        ],
    )
    update_tracking_history(tmp_path, "20260601")

    # Phase 2: 只提供 T+0 到 T+5 的数据 (6 个交易日, 无 T+10/T+20/T+30)
    prices = []
    for i in range(1, 7):  # 06-01 到 06-06 (6 个交易日)
        prices.append((f"2026-06-{i:02d}", 50.0))
    prices[5] = ("2026-06-06", 55.0)  # T+5 = +10%
    mapping = {"000999": prices}
    fetcher = _mock_fetcher_map(mapping)

    # Phase 3: 在 T+6 触发收益拉取
    update_tracking_history(tmp_path, "20260607", use_data_fetcher=fetcher)

    # Phase 4: tracking_status 应该是 "partial" (有 T+5, 但没有 T+30)
    history = _load_history(tmp_path / HISTORY_FILENAME)
    rec = history[0]
    assert rec["tracking_status"] == "partial"
    assert rec["next_5day_return"] == pytest.approx(10.0, rel=1e-4)
    assert rec["next_10day_return"] is None
    assert rec["next_30day_return"] is None

    # Phase 5: 现在提供完整 T+0 到 T+30 数据 (31 个交易日)
    full_prices = []
    for i in range(1, 32):
        month = 6 if i <= 30 else 7
        day = i if i <= 30 else i - 30
        full_prices.append((f"2026-{month:02d}-{day:02d}", 50.0))
    full_prices[5] = ("2026-06-06", 55.0)  # T+5 = +10%
    full_prices[30] = ("2026-07-01", 65.0)  # T+30 = +30%
    mapping["000999"] = full_prices
    fetcher2 = _mock_fetcher_map(mapping)

    # Phase 6: 在 T+35 触发收益拉取
    update_tracking_history(tmp_path, "20260706", use_data_fetcher=fetcher2)

    # Phase 7: 现在 tracking_status 应该是 "complete"
    history = _load_history(tmp_path / HISTORY_FILENAME)
    rec = history[0]
    assert rec["tracking_status"] == "complete"
    assert rec["next_30day_return"] == pytest.approx(30.0, rel=1e-4)
