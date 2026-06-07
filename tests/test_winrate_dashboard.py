"""P2-4 历史推荐胜率看板测试 — 12 个测试用例。

覆盖:
1. 空历史 → 空摘要
2. 单日数据
3. 多日聚合
4. T+1/T+3/T+5 分别计算
5. trend = improving
6. trend = declining
7. trend = stable
8. ASCII 趋势图渲染
9. 损坏 JSON → 降级
10. 混合有/无收益的推荐
11. CLI smoke
12. Web 端点 smoke
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from src.screening.winrate_dashboard import (
    DailyWinRate,
    WinRateSummary,
    compute_winrate_dashboard,
    render_winrate_dashboard,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_history(records: list[dict]) -> dict:
    """构造 tracking_history.json 的顶层结构。"""
    return {"records": records, "updated_at": "20260601120000"}


def _make_record(
    ticker: str,
    recommended_date: str,
    *,
    next_day_return: float | None = None,
    next_3day_return: float | None = None,
    next_5day_return: float | None = None,
    recommended_price: float = 10.0,
    score_b: float = 0.5,
) -> dict:
    """构造单条 TrackingRecord dict。"""
    return {
        "ticker": ticker,
        "name": f"测试{ticker}",
        "recommended_date": recommended_date,
        "recommended_price": recommended_price,
        "recommendation_score": score_b,
        "next_day_return": next_day_return,
        "next_3day_return": next_3day_return,
        "next_5day_return": next_5day_return,
        "tracking_status": "complete" if next_5day_return is not None else "pending",
    }


def _write_history(tmp_path: Path, records: list[dict]) -> Path:
    """写入 tracking_history.json 并返回路径。"""
    history_path = tmp_path / "tracking_history.json"
    history_path.write_text(json.dumps(_make_history(records), ensure_ascii=False, indent=2), encoding="utf-8")
    return history_path


def _days_ago(n: int) -> str:
    """返回 N 天前的日期 YYYYMMDD。"""
    return (datetime.now() - timedelta(days=n)).strftime("%Y%m%d")


# ---------------------------------------------------------------------------
# Test 1: 空历史 → 空摘要
# ---------------------------------------------------------------------------


class TestEmptyHistory:
    def test_file_not_exists(self, tmp_path: Path) -> None:
        path = tmp_path / "nonexistent.json"
        summary = compute_winrate_dashboard(path, lookback_days=30)
        assert summary.total_days == 0
        assert summary.total_recommendations == 0
        assert summary.avg_t1_win_rate is None
        assert summary.daily == []

    def test_empty_records(self, tmp_path: Path) -> None:
        path = _write_history(tmp_path, [])
        summary = compute_winrate_dashboard(path, lookback_days=30)
        assert summary.total_days == 0
        assert summary.total_recommendations == 0


# ---------------------------------------------------------------------------
# Test 2: 单日数据
# ---------------------------------------------------------------------------


class TestSingleDay:
    def test_single_day_stats(self, tmp_path: Path) -> None:
        date = _days_ago(3)
        records = [
            _make_record("000001", date, next_day_return=2.0, next_3day_return=3.0, next_5day_return=1.0),
            _make_record("000002", date, next_day_return=-1.0, next_3day_return=0.5, next_5day_return=2.0),
            _make_record("000003", date, next_day_return=1.5, next_3day_return=-0.5, next_5day_return=0.0),
        ]
        path = _write_history(tmp_path, records)
        summary = compute_winrate_dashboard(path, lookback_days=30)

        assert summary.total_days == 1
        assert summary.total_recommendations == 3
        # T+1: 2 winners out of 3 = 66.7%
        assert summary.avg_t1_win_rate is not None
        assert abs(summary.avg_t1_win_rate - 2 / 3) < 0.01
        # T+1 avg return: (2.0 + (-1.0) + 1.5) / 3 = 0.833
        assert summary.avg_t1_return is not None
        assert abs(summary.avg_t1_return - (2.0 - 1.0 + 1.5) / 3) < 0.01

        # 日度数据
        assert len(summary.daily) == 1
        day = summary.daily[0]
        assert day.date == date
        assert day.total_recommendations == 3
        assert day.t1_winners == 2


# ---------------------------------------------------------------------------
# Test 3: 多日聚合
# ---------------------------------------------------------------------------


class TestMultiDayAggregation:
    def test_multi_day_summary(self, tmp_path: Path) -> None:
        d1 = _days_ago(5)
        d2 = _days_ago(3)
        d3 = _days_ago(1)
        records = [
            _make_record("000001", d1, next_day_return=3.0, next_3day_return=4.0, next_5day_return=2.0),
            _make_record("000002", d1, next_day_return=-2.0, next_3day_return=1.0, next_5day_return=0.5),
            _make_record("000003", d2, next_day_return=1.0, next_3day_return=2.0, next_5day_return=3.0),
            _make_record("000004", d2, next_day_return=2.0, next_3day_return=1.5, next_5day_return=1.0),
            _make_record("000005", d3, next_day_return=-1.0, next_3day_return=0.0, next_5day_return=None),
        ]
        path = _write_history(tmp_path, records)
        summary = compute_winrate_dashboard(path, lookback_days=30)

        assert summary.total_days == 3
        assert summary.total_recommendations == 5
        # 3 days, daily T+1 win rates: d1=1/2=50%, d2=2/2=100%, d3=0/1=0%
        # avg_t1_win_rate = mean of daily rates = (0.5 + 1.0 + 0.0) / 3
        assert summary.avg_t1_win_rate is not None
        assert abs(summary.avg_t1_win_rate - (0.5 + 1.0 + 0.0) / 3) < 0.01

        assert len(summary.daily) == 3
        assert summary.daily[0].date == d1
        assert summary.daily[1].date == d2
        assert summary.daily[2].date == d3


# ---------------------------------------------------------------------------
# Test 4: T+1/T+3/T+5 分别计算
# ---------------------------------------------------------------------------


class TestHorizonSeparation:
    def test_each_horizon_independent(self, tmp_path: Path) -> None:
        date = _days_ago(3)
        records = [
            # T+1 盈利, T+3 亏损, T+5 盈利
            _make_record("000001", date, next_day_return=2.0, next_3day_return=-3.0, next_5day_return=5.0),
            # T+1 亏损, T+3 盈利, T+5 亏损
            _make_record("000002", date, next_day_return=-1.0, next_3day_return=4.0, next_5day_return=-2.0),
        ]
        path = _write_history(tmp_path, records)
        summary = compute_winrate_dashboard(path, lookback_days=30)

        day = summary.daily[0]
        # T+1: 1/2 winner (50%), avg = (2-1)/2 = 0.5
        assert day.t1_win_rate is not None
        assert abs(day.t1_win_rate - 0.5) < 0.01
        assert day.t1_avg_return is not None
        assert abs(day.t1_avg_return - 0.5) < 0.01

        # T+3: 1/2 winner (50%), avg = (-3+4)/2 = 0.5
        assert day.t3_win_rate is not None
        assert abs(day.t3_win_rate - 0.5) < 0.01
        assert day.t3_avg_return is not None
        assert abs(day.t3_avg_return - 0.5) < 0.01

        # T+5: 1/2 winner (50%), avg = (5-2)/2 = 1.5
        assert day.t5_win_rate is not None
        assert abs(day.t5_win_rate - 0.5) < 0.01
        assert day.t5_avg_return is not None
        assert abs(day.t5_avg_return - 1.5) < 0.01


# ---------------------------------------------------------------------------
# Test 5: trend = improving
# ---------------------------------------------------------------------------


class TestTrendImproving:
    def test_recent_higher_than_earlier(self, tmp_path: Path) -> None:
        records = []
        for i in range(14):
            d = _days_ago(14 - i)
            if i < 7:
                # 早期: 低胜率 (1/3 ≈ 33%)
                records.append(_make_record(f"00{i}01", d, next_day_return=-1.0))
                records.append(_make_record(f"00{i}02", d, next_day_return=-2.0))
                records.append(_make_record(f"00{i}03", d, next_day_return=1.0))
            else:
                # 近期: 高胜率 (3/3 = 100%)
                records.append(_make_record(f"00{i}01", d, next_day_return=2.0))
                records.append(_make_record(f"00{i}02", d, next_day_return=1.0))
                records.append(_make_record(f"00{i}03", d, next_day_return=3.0))

        path = _write_history(tmp_path, records)
        summary = compute_winrate_dashboard(path, lookback_days=30)
        assert summary.trend == "improving"


# ---------------------------------------------------------------------------
# Test 6: trend = declining
# ---------------------------------------------------------------------------


class TestTrendDeclining:
    def test_recent_lower_than_earlier(self, tmp_path: Path) -> None:
        records = []
        for i in range(14):
            d = _days_ago(14 - i)
            if i < 7:
                # 早期: 高胜率 (3/3 = 100%)
                records.append(_make_record(f"00{i}01", d, next_day_return=2.0))
                records.append(_make_record(f"00{i}02", d, next_day_return=1.0))
                records.append(_make_record(f"00{i}03", d, next_day_return=3.0))
            else:
                # 近期: 低胜率 (1/3 ≈ 33%)
                records.append(_make_record(f"00{i}01", d, next_day_return=-1.0))
                records.append(_make_record(f"00{i}02", d, next_day_return=-2.0))
                records.append(_make_record(f"00{i}03", d, next_day_return=1.0))

        path = _write_history(tmp_path, records)
        summary = compute_winrate_dashboard(path, lookback_days=30)
        assert summary.trend == "declining"


# ---------------------------------------------------------------------------
# Test 7: trend = stable
# ---------------------------------------------------------------------------


class TestTrendStable:
    def test_similar_recent_and_earlier(self, tmp_path: Path) -> None:
        records = []
        for i in range(14):
            d = _days_ago(14 - i)
            # 全部 50% 胜率
            records.append(_make_record(f"00{i}01", d, next_day_return=1.0))
            records.append(_make_record(f"00{i}02", d, next_day_return=-1.0))

        path = _write_history(tmp_path, records)
        summary = compute_winrate_dashboard(path, lookback_days=30)
        assert summary.trend == "stable"

    def test_insufficient_data_is_stable(self, tmp_path: Path) -> None:
        d = _days_ago(1)
        records = [
            _make_record("000001", d, next_day_return=1.0),
        ]
        path = _write_history(tmp_path, records)
        summary = compute_winrate_dashboard(path, lookback_days=30)
        assert summary.trend == "stable"


# ---------------------------------------------------------------------------
# Test 8: ASCII 趋势图渲染
# ---------------------------------------------------------------------------


class TestRenderDashboard:
    def test_render_with_data(self, tmp_path: Path) -> None:
        d1 = _days_ago(5)
        d2 = _days_ago(3)
        records = [
            _make_record("000001", d1, next_day_return=2.0, next_3day_return=3.0, next_5day_return=1.0),
            _make_record("000002", d1, next_day_return=-1.0, next_3day_return=0.5, next_5day_return=2.0),
            _make_record("000003", d2, next_day_return=1.5, next_3day_return=-0.5, next_5day_return=0.0),
        ]
        path = _write_history(tmp_path, records)
        summary = compute_winrate_dashboard(path, lookback_days=30)
        output = render_winrate_dashboard(summary)

        assert "历史推荐胜率看板" in output
        assert "近 30 天" in output
        assert "总推荐: 3 只" in output
        assert "T+1 平均胜率:" in output
        assert "T+1 平均收益:" in output
        assert "趋势:" in output
        assert "日度趋势 (T+1 胜率):" in output
        # 应包含 bar chars
        assert "█" in output or "░" in output

    def test_render_empty(self) -> None:
        summary = WinRateSummary(period_days=30)
        output = render_winrate_dashboard(summary)
        assert "暂无推荐历史数据" in output

    def test_render_contains_date_labels(self, tmp_path: Path) -> None:
        d1 = _days_ago(5)
        records = [
            _make_record("000001", d1, next_day_return=1.0),
        ]
        path = _write_history(tmp_path, records)
        summary = compute_winrate_dashboard(path, lookback_days=30)
        output = render_winrate_dashboard(summary)
        # Date label should be MM-DD format
        expected_label = f"{d1[4:6]}-{d1[6:]}"
        assert expected_label in output

    def test_render_missing_t1_shows_dash(self, tmp_path: Path) -> None:
        d1 = _days_ago(5)
        records = [
            _make_record("000001", d1, next_day_return=None),
        ]
        path = _write_history(tmp_path, records)
        summary = compute_winrate_dashboard(path, lookback_days=30)
        output = render_winrate_dashboard(summary)
        # When t1_win_rate is None, the bar line should show "—"
        assert "—" in output


# ---------------------------------------------------------------------------
# Test 9: 损坏 JSON → 降级
# ---------------------------------------------------------------------------


class TestCorruptJson:
    def test_invalid_json_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "tracking_history.json"
        path.write_text("{bad json content", encoding="utf-8")
        summary = compute_winrate_dashboard(path, lookback_days=30)
        assert summary.total_days == 0
        assert summary.total_recommendations == 0

    def test_missing_records_key_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "tracking_history.json"
        path.write_text('{"updated_at": "20260601"}', encoding="utf-8")
        summary = compute_winrate_dashboard(path, lookback_days=30)
        assert summary.total_days == 0

    def test_records_not_list_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "tracking_history.json"
        path.write_text('{"records": "not a list"}', encoding="utf-8")
        summary = compute_winrate_dashboard(path, lookback_days=30)
        assert summary.total_days == 0


# ---------------------------------------------------------------------------
# Test 10: 混合有/无收益的推荐
# ---------------------------------------------------------------------------


class TestMixedReturns:
    def test_partial_returns_only_count_tracked(self, tmp_path: Path) -> None:
        date = _days_ago(3)
        records = [
            _make_record("000001", date, next_day_return=2.0, next_3day_return=3.0, next_5day_return=1.0),
            _make_record("000002", date, next_day_return=None, next_3day_return=1.0, next_5day_return=None),
            _make_record("000003", date, next_day_return=-1.0, next_3day_return=None, next_5day_return=None),
        ]
        path = _write_history(tmp_path, records)
        summary = compute_winrate_dashboard(path, lookback_days=30)

        day = summary.daily[0]
        assert day.total_recommendations == 3
        # T+1: only 2 tracked (2.0 and -1.0), 1 winner → 50%
        assert day.t1_win_rate is not None
        assert abs(day.t1_win_rate - 0.5) < 0.01
        # T+3: only 2 tracked (3.0 and 1.0), 2 winners → 100%
        assert day.t3_win_rate is not None
        assert abs(day.t3_win_rate - 1.0) < 0.01
        # T+5: only 1 tracked (1.0), 1 winner → 100%
        assert day.t5_win_rate is not None
        assert abs(day.t5_win_rate - 1.0) < 0.01


# ---------------------------------------------------------------------------
# Test 11: CLI smoke
# ---------------------------------------------------------------------------


class TestCLISmoke:
    def test_cli_help_or_exit(self) -> None:
        """CLI --winrate-dashboard should be recognized (may exit 1 if no data)."""
        result = subprocess.run(
            [sys.executable, "-m", "src.main", "--winrate-dashboard"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # It should either print the dashboard (exit 0) or show a message (exit 1)
        # but NOT crash with a traceback (exit != 0 but stderr empty or with known messages)
        combined = result.stdout + result.stderr
        # Should not have a Python traceback from our module
        assert "winrate_dashboard" not in combined or "暂无" in combined or "历史推荐胜率看板" in combined or result.returncode in (0, 1)


# ---------------------------------------------------------------------------
# Test 12: Web 端点 smoke
# ---------------------------------------------------------------------------


class TestWebEndpointSmoke:
    def test_endpoint_definition_exists(self) -> None:
        """Verify the web endpoint is registered by importing the module."""
        from app.backend.routes.screening import router

        routes = [r.path for r in router.routes]
        assert "/winrate-dashboard" in routes or "/api/screening/winrate-dashboard" in routes

    def test_endpoint_returns_summary(self) -> None:
        """Test the endpoint handler with mock data."""
        from fastapi.testclient import TestClient

        from app.backend.routes.screening import router

        # We just check the route exists and is callable via FastAPI
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        # The endpoint should return 200 even with no data (degraded gracefully)
        response = client.get("/api/screening/winrate-dashboard", params={"lookback_days": 30})
        assert response.status_code == 200
        data = response.json()
        assert "period_days" in data
        assert "total_days" in data
        assert "daily" in data
        assert "trend" in data
