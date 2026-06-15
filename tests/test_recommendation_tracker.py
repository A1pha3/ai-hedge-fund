"""P1-3 推荐标的自动追踪 — 单元测试。

所有外部数据获取 (akshare / tushare) 全部 mock。
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from src.screening.recommendation_tracker import (
    _coerce_recommended_price,
    _extract_sorted_closes,
    _load_history,
    _optional_float,
    _parse_date,
    _record_key,
    _safe_float,
    _save_history,
    _summarize_history,
    DEFAULT_HORIZONS,
    fetch_actual_returns,
    get_tracking_summary,
    HISTORY_FILENAME,
    load_pending_recommendations,
    render_tracking_summary,
    TrackingRecord,
    update_tracking_history,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_report(
    reports_dir: Path,
    date_str: str,
    recs: list[dict],
) -> Path:
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


def _make_price_series(
    ticker: str,
    prices: list[tuple[str, float]],
) -> list[dict]:
    """构造 fetcher 返回的原始数据。"""
    return [{"ticker": ticker, "time": date, "close": close} for date, close in prices]


def _mock_fetcher_map(
    mapping: dict[str, list[tuple[str, float]]],
):
    """根据 mapping 构造 fetcher 函数。"""
    def fetcher(ticker: str, start_date: str, end_date: str):
        return _make_price_series(ticker, mapping.get(ticker, []))
    return fetcher


# ---------------------------------------------------------------------------
# 1. 加载空报告 → 空列表
# ---------------------------------------------------------------------------


def test_load_pending_no_report_returns_empty(tmp_path: Path):
    assert load_pending_recommendations(tmp_path, "20260607") == []


def test_load_pending_invalid_date_returns_empty(tmp_path: Path):
    assert load_pending_recommendations(tmp_path, "invalid") == []


# ---------------------------------------------------------------------------
# 2. 加载有报告 → 正确解析 Top N
# ---------------------------------------------------------------------------


def test_load_pending_parses_top_n(tmp_path: Path):
    recs = [
        {"ticker": "000001", "name": "PingAn", "score_b": 0.65, "close": 12.5},
        {"ticker": "000002", "name": "Vanke", "score_b": 0.55, "close": 8.3},
    ]
    _make_report(tmp_path, "20260607", recs)
    loaded = load_pending_recommendations(tmp_path, "20260607")
    assert len(loaded) == 2
    assert loaded[0]["ticker"] == "000001"
    assert loaded[0]["name"] == "PingAn"


# ---------------------------------------------------------------------------
# 3. T+1 收益计算正确
# ---------------------------------------------------------------------------


def test_fetch_actual_returns_day1_correct(tmp_path: Path):
    mapping = {
        "000001": [
            ("2026-06-07", 10.0),
            ("2026-06-08", 10.5),  # T+1 = +5.0%
        ]
    }
    fetcher = _mock_fetcher_map(mapping)
    result = fetch_actual_returns(["000001"], "20260607", "20260613", use_data_fetcher=fetcher)
    assert "000001" in result
    assert result["000001"]["day_1"] == pytest.approx(5.0, rel=1e-4)


# ---------------------------------------------------------------------------
# 4. T+3 收益计算正确
# ---------------------------------------------------------------------------


def test_fetch_actual_returns_day3_correct(tmp_path: Path):
    mapping = {
        "000002": [
            ("2026-06-07", 20.0),
            ("2026-06-08", 20.5),
            ("2026-06-09", 20.0),
            ("2026-06-10", 21.0),  # T+3 = +5.0%
        ]
    }
    fetcher = _mock_fetcher_map(mapping)
    result = fetch_actual_returns(["000002"], "20260607", "20260613", use_data_fetcher=fetcher)
    assert result["000002"]["day_3"] == pytest.approx(5.0, rel=1e-4)


# ---------------------------------------------------------------------------
# 5. T+5 收益计算正确
# ---------------------------------------------------------------------------


def test_fetch_actual_returns_day5_correct(tmp_path: Path):
    mapping = {
        "000003": [
            ("2026-06-07", 10.0),
            ("2026-06-08", 10.0),
            ("2026-06-09", 10.0),
            ("2026-06-10", 10.0),
            ("2026-06-11", 10.0),
            ("2026-06-12", 11.0),  # T+5 = +10.0%
        ]
    }
    fetcher = _mock_fetcher_map(mapping)
    result = fetch_actual_returns(["000003"], "20260607", "20260613", use_data_fetcher=fetcher)
    assert result["000003"]["day_5"] == pytest.approx(10.0, rel=1e-4)


# ---------------------------------------------------------------------------
# 6. 价格缺失 → None 而非 crash
# ---------------------------------------------------------------------------


def test_fetch_actual_returns_missing_prices_returns_none_for_horizons():
    """当 fetcher 返回空数据时, 整个 ticker 不出现在结果中。"""
    fetcher = _mock_fetcher_map({})
    result = fetch_actual_returns(["000099"], "20260607", "20260613", use_data_fetcher=fetcher)
    assert "000099" not in result


def test_fetch_actual_returns_partial_horizons():
    """当数据点不足以覆盖 T+5 时, 早期 horizon 仍可计算。"""
    mapping = {
        "000004": [
            ("2026-06-07", 10.0),
            ("2026-06-08", 10.5),  # 有 T+1
            # 没有 T+3 / T+5
        ]
    }
    fetcher = _mock_fetcher_map(mapping)
    result = fetch_actual_returns(["000004"], "20260607", "20260613", use_data_fetcher=fetcher)
    assert "000004" in result
    assert "day_1" in result["000004"]
    assert "day_3" not in result["000004"]
    assert "day_5" not in result["000004"]


# ---------------------------------------------------------------------------
# 7. update_tracking_history 幂等
# ---------------------------------------------------------------------------


def test_update_tracking_history_idempotent(tmp_path: Path):
    """同一日同一报告调用两次, 历史记录不重复。"""
    recs = [
        {"ticker": "000001", "name": "A", "score_b": 0.5, "close": 10.0},
        {"ticker": "000002", "name": "B", "score_b": 0.4, "close": 20.0},
    ]
    _make_report(tmp_path, "20260607", recs)
    n1 = update_tracking_history(tmp_path, "20260607")
    n2 = update_tracking_history(tmp_path, "20260607")
    assert n1 == 2  # 新增 2 条
    assert n2 == 0  # 第二次幂等, 无新增

    history = _load_history(tmp_path / HISTORY_FILENAME)
    assert len(history) == 2
    tickers = {r["ticker"] for r in history}
    assert tickers == {"000001", "000002"}


def test_update_tracking_history_rerun_does_not_clobber_realized_return(tmp_path: Path):
    """BH-008: a re-run whose fetcher returns a shorter series must not clobber
    an already-realized return with None.

    Before the fix, Phase 2 unconditionally overwrote next_day_return …
    next_30day_return. If a later fetcher call returned fewer bars (delisted/
    halted ticker, data-source hiccup), an existing realized value was
    reverted to None, demoting a mature record and corrupting the win-rate
    pool. The fix merges (adopt only non-None fetched values)."""

    # Seed a recommendation old enough to clear the 6-day maturity gate.
    _make_report(tmp_path, "20260520", [
        {"ticker": "000001", "name": "A", "score_b": 0.5, "close": 10.0},
    ])
    # Phase 1 reads the trade_date report; an empty one triggers Phase 2 backfill
    # of the 20260520 record already in history.
    _make_report(tmp_path, "20260601", [])
    # First, persist the 20260520 record into history.
    update_tracking_history(tmp_path, "20260520")

    # First backfill run: fetcher returns a full T+5 realization (base + 5 bars).
    def full_fetcher(ticker, _frm, _to):
        return [
            {"time": "20260520", "close": 10.0},
            {"time": "20260521", "close": 11.0},
            {"time": "20260522", "close": 12.0},
            {"time": "20260523", "close": 13.0},
            {"time": "20260524", "close": 14.0},
            {"time": "20260525", "close": 15.0},
        ]

    update_tracking_history(tmp_path, "20260601", use_data_fetcher=full_fetcher)
    history = _load_history(tmp_path / HISTORY_FILENAME)
    rec = next(r for r in history if r["ticker"] == "000001")
    assert rec["next_day_return"] is not None
    assert rec["next_5day_return"] is not None

    # Second run: fetcher now returns a SHORTER series (simulating a halted
    # ticker / data-source hiccup). Before BH-008 this would clobber
    # next_5day_return → None.
    def short_fetcher(ticker, _frm, _to):
        return [
            {"time": "20260520", "close": 10.0},
            {"time": "20260521", "close": 11.0},
        ]  # only T+1 available now

    update_tracking_history(tmp_path, "20260601", use_data_fetcher=short_fetcher)
    history = _load_history(tmp_path / HISTORY_FILENAME)
    rec = next(r for r in history if r["ticker"] == "000001")
    # The already-realized T+5 must survive the re-run (no clobber).
    assert rec["next_5day_return"] is not None
    assert rec["next_day_return"] is not None


# ---------------------------------------------------------------------------
# 8. 跨日推荐合并
# ---------------------------------------------------------------------------


def test_update_tracking_history_merges_multi_day_recommendations(tmp_path: Path):
    """多日报告推荐同一 ticker, 历史应保留两条 (不同 recommended_date)。"""
    _make_report(tmp_path, "20260605", [
        {"ticker": "000001", "name": "A", "score_b": 0.5, "close": 10.0},
    ])
    _make_report(tmp_path, "20260606", [
        {"ticker": "000001", "name": "A", "score_b": 0.6, "close": 11.0},
    ])
    _make_report(tmp_path, "20260607", [
        {"ticker": "000002", "name": "B", "score_b": 0.4, "close": 20.0},
    ])

    update_tracking_history(tmp_path, "20260605")
    update_tracking_history(tmp_path, "20260606")
    update_tracking_history(tmp_path, "20260607")

    history = _load_history(tmp_path / HISTORY_FILENAME)
    assert len(history) == 3
    keys = {_record_key(r) for r in history}
    assert ("000001", "20260605") in keys
    assert ("000001", "20260606") in keys
    assert ("000002", "20260607") in keys


def test_update_tracking_history_fills_pending_returns(tmp_path: Path):
    """当历史中存在 < 6 天的 pending 记录, 不会尝试拉取收益。"""
    _make_report(tmp_path, "20260607", [
        {"ticker": "000001", "name": "A", "score_b": 0.5, "close": 10.0},
    ])
    update_tracking_history(tmp_path, "20260607")
    history = _load_history(tmp_path / HISTORY_FILENAME)
    assert history[0]["tracking_status"] == "pending"
    assert history[0]["next_day_return"] is None


def test_update_tracking_history_queries_returns_when_due(tmp_path: Path):
    """6+ 天前的 pending 记录会被查询, 有 T+5 后标记 partial (非 complete)。"""
    # Phase 1: 注册 6+ 天前的推荐
    _make_report(tmp_path, "20260601", [
        {"ticker": "000001", "name": "A", "score_b": 0.5, "close": 10.0},
    ])
    update_tracking_history(tmp_path, "20260601")
    # Phase 2: 当下日期 6+ 天后, 触发收益拉取
    mapping = {
        "000001": [
            ("2026-06-01", 10.0),
            ("2026-06-02", 10.5),
            ("2026-06-03", 10.0),
            ("2026-06-04", 11.0),
            ("2026-06-05", 10.0),
            ("2026-06-06", 12.0),  # T+5 = +20%
        ]
    }
    fetcher = _mock_fetcher_map(mapping)
    n = update_tracking_history(tmp_path, "20260610", use_data_fetcher=fetcher)
    assert n >= 1
    history = _load_history(tmp_path / HISTORY_FILENAME)
    rec = history[0]
    assert rec["tracking_status"] == "partial"  # 有 T+5, 但没有 T+30
    assert rec["next_day_return"] == pytest.approx(5.0, rel=1e-4)
    assert rec["next_3day_return"] == pytest.approx(10.0, rel=1e-4)
    assert rec["next_5day_return"] == pytest.approx(20.0, rel=1e-4)


# ---------------------------------------------------------------------------
# 9. 胜率计算
# ---------------------------------------------------------------------------


def test_summarize_win_rates():
    history = [
        {"ticker": "A", "recommended_date": "20260607", "next_day_return": 2.0, "next_3day_return": -1.0, "next_5day_return": 5.0},
        {"ticker": "B", "recommended_date": "20260607", "next_day_return": -1.0, "next_3day_return": 3.0, "next_5day_return": -2.0},
        {"ticker": "C", "recommended_date": "20260607", "next_day_return": 0.0, "next_3day_return": 0.0, "next_5day_return": 0.0},
    ]
    summary = _summarize_history(history, lookback_days=30)
    # T+1: 1 win (A) / 3 tracked = 33.33%
    assert summary["win_count_day1"] == 1
    assert summary["win_rate_day1"] == pytest.approx(1 / 3, rel=1e-4)
    # T+3: 1 win (B) / 3 tracked = 33.33%
    assert summary["win_count_day3"] == 1
    # T+5: 1 win (A) / 3 tracked = 33.33%
    assert summary["win_count_day5"] == 1


# ---------------------------------------------------------------------------
# 10. 平均收益计算
# ---------------------------------------------------------------------------


def test_summarize_avg_returns():
    history = [
        {"ticker": "A", "recommended_date": "20260607", "next_day_return": 4.0, "next_3day_return": 6.0, "next_5day_return": 10.0},
        {"ticker": "B", "recommended_date": "20260607", "next_day_return": 2.0, "next_3day_return": -2.0, "next_5day_return": 0.0},
    ]
    summary = _summarize_history(history, lookback_days=30)
    assert summary["avg_return_day1"] == pytest.approx(3.0, rel=1e-4)
    assert summary["avg_return_day3"] == pytest.approx(2.0, rel=1e-4)
    assert summary["avg_return_day5"] == pytest.approx(5.0, rel=1e-4)


def test_summarize_skips_null_returns():
    history = [
        {"ticker": "A", "recommended_date": "20260607", "next_day_return": None, "next_3day_return": None, "next_5day_return": None},
        {"ticker": "B", "recommended_date": "20260607", "next_day_return": 5.0, "next_3day_return": 7.0, "next_5day_return": 9.0},
    ]
    summary = _summarize_history(history, lookback_days=30)
    assert summary["avg_return_day1"] == pytest.approx(5.0, rel=1e-4)
    assert summary["win_rate_day1"] == pytest.approx(1.0, rel=1e-4)


# ---------------------------------------------------------------------------
# 11. tracking_history.json 损坏 → 优雅降级
# ---------------------------------------------------------------------------


def test_load_history_corrupted_json_returns_empty(tmp_path: Path):
    history_path = tmp_path / HISTORY_FILENAME
    history_path.write_text("not valid json {{{", encoding="utf-8")
    assert _load_history(history_path) == []


def test_load_history_missing_returns_empty(tmp_path: Path):
    assert _load_history(tmp_path / HISTORY_FILENAME) == []


def test_load_history_malformed_payload_returns_empty(tmp_path: Path):
    history_path = tmp_path / HISTORY_FILENAME
    history_path.write_text(json.dumps({"wrong_key": []}), encoding="utf-8")
    assert _load_history(history_path) == []


def test_update_tracking_history_handles_corrupted_history(tmp_path: Path):
    """历史文件损坏时, update 仍能正常处理当日新推荐。"""
    history_path = tmp_path / HISTORY_FILENAME
    history_path.write_text("CORRUPTED", encoding="utf-8")
    _make_report(tmp_path, "20260607", [
        {"ticker": "000001", "name": "A", "score_b": 0.5, "close": 10.0},
    ])
    n = update_tracking_history(tmp_path, "20260607")
    assert n == 1
    history = _load_history(history_path)
    assert len(history) == 1
    assert history[0]["ticker"] == "000001"


# ---------------------------------------------------------------------------
# 12. render_tracking_summary 输出格式
# ---------------------------------------------------------------------------


def test_render_tracking_summary_empty_history(tmp_path: Path):
    history_path = tmp_path / HISTORY_FILENAME
    output = render_tracking_summary(history_path, lookback_days=30)
    assert "暂无追踪历史" in output
    assert str(history_path) in output


def test_render_tracking_summary_format(tmp_path: Path):
    """输出应包含: 总推荐 / 胜率 / 平均收益字段。"""
    history = [
        {"ticker": "A", "recommended_date": "20260607", "next_day_return": 2.0, "next_3day_return": 4.0, "next_5day_return": 5.0},
        {"ticker": "B", "recommended_date": "20260607", "next_day_return": -1.0, "next_3day_return": -2.0, "next_5day_return": -3.0},
        {"ticker": "C", "recommended_date": "20260607", "next_day_return": 0.5, "next_3day_return": 1.0, "next_5day_return": 2.0},
    ]
    history_path = tmp_path / HISTORY_FILENAME
    _save_history(history_path, history)
    output = render_tracking_summary(history_path, lookback_days=30)
    assert "跟踪总结 (近 30 天)" in output
    assert "总推荐: 3 只" in output
    assert "T+1 胜率:" in output
    assert "T+3 胜率:" in output
    assert "T+5 胜率:" in output
    assert "T+10 胜率:" in output
    assert "T+20 胜率:" in output
    assert "T+30 胜率:" in output
    assert "T+1 平均收益:" in output
    assert "T+3 平均收益:" in output
    assert "T+5 平均收益:" in output
    assert "T+10 平均收益:" in output
    assert "T+20 平均收益:" in output
    assert "T+30 平均收益:" in output
    # T+1 胜率: 2/3 (A: +2.0%, C: +0.5%, B: -1.0%) = 66.7%
    assert "66.7%" in output


def test_get_tracking_summary_includes_extended_horizons(tmp_path: Path):
    history = [
        {
            "ticker": "A",
            "recommended_date": "20260607",
            "next_day_return": 2.0,
            "next_3day_return": 4.0,
            "next_5day_return": 5.0,
            "next_10day_return": 6.0,
            "next_20day_return": 8.0,
            "next_30day_return": 9.0,
        },
        {
            "ticker": "B",
            "recommended_date": "20260607",
            "next_day_return": -1.0,
            "next_3day_return": -2.0,
            "next_5day_return": -3.0,
            "next_10day_return": -4.0,
            "next_20day_return": -5.0,
            "next_30day_return": -6.0,
        },
    ]
    history_path = tmp_path / HISTORY_FILENAME
    _save_history(history_path, history)

    summary = get_tracking_summary(history_path, lookback_days=30)

    assert summary["win_count_day10"] == 1
    assert summary["win_count_day20"] == 1
    assert summary["win_count_day30"] == 1
    assert summary["tracked_count_day10"] == 2
    assert summary["tracked_count_day20"] == 2
    assert summary["tracked_count_day30"] == 2
    assert summary["win_rate_day10"] == pytest.approx(0.5, abs=1e-3)
    assert summary["win_rate_day20"] == pytest.approx(0.5, abs=1e-3)
    assert summary["win_rate_day30"] == pytest.approx(0.5, abs=1e-3)
    assert summary["avg_return_day10"] == pytest.approx(1.0, abs=1e-3)
    assert summary["avg_return_day20"] == pytest.approx(1.5, abs=1e-3)
    assert summary["avg_return_day30"] == pytest.approx(1.5, abs=1e-3)


def test_render_tracking_summary_no_data_in_lookback(tmp_path: Path):
    history = [
        {"ticker": "OLD", "recommended_date": "20200101", "next_day_return": 10.0, "next_3day_return": 20.0, "next_5day_return": 30.0},
    ]
    history_path = tmp_path / HISTORY_FILENAME
    _save_history(history_path, history)
    output = render_tracking_summary(history_path, lookback_days=30)
    assert "近 30 天内无推荐记录" in output


def test_summarize_history_as_of_includes_backfilled_records_in_window():
    """BH-007: ``_summarize_history(as_of=...)`` anchors the lookback window to
    a caller-provided instant instead of the machine wall clock, so backfilled
    recommendations (older than ``now`` but within N days of their own
    ``as_of``) are not silently dropped from win-rate.

    Default behavior (as_of=None → datetime.now()) still excludes old records
    (see test_render_tracking_summary_no_data_in_lookback). This test pins the
    new ``as_of`` capability that callers use during backfill.
    """
    history = [
        {"ticker": "000001", "recommended_date": "20200101", "next_day_return": 5.0},
        {"ticker": "000002", "recommended_date": "20200105", "next_day_return": -2.0},
    ]
    # Anchor to the data's own time: 20200105. Window = 30 days → both included.
    as_of = datetime(2020, 1, 5)
    summary = _summarize_history(history, lookback_days=30, as_of=as_of)
    assert summary["total_recommendations"] == 2
    # Wall-clock default would exclude BOTH (they're years before now()).
    summary_now = _summarize_history(history, lookback_days=30)
    assert summary_now["total_recommendations"] == 0


# ---------------------------------------------------------------------------
# Bonus: TrackingRecord serialization round-trip
# ---------------------------------------------------------------------------


def test_tracking_record_roundtrip():
    rec = TrackingRecord(
        ticker="000001",
        name="Test",
        recommended_date="20260607",
        recommended_price=10.0,
        recommendation_score=0.5,
        next_day_return=2.5,
        tracking_status="partial",
    )
    d = rec.to_dict()
    rec2 = TrackingRecord.from_dict(d)
    assert rec2.ticker == rec.ticker
    assert rec2.next_day_return == rec.next_day_return
    assert rec2.tracking_status == rec.tracking_status


# ---------------------------------------------------------------------------
# Bonus: helper unit tests
# ---------------------------------------------------------------------------


def test_safe_float_handles_nan_inf_none():
    assert _safe_float(None) == 0.0
    assert _safe_float("abc") == 0.0
    assert _safe_float(float("nan")) == 0.0
    assert _safe_float(float("inf")) == 0.0
    assert _safe_float("3.14") == pytest.approx(3.14, rel=1e-4)
    assert _safe_float(5) == 5.0


def test_optional_float_returns_none_for_invalid():
    assert _optional_float(None) is None
    assert _optional_float(float("nan")) is None
    assert _optional_float("abc") is None
    assert _optional_float("2.5") == pytest.approx(2.5, rel=1e-4)


def test_parse_date_validates_format():
    assert _parse_date("20260607") is not None
    assert _parse_date("2026-06-07") is not None
    assert _parse_date("invalid") is None
    assert _parse_date("") is None
    assert _parse_date("2026060") is None  # too short


def test_coerce_recommended_price_priority():
    """推荐价提取优先级: recommended_price > entry_price > close。"""
    rec1 = {"recommended_price": 12.0, "close": 10.0}
    rec2 = {"entry_price": 11.0, "close": 10.0}
    rec3 = {"close": 10.0}
    rec4 = {}
    assert _coerce_recommended_price(rec1) == 12.0
    assert _coerce_recommended_price(rec2) == 11.0
    assert _coerce_recommended_price(rec3) == 10.0
    assert _coerce_recommended_price(rec4) == 0.0


def test_extract_sorted_closes_filters_and_sorts():
    raw = [
        {"time": "2026-06-09", "close": 11.0},  # later
        {"time": "2026-06-07", "close": 10.0},  # base
        {"time": "2026-06-08", "close": 10.5},
        {"time": "invalid", "close": 99.0},     # invalid
        {"time": "2026-06-08", "close": 0.0},   # zero close — filtered
        {"time": "2026-06-06", "close": 9.0},   # before base — filtered
    ]
    closes = _extract_sorted_closes(raw, base_date="20260607")
    assert [c[0] for c in closes] == ["20260607", "20260608", "20260609"]
    assert [c[1] for c in closes] == [10.0, 10.5, 11.0]


def test_get_tracking_summary_empty(tmp_path: Path):
    history_path = tmp_path / HISTORY_FILENAME
    summary = get_tracking_summary(history_path, lookback_days=30)
    assert summary["total_recommendations"] == 0
    assert summary["win_rate_day1"] is None
    assert summary["avg_return_day5"] is None


def test_record_key_uniqueness():
    r1 = {"ticker": "A", "recommended_date": "20260607"}
    r2 = {"ticker": "A", "recommended_date": "20260608"}
    r3 = {"ticker": "B", "recommended_date": "20260607"}
    assert _record_key(r1) != _record_key(r2)
    assert _record_key(r1) != _record_key(r3)
    assert _record_key(r1) == ("A", "20260607")


def test_update_tracking_history_empty_recommendations(tmp_path: Path):
    """当报告存在但 recommendations 为空, 不会 crash, 返回 0。"""
    _make_report(tmp_path, "20260607", [])
    n = update_tracking_history(tmp_path, "20260607")
    assert n == 0
    assert _load_history(tmp_path / HISTORY_FILENAME) == []


def test_default_horizons_constant():
    """DEFAULT_HORIZONS 必须包含扩展周期 (1, 3, 5, 10, 20, 30)。"""
    assert DEFAULT_HORIZONS == (1, 3, 5, 10, 20, 30)


def test_uses_injected_fetcher_for_actual_returns(tmp_path: Path):
    """验证 use_data_fetcher 被实际调用, 默认 fetcher 不被触发。"""
    call_log: list[tuple[str, str, str]] = []
    def fake_fetcher(ticker, start, end):
        call_log.append((ticker, start, end))
        if ticker == "000010":
            return [
                {"time": "2026-06-07", "close": 5.0},
                {"time": "2026-06-08", "close": 5.5},
            ]
        return []
    with patch(
        "src.screening.recommendation_tracker._default_price_fetcher",
        side_effect=AssertionError("默认 fetcher 不应被调用"),
    ):
        result = fetch_actual_returns(["000010"], "20260607", "20260613", use_data_fetcher=fake_fetcher)
    # 窗口扩展从 +10 天改为 +45 天 (为 T+30 容错)
    assert call_log == [("000010", "20260607", "20260728")]
    assert result["000010"]["day_1"] == pytest.approx(10.0, rel=1e-4)
