"""gamma Round 16 — 集成测试: 验证 Round 7-15 新增 24 个功能模块间的协作。

8 个端到端集成场景:
  1. auto_screening -> tracking -> winrate_dashboard
  2. auto_screening -> consecutive -> decay -> explainability
  3. auto_screening -> industry_rotation -> compare
  4. auto_screening -> watchlist -> stock_detail
  5. auto_screening -> conditional_orders -> PDF
  6. custom_weights -> reweight -> compare
  7. rebalance -> performance_report
  8. preheat -> auto_screening (cache hit)

所有外部数据获取全部 mock, 不依赖网络 / tushare / akshare。
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ============================================================================
# Shared fixtures & helpers
# ============================================================================


def _make_recommendation(
    ticker: str,
    name: str = "",
    industry_sw: str = "test_industry",
    score_b: float = 0.5,
    decision: str = "watch",
    strategy_signals: dict | None = None,
    metrics: dict | None = None,
    current_price: float = 10.0,
) -> dict[str, Any]:
    """构建一条标准的 recommendation dict (与 auto_screening 输出对齐)。"""
    if strategy_signals is None:
        strategy_signals = {
            "trend": {"direction": 1, "confidence": 60, "completeness": 1.0},
            "mean_reversion": {"direction": 1, "confidence": 50, "completeness": 1.0},
            "fundamental": {"direction": 1, "confidence": 70, "completeness": 1.0},
            "event_sentiment": {"direction": 0, "confidence": 30, "completeness": 0.5},
        }
    if metrics is None:
        metrics = {}
    return {
        "ticker": ticker,
        "name": name or ticker,
        "industry_sw": industry_sw,
        "score_b": score_b,
        "decision": decision,
        "strategy_signals": strategy_signals,
        "metrics": metrics,
        "current_price": current_price,
        "arbitration_applied": [],
    }


def _write_auto_report(
    report_dir: Path,
    date_str: str,
    recommendations: list[dict],
    market_state: dict | None = None,
) -> Path:
    """写入一个最小可用的 auto_screening_{date}.json 文件。"""
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": "auto_screening",
        "date": date_str,
        "market_state": market_state or {"state_type": "mixed", "position_scale": 1.0},
        "layer_a_count": 100,
        "total_scored": 50,
        "high_pool_count": 10,
        "top_n": len(recommendations),
        "recommendations": recommendations,
        "sector_concentration_warnings": [],
        "industry_rotation": [],
        "signal_decay_summary": {},
        "conditional_orders": [],
    }
    out = report_dir / f"auto_screening_{date_str}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return out


@pytest.fixture()
def tmp_reports(tmp_path: Path) -> Path:
    """创建临时 reports 目录。"""
    d = tmp_path / "data" / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture()
def mock_recommendations_day1() -> list[dict]:
    """3 只推荐标的 (day 1)。"""
    return [
        _make_recommendation("300750", "宁德时代", "电力设备", score_b=0.65, decision="strong_buy"),
        _make_recommendation("600519", "贵州茅台", "食品饮料", score_b=0.50, decision="watch"),
        _make_recommendation("000001", "平安银行", "银行", score_b=0.35, decision="watch"),
    ]


@pytest.fixture()
def mock_recommendations_day2() -> list[dict]:
    """3 只推荐标的 (day 2) — 300750 和 600519 连续, 000001 被 002594 替代。"""
    return [
        _make_recommendation("300750", "宁德时代", "电力设备", score_b=0.60, decision="watch"),
        _make_recommendation("600519", "贵州茅台", "食品饮料", score_b=0.55, decision="watch"),
        _make_recommendation("002594", "比亚迪", "汽车", score_b=0.40, decision="watch"),
    ]


@pytest.fixture()
def mock_recommendations_day3() -> list[dict]:
    """3 只推荐标的 (day 3) — 300750 连续 3 天。"""
    return [
        _make_recommendation("300750", "宁德时代", "电力设备", score_b=0.55, decision="watch"),
        _make_recommendation("002594", "比亚迪", "汽车", score_b=0.45, decision="watch"),
        _make_recommendation("000858", "五粮液", "食品饮料", score_b=0.38, decision="neutral"),
    ]


# ============================================================================
# Scenario 1: auto_screening -> tracking -> winrate_dashboard
# ============================================================================


class TestAutoScreeningTrackingDashboard:
    """集成测试 1: auto_screening -> tracking -> winrate_dashboard。

    验证:
    - auto_screening 报告写入 -> recommendation_tracker 读取并写入 tracking_history
    - tracking_history 被 winrate_dashboard 读取生成看板
    """

    def test_tracking_to_dashboard_pipeline(self, tmp_reports: Path, mock_recommendations_day1: list[dict], mock_recommendations_day2: list[dict]) -> None:
        """写入 2 天 auto_screening 报告 -> update_tracking -> compute_winrate_dashboard。"""
        from src.screening.recommendation_tracker import (
            update_tracking_history,
            load_pending_recommendations,
        )
        from src.screening.winrate_dashboard import compute_winrate_dashboard, render_winrate_dashboard

        # Day 1: 写入报告
        _write_auto_report(tmp_reports, "20260601", mock_recommendations_day1)

        # Day 2: 写入报告
        _write_auto_report(tmp_reports, "20260605", mock_recommendations_day2)

        # 模拟价格 fetcher — 所有标的 T+1 都涨 2%
        def mock_price_fetcher(ticker: str, start: str, end: str) -> list[dict]:
            base_date = datetime.strptime(start.replace("-", ""), "%Y%m%d")
            return [
                {"time": (base_date + timedelta(days=i)).strftime("%Y-%m-%d"), "close": 10.0 + i * 0.2}
                for i in range(10)
            ]

        # Phase 1: 写入 day1 推荐
        updated_1 = update_tracking_history(
            tmp_reports,
            trade_date="20260601",
            use_data_fetcher=mock_price_fetcher,
        )
        assert updated_1 >= 1  # 至少写入 3 条新推荐

        # Phase 2: day2 更新 (day1 已超过 6 天, 可以拉取收益)
        updated_2 = update_tracking_history(
            tmp_reports,
            trade_date="20260605",
            use_data_fetcher=mock_price_fetcher,
        )
        assert updated_2 >= 1  # 至少写入 day2 的新推荐

        # Phase 3: 用 winrate_dashboard 读取 tracking_history
        history_path = tmp_reports / "tracking_history.json"
        assert history_path.exists()

        summary = compute_winrate_dashboard(history_path, lookback_days=30)
        assert summary.total_days >= 1
        assert summary.total_recommendations >= 1

        # 渲染看板 (无崩溃)
        rendered = render_winrate_dashboard(summary)
        assert isinstance(rendered, str)
        assert "胜率看板" in rendered


# ============================================================================
# Scenario 2: auto_screening -> consecutive -> decay -> explainability
# ============================================================================


class TestConsecutiveDecayExplain:
    """集成测试 2: auto_screening -> consecutive -> decay -> explainability。

    验证:
    - 3 天报告写入 -> consecutive_recommendation 计算连续天数
    - signal_decay_detector 检测 300750 的衰减 (0.65 -> 0.60 -> 0.55)
    - explainability 辅助函数正常工作
    """

    def test_consecutive_decay_explain_pipeline(self, tmp_reports: Path, mock_recommendations_day1: list[dict], mock_recommendations_day2: list[dict], mock_recommendations_day3: list[dict]) -> None:
        from src.screening.consecutive_recommendation import compute_consecutive_recommendations, RecommendationStatus
        from src.screening.signal_decay_detector import detect_signal_decay, DecayLevel
        from src.targets.explainability import derive_confidence, trim_reasons

        # 写入 3 天报告
        _write_auto_report(tmp_reports, "20260601", mock_recommendations_day1)
        _write_auto_report(tmp_reports, "20260602", mock_recommendations_day2)
        _write_auto_report(tmp_reports, "20260603", mock_recommendations_day3)

        # Step 1: consecutive_recommendation
        consecutive = compute_consecutive_recommendations(
            lookback_days=3,
            report_dir=tmp_reports,
            end_date="20260603",
        )

        # 300750 应该连续 3 天推荐
        assert "300750" in consecutive
        stats_300750 = consecutive["300750"]
        assert stats_300750.consecutive_days == 3
        assert stats_300750.status == RecommendationStatus.CONSECUTIVE_3PLUS
        assert stats_300750.stability_bonus == 10.0

        # 600519 只在 day1/day2 出现, day3 不出现
        assert "600519" in consecutive
        stats_600519 = consecutive["600519"]
        # day3 没出现所以不是连续
        assert stats_600519.consecutive_days <= 2

        # Step 2: signal_decay
        decay_map = detect_signal_decay(
            current_recommendations=mock_recommendations_day3,
            report_dir=tmp_reports,
            lookback_days=3,
            end_date="20260603",
        )

        # 300750: score 从 0.65 -> 0.60 -> 0.55, 应检测到衰减
        assert "300750" in decay_map
        decay_300750 = decay_map["300750"]
        assert decay_300750.current_score == 0.55
        assert decay_300750.previous_score == 0.60
        # 下降 ~8.3% -> 未达到 10% 阈值, 所以是 NONE 或 MILD
        assert decay_300750.level in (DecayLevel.NONE, DecayLevel.MILD)

        # Step 3: explainability 辅助函数
        conf = derive_confidence(0.8, 0.6, 0.9)
        assert 0.0 <= conf <= 1.0
        assert conf == 0.9  # max of components

        trimmed = trim_reasons(["趋势强势", "基本面优秀", "均值回归信号", "多余理由"])
        assert len(trimmed) == 3
        assert "多余理由" not in trimmed


# ============================================================================
# Scenario 3: auto_screening -> industry_rotation -> compare
# ============================================================================


class TestIndustryRotationCompare:
    """集成测试 3: auto_screening -> industry_rotation -> compare。

    验证:
    - 推荐结果中含多个行业标的 -> industry_rotation 正确排名
    - 从推荐结果中取 2-3 只同/跨行业标的 -> compare_tickers 对比
    """

    def test_rotation_then_compare_pipeline(self, tmp_reports: Path) -> None:
        from src.screening.industry_rotation import calculate_industry_rotation
        from src.screening.compare_tool import compare_tickers

        # 构造含 2+ 个行业的推荐结果
        recs = [
            _make_recommendation("300750", "宁德时代", "电力设备", score_b=0.65),
            _make_recommendation("002594", "比亚迪", "汽车", score_b=0.50),
            _make_recommendation("600519", "贵州茅台", "食品饮料", score_b=0.45),
            _make_recommendation("000858", "五粮液", "食品饮料", score_b=0.40),
            _make_recommendation("601012", "隆基绿能", "电力设备", score_b=0.35),
        ]

        _write_auto_report(tmp_reports, "20260601", recs)

        # Step 1: industry_rotation
        signals = calculate_industry_rotation(recommendations=recs, trade_date="20260601")

        # 至少应有 "电力设备" 和 "食品饮料" 两个行业 (各 >=2 只候选)
        industry_names = [s.industry_name for s in signals]
        assert "电力设备" in industry_names
        assert "食品饮料" in industry_names
        # "汽车" 只有 1 只 -> 不应出现
        assert "汽车" not in industry_names

        # 第 1 名应有最高 momentum
        if len(signals) >= 2:
            assert signals[0].rank == 1
            assert signals[0].momentum_score >= signals[1].momentum_score

        # Step 2: compare_tickers — 选 3 只做对比
        report = compare_tickers(
            tickers=["300750", "600519", "000858"],
            recommendations=recs,
        )
        assert len(report.tickers) == 3
        assert len(report.metrics) == 3 * 5  # 3 tickers x 5 metrics
        assert report.winner is not None  # 应有明确的 winner
        # 300750 score_b=0.65 最高 -> 应该赢得 score_b 维度
        score_b_metrics = [m for m in report.metrics if m.metric_name == "score_b"]
        metric_300750 = [m for m in score_b_metrics if m.ticker == "300750"][0]
        assert metric_300750.rank_in_group == 1


# ============================================================================
# Scenario 4: auto_screening -> watchlist -> stock_detail
# ============================================================================


class TestWatchlistStockDetail:
    """集成测试 4: auto_screening -> watchlist -> stock_detail。

    验证:
    - 推荐标的加入自选池 -> watchlist 正确持久化
    - stock_detail 从推荐报告 + watchlist 中聚合数据
    """

    def test_watchlist_then_stock_detail(self, tmp_reports: Path, mock_recommendations_day1: list[dict]) -> None:
        from src.screening.watchlist import Watchlist
        from src.screening.stock_detail import compute_stock_detail, render_stock_detail

        _write_auto_report(tmp_reports, "20260601", mock_recommendations_day1)

        # Step 1: 将推荐标的加入自选池
        watchlist_path = tmp_reports.parent.parent / "watchlist.json"
        wl = Watchlist(path=watchlist_path)

        for rec in mock_recommendations_day1:
            wl.add(rec["ticker"], rec["name"], tags=[rec["industry_sw"]])
            wl.update_score(rec["ticker"], score=rec["score_b"], signal=rec["decision"])

        assert len(wl) == 3
        assert "300750" in wl
        assert "600519" in wl
        assert "000001" in wl

        # Step 2: stock_detail — 300750 详情
        detail = compute_stock_detail(
            ticker="300750",
            recommendations=mock_recommendations_day1,
            report_dir=tmp_reports,
            trade_date="20260601",
        )
        assert detail.ticker == "300750"
        assert detail.name == "宁德时代"
        assert detail.industry_sw == "电力设备"
        assert detail.latest_score_b == 0.65
        assert detail.latest_decision == "strong_buy"

        # 渲染详情
        rendered = render_stock_detail(detail)
        assert "300750" in rendered
        assert "宁德时代" in rendered


# ============================================================================
# Scenario 5: auto_screening -> conditional_orders -> PDF
# ============================================================================


class TestConditionalOrdersPDF:
    """集成测试 5: auto_screening -> conditional_orders -> PDF。

    验证:
    - 从推荐结果生成条件单建议
    - 将条件单 + 推荐报告导出为 PDF
    """

    def test_conditional_orders_then_pdf(self, tmp_reports: Path, mock_recommendations_day1: list[dict], tmp_path: Path) -> None:
        from src.screening.conditional_order_advisor import (
            compute_conditional_advice,
            format_conditional_advice_table,
        )
        from src.reporting.pdf_exporter import generate_screening_pdf

        _write_auto_report(tmp_reports, "20260601", mock_recommendations_day1)

        # Step 1: 为每只标的生成条件单
        price_history = [10.0 + i * 0.1 for i in range(20)]  # 模拟 20 日价格

        advices = []
        for rec in mock_recommendations_day1:
            advice = compute_conditional_advice(
                ticker=rec["ticker"],
                current_price=rec.get("current_price", 10.0),
                price_history=price_history,
                name=rec["name"],
            )
            advices.append(advice)

        assert len(advices) == 3
        for advice in advices:
            assert advice.current_price > 0
            assert advice.suggested_buy_zone[0] < advice.suggested_buy_zone[1]
            assert advice.suggested_stop_loss < advice.current_price
            assert advice.suggested_take_profit > advice.current_price
            assert not advice.degraded  # 有足够数据, 不应降级

        # 渲染条件单表
        table = format_conditional_advice_table(advices)
        assert "300750" in table
        assert "买入区间" in table

        # Step 2: PDF 生成
        report_data = {
            "mode": "auto_screening",
            "date": "20260601",
            "market_state": {"state_type": "mixed", "position_scale": 1.0},
            "layer_a_count": 100,
            "total_scored": 50,
            "high_pool_count": 10,
            "top_n": 3,
            "recommendations": mock_recommendations_day1,
            "sector_concentration_warnings": [],
            "industry_rotation": [],
            "tracking_summary": {},
        }
        pdf_path = tmp_path / "test_report.pdf"
        generated = generate_screening_pdf(report_data, pdf_path)
        assert generated.exists()
        assert generated.stat().st_size > 1000  # PDF 至少有内容


# ============================================================================
# Scenario 6: custom_weights -> reweight -> compare
# ============================================================================


class TestCustomWeightsReweightCompare:
    """集成测试 6: custom_weights -> reweight -> compare。

    验证:
    - 自定义权重 -> reweight_recommendations 重算 score_b
    - 原推荐 vs 新推荐通过 compare_tickers 对比
    """

    def test_reweight_then_compare(self) -> None:
        from src.screening.custom_weights import StrategyWeights, reweight_recommendations
        from src.screening.compare_tool import compare_tickers

        # 构造 2 只标的, 其中 A 趋势强、B 基本面强
        recs = [
            _make_recommendation(
                "300750",
                "宁德时代",
                score_b=0.50,
                strategy_signals={
                    "trend": {"direction": 1, "confidence": 80, "completeness": 1.0},
                    "mean_reversion": {"direction": 0, "confidence": 20, "completeness": 1.0},
                    "fundamental": {"direction": 0, "confidence": 10, "completeness": 1.0},
                    "event_sentiment": {"direction": 0, "confidence": 10, "completeness": 1.0},
                },
            ),
            _make_recommendation(
                "600519",
                "贵州茅台",
                score_b=0.50,
                strategy_signals={
                    "trend": {"direction": 0, "confidence": 10, "completeness": 1.0},
                    "mean_reversion": {"direction": 0, "confidence": 20, "completeness": 1.0},
                    "fundamental": {"direction": 1, "confidence": 90, "completeness": 1.0},
                    "event_sentiment": {"direction": 0, "confidence": 10, "completeness": 1.0},
                },
            ),
        ]

        # Step 1: 默认权重 (等权) 的 compare
        default_report = compare_tickers(tickers=["300750", "600519"], recommendations=recs)

        # Step 2: 自定义权重 — 趋势 70% + 基本面 30%
        trend_heavy = StrategyWeights(trend=0.70, mean_reversion=0.0, fundamental=0.30, event_sentiment=0.0)
        reweighted = reweight_recommendations(recs, trend_heavy, sort=True)

        assert len(reweighted) == 2
        # 300750 趋势强 -> 在趋势加权下应排第一
        assert reweighted[0]["ticker"] == "300750"
        assert reweighted[0]["original_score_b"] == 0.50
        assert reweighted[0]["score_b"] != 0.50  # 重算后不同

        # Step 3: 基本面权重 -> 600519 应反超
        fund_heavy = StrategyWeights(trend=0.0, mean_reversion=0.0, fundamental=0.70, event_sentiment=0.30)
        reweighted_fund = reweight_recommendations(recs, fund_heavy, sort=True)
        assert reweighted_fund[0]["ticker"] == "600519"

        # Step 4: 用 compare 对比原始 vs 重算
        compare_report = compare_tickers(
            tickers=["300750", "600519"],
            recommendations=reweighted,
        )
        assert compare_report.winner == "300750"  # 趋势加权下 300750 胜


# ============================================================================
# Scenario 7: rebalance -> performance_report
# ============================================================================


class TestRebalancePerformanceReport:
    """集成测试 7: rebalance -> performance_report。

    验证:
    - 给定持仓列表 -> rebalance_advisor 计算再平衡建议
    - 用持仓历史 + 交易记录 -> performance_report 生成绩效报告
    """

    def test_rebalance_then_performance_report(self) -> None:
        from src.portfolio.rebalance_advisor import compute_rebalance_actions, format_rebalance_actions
        from src.portfolio.performance_report import generate_performance_report, render_performance_report

        portfolio_value = 1_000_000.0

        # Step 1: 当前持仓 (偏离目标权重)
        positions = [
            {"ticker": "300750", "name": "宁德时代", "sector": "电力设备", "current_value": 200_000, "target_weight": 0.10},
            {"ticker": "600519", "name": "贵州茅台", "sector": "食品饮料", "current_value": 100_000, "target_weight": 0.20},
            {"ticker": "000001", "name": "平安银行", "sector": "银行", "current_value": 50_000, "target_weight": 0.10},
        ]

        actions = compute_rebalance_actions(
            positions=positions,
            portfolio_value=portfolio_value,
            drift_threshold=0.05,
        )

        # 300750: 当前 20%, 目标 10% -> 超配, 应减仓
        action_300750 = [a for a in actions if a.ticker == "300750"]
        assert len(action_300750) >= 1
        assert action_300750[0].action in ("trim", "sell")
        assert action_300750[0].delta_weight < 0

        # 600519: 当前 10%, 目标 20% -> 低配, 应加仓
        action_600519 = [a for a in actions if a.ticker == "600519"]
        assert len(action_600519) >= 1
        assert action_600519[0].action in ("add", "buy")
        assert action_600519[0].delta_weight > 0

        # 渲染
        rendered_actions = format_rebalance_actions(actions, portfolio_value)
        assert "再平衡" in rendered_actions
        assert "300750" in rendered_actions

        # Step 2: performance_report
        positions_history = [
            {"date": "20260525", "portfolio_value": 980_000, "positions": []},
            {"date": "20260526", "portfolio_value": 990_000, "positions": []},
            {"date": "20260527", "portfolio_value": 995_000, "positions": []},
            {"date": "20260528", "portfolio_value": 1_005_000, "positions": []},
            {"date": "20260529", "portfolio_value": 1_000_000, "positions": []},
        ]
        trades = [
            {"date": "20260526", "ticker": "300750", "action": "buy", "pnl": 0.02, "strategy": "trend"},
            {"date": "20260527", "ticker": "600519", "action": "buy", "pnl": -0.01, "strategy": "fundamental"},
            {"date": "20260528", "ticker": "300750", "action": "sell", "pnl": 0.03, "strategy": "trend"},
        ]

        report = generate_performance_report(
            positions_history=positions_history,
            trades=trades,
            recommendations=[],
            tracking_history=[],
            period="weekly",
            end_date="20260529",
            benchmark_return=0.005,
        )

        assert report.total_return > 0  # 980K -> 1M = +2%
        assert report.total_trades == 3
        assert report.win_count == 2
        assert report.loss_count == 1
        assert report.sharpe_ratio != 0.0  # 有数据, 应有 Sharpe

        # 渲染报告
        rendered = render_performance_report(report)
        assert "绩效" in rendered
        assert "Sharpe" in rendered


# ============================================================================
# Scenario 8: preheat -> auto_screening (cache hit)
# ============================================================================


class TestPreheatCacheHit:
    """集成测试 8: preheat -> auto_screening (cache hit)。

    验证:
    - 缓存预热任务写入 EnhancedCache
    - 后续 auto_screening 读取时命中缓存
    """

    def test_preheat_then_cache_hit(self, tmp_path: Path) -> None:
        from src.data.cache_preheater import preheat_cache, PreheatStats

        # We patch at the source: src.data.enhanced_cache.get_enhanced_cache
        # because cache_preheater does local imports inside each _fetch_* function.

        # Strategy: mock _is_cached to simulate cached/uncached keys,
        # and mock the actual data-fetching functions to avoid network calls.

        with patch("src.data.cache_preheater._is_cached") as mock_is_cached:
            # daily_basic and daily_prices are "cached" -> will be skipped
            # industry_classify is NOT cached -> will attempt to fetch
            def is_cached_side_effect(key: str) -> bool:
                return key in ("preheat:daily_basic:20260601", "preheat:daily_prices:20260601")

            mock_is_cached.side_effect = is_cached_side_effect

            # Mock the actual fetch for industry_classify (the only uncached task)
            with patch("src.data.cache_preheater._fetch_industry_classify") as mock_fetch_industry:
                import pandas as pd

                mock_fetch_industry.return_value = pd.DataFrame({"ts_code": ["000001.SZ"], "industry": ["银行"]})

                # Mock get_enhanced_cache at source to avoid real DB access
                mock_cache = MagicMock()
                with patch("src.data.enhanced_cache.get_enhanced_cache", return_value=mock_cache):
                    stats = preheat_cache(
                        trade_date="20260601",
                        tasks=["daily_basic", "daily_prices", "industry_classify"],
                        force=False,
                    )

        assert stats.tasks_total == 3
        assert stats.cache_hits >= 2  # daily_basic + daily_prices skipped (cached)
        assert stats.tasks_skipped >= 2  # both counted as skipped


# ============================================================================
# Cross-module edge cases
# ============================================================================


class TestCrossModuleEdgeCases:
    """跨模块边界条件验证。"""

    def test_empty_recommendations_safe(self) -> None:
        """空推荐列表不应导致任何模块崩溃。"""
        from src.screening.industry_rotation import calculate_industry_rotation
        from src.screening.compare_tool import compare_tickers
        from src.screening.signal_decay_detector import detect_signal_decay
        from src.screening.custom_weights import reweight_recommendations, StrategyWeights
        from src.portfolio.rebalance_advisor import compute_rebalance_actions
        from src.portfolio.performance_report import generate_performance_report

        # 全部传空
        assert calculate_industry_rotation([], "20260601") == []
        assert generate_performance_report([], [], [], [], period="weekly") is not None
        assert compute_rebalance_actions([], 1_000_000) == []

        # compare 需要至少 2 只
        with pytest.raises(ValueError):
            compare_tickers(["300750"], [])

        # reweight 空列表
        result = reweight_recommendations([], StrategyWeights())
        assert result == []

    def test_nan_inf_propagation_blocked(self) -> None:
        """NaN / Inf 输入不应跨模块传播。"""
        import math

        from src.screening.conditional_order_advisor import compute_conditional_advice
        from src.portfolio.rebalance_advisor import compute_rebalance_actions

        # 条件单: NaN 价格历史
        advice = compute_conditional_advice(
            ticker="300750",
            current_price=float("nan"),
            price_history=[float("nan"), float("inf"), 10.0, 11.0, 12.0, 13.0, 14.0],
        )
        assert advice.degraded  # NaN current_price 触发降级
        assert not math.isnan(advice.current_price)  # 已被清理

        # 再平衡: NaN 权重
        positions = [
            {"ticker": "300750", "name": "宁德时代", "sector": "电力设备", "current_value": float("nan"), "target_weight": float("inf")},
        ]
        actions = compute_rebalance_actions(positions, 1_000_000)
        # 不应崩溃, NaN 被 safe 化
        assert isinstance(actions, list)

    def test_all_strategy_signals_none(self) -> None:
        """所有 strategy_signals 为 None/dict 缺失时, reweight 回退到原 score_b。"""
        from src.screening.custom_weights import StrategyWeights, reweight_recommendations

        recs = [
            {"ticker": "300750", "score_b": 0.50, "strategy_signals": None},
            {"ticker": "600519", "score_b": 0.30},  # 无 strategy_signals 字段
        ]
        result = reweight_recommendations(recs, StrategyWeights())
        assert len(result) == 2
        # 无信号时回退到原 score_b
        assert result[0]["score_b"] == 0.50
        assert result[1]["score_b"] == 0.30

    def test_recommendation_tracker_corrupt_history(self, tmp_reports: Path) -> None:
        """tracking_history.json 损坏时, 应优雅降级而非崩溃。"""
        from src.screening.recommendation_tracker import update_tracking_history
        from src.screening.winrate_dashboard import compute_winrate_dashboard

        # 写入损坏的 tracking_history
        history_path = tmp_reports / "tracking_history.json"
        history_path.write_text("{invalid json!!!", encoding="utf-8")

        # 应不崩溃
        updated = update_tracking_history(tmp_reports, trade_date="20260601")
        assert isinstance(updated, int)

        # dashboard 也应不崩溃
        summary = compute_winrate_dashboard(history_path)
        assert summary.total_days == 0  # 损坏 -> 空
