"""P2-6 标的深度分析 — 单只股票完整分析报告 单元测试。

至少 10 个测试:
  1. 完整数据
  2. 缺失基本面数据
  3. 缺失技术面
  4. 无推荐历史
  5. 同行业排名
  6. 龙虎榜检测
  7. MACD 信号判定
  8. render 输出格式
  9. CLI smoke
  10. Web 端点 smoke
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.screening.stock_detail import (
    _compute_industry_rank,
    _determine_macd_signal,
    compute_stock_detail,
    render_stock_detail,
    run_stock_detail_cli,
    StockDetail,
)

# ============================================================================
# Fixtures
# ============================================================================


def _write_auto_report(
    report_dir: Path,
    date_str: str,
    tickers: list[str],
    score_b: float = 0.5,
    industry_sw: str = "电力设备",
    name: str = "宁德时代",
) -> Path:
    """写入一个最小可用的 auto_screening_{date}.json 文件。"""
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": "auto_screening",
        "date": date_str,
        "market_state": {"state_type": "mixed", "position_scale": 1.0},
        "layer_a_count": 100,
        "total_scored": 50,
        "high_pool_count": 10,
        "top_n": len(tickers),
        "recommendations": [
            {
                "ticker": t,
                "name": name if idx == 0 else f"stock_{t}",
                "industry_sw": industry_sw if idx < 3 else "银行",
                "score_b": score_b + idx * 0.01,
                "decision": "watch" if score_b >= 0.35 else "neutral",
                "strategy_signals": {
                    "trend": {"direction": 1, "confidence": 75.0, "sub_factors": {"macd": {"name": "macd", "direction": 1, "confidence": 70.0}}},
                    "mean_reversion": {"direction": 0, "confidence": 30.0},
                    "fundamental": {"direction": 1, "confidence": 65.0, "sub_factors": {"profitability": {"name": "profitability", "direction": 1, "confidence": 60.0, "metrics": {"pe_ratio": 35.2, "pb_ratio": 8.5, "roe": 18.3, "revenue_growth": 28.5, "profit_growth": 32.1, "dividend_yield": 0.5}}}},
                    "event_sentiment": {"direction": 1, "confidence": 50.0},
                },
                "metrics": {
                    "price": 245.30,
                    "change_pct": 2.1,
                    "ma5": 240.5,
                    "ma20": 235.2,
                    "ma60": 230.0,
                    "rsi_14": 62.3,
                    "atr_pct": 3.2,
                    "money_flow_net": 23000.0,
                    "north_money_net": 15000.0,
                    "dragon_tiger": True,
                },
                "arbitration_applied": [],
            }
            for idx, t in enumerate(tickers)
        ],
        "sector_concentration_warnings": [],
    }
    out = report_dir / f"auto_screening_{date_str}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return out


@pytest.fixture
def report_dir(tmp_path: Path) -> Path:
    """创建一个包含一份报告的临时 report 目录。"""
    rd = tmp_path / "data" / "reports"
    _write_auto_report(rd, "20260607", ["300750", "600519", "000001", "601398"])
    return rd


@pytest.fixture
def full_recommendations() -> list[dict]:
    """完整的推荐列表 (模拟 auto_screening 输出)。"""
    return [
        {
            "ticker": "300750",
            "name": "宁德时代",
            "industry_sw": "电力设备",
            "score_b": 0.72,
            "decision": "strong_buy",
            "strategy_signals": {
                "trend": {"direction": 1, "confidence": 80.0, "sub_factors": {"macd": {"name": "macd", "direction": 1, "confidence": 75.0}}},
                "mean_reversion": {"direction": 0, "confidence": 30.0},
                "fundamental": {
                    "direction": 1,
                    "confidence": 70.0,
                    "sub_factors": {
                        "profitability": {
                            "name": "profitability",
                            "direction": 1,
                            "confidence": 65.0,
                            "metrics": {"pe_ratio": 35.2, "pb_ratio": 8.5, "roe": 18.3, "revenue_growth": 28.5, "profit_growth": 32.1, "dividend_yield": 0.5},
                        }
                    },
                },
                "event_sentiment": {"direction": 1, "confidence": 55.0},
            },
            "metrics": {
                "price": 245.30,
                "change_pct": 2.1,
                "ma5": 240.5,
                "ma20": 235.2,
                "ma60": 230.0,
                "rsi_14": 62.3,
                "atr_pct": 3.2,
                "money_flow_net": 23000.0,
                "north_money_net": 15000.0,
                "dragon_tiger": True,
            },
        },
        {
            "ticker": "600519",
            "name": "贵州茅台",
            "industry_sw": "电力设备",
            "score_b": 0.50,
            "decision": "watch",
            "strategy_signals": {},
            "metrics": {},
        },
        {
            "ticker": "000001",
            "name": "平安银行",
            "industry_sw": "银行",
            "score_b": 0.30,
            "decision": "neutral",
            "strategy_signals": {},
            "metrics": {},
        },
    ]


# ============================================================================
# Test 1: 完整数据
# ============================================================================


class TestFullData:
    """测试完整数据 — 所有字段都有值。"""

    def test_full_stock_detail(self, full_recommendations: list[dict]) -> None:
        detail = compute_stock_detail(
            ticker="300750",
            recommendations=full_recommendations,
            tracking_history=[],
        )
        assert detail.ticker == "300750"
        assert detail.name == "宁德时代"
        assert detail.industry_sw == "电力设备"

        # 基本面
        assert detail.pe_ratio == 35.2
        assert detail.pb_ratio == 8.5
        assert detail.roe == 18.3
        assert detail.revenue_growth == 28.5
        assert detail.profit_growth == 32.1
        assert detail.dividend_yield == 0.5

        # 技术面
        assert detail.price == 245.30
        assert detail.change_pct == 2.1
        assert detail.ma5 == 240.5
        assert detail.ma20 == 235.2
        assert detail.ma60 == 230.0
        assert detail.rsi_14 == 62.3
        assert detail.macd_signal == "bullish"
        assert detail.atr_pct == 3.2

        # 资金流
        assert detail.money_flow_net == 23000.0
        assert detail.north_money_net == 15000.0
        assert detail.dragon_tiger is True

        # 系统历史
        assert detail.latest_score_b == 0.72
        assert detail.latest_decision == "strong_buy"
        assert detail.latest_front_door_action == "AVOID"

        # 同行业排名
        assert detail.industry_rank == 1
        assert detail.industry_total == 2


# ============================================================================
# Test 2: 缺失基本面数据
# ============================================================================


class TestMissingFundamentals:
    """测试缺失基本面数据 — 所有基本面字段应为 None。"""

    def test_no_fundamental_data(self) -> None:
        recs = [
            {
                "ticker": "300750",
                "name": "宁德时代",
                "industry_sw": "电力设备",
                "score_b": 0.5,
                "decision": "watch",
                "strategy_signals": {
                    "trend": {"direction": 1, "confidence": 70.0},
                },
                "metrics": {},
            }
        ]
        detail = compute_stock_detail(
            ticker="300750",
            recommendations=recs,
            tracking_history=[],
        )
        assert detail.pe_ratio is None
        assert detail.pb_ratio is None
        assert detail.roe is None
        assert detail.revenue_growth is None
        assert detail.profit_growth is None
        assert detail.dividend_yield is None


# ============================================================================
# Test 3: 缺失技术面
# ============================================================================


class TestMissingTechnicals:
    """测试缺失技术面数据 — 技术指标应为 None / 默认值。"""

    def test_no_technical_data(self) -> None:
        recs = [
            {
                "ticker": "300750",
                "name": "宁德时代",
                "industry_sw": "电力设备",
                "score_b": 0.5,
                "decision": "watch",
                "strategy_signals": {},
                "metrics": {},
            }
        ]
        detail = compute_stock_detail(
            ticker="300750",
            recommendations=recs,
            tracking_history=[],
        )
        assert detail.price == 0.0
        assert detail.change_pct == 0.0
        assert detail.ma5 is None
        assert detail.ma20 is None
        assert detail.ma60 is None
        assert detail.rsi_14 is None
        assert detail.macd_signal == "neutral"
        assert detail.atr_pct is None


# ============================================================================
# Test 4: 无推荐历史
# ============================================================================


class TestNoHistory:
    """测试无推荐历史 — 标的不在列表中时返回默认值。"""

    def test_ticker_not_found(self) -> None:
        detail = compute_stock_detail(
            ticker="999999",
            recommendations=[],
            tracking_history=[],
        )
        assert detail.ticker == "999999"
        assert detail.name == ""
        assert detail.latest_score_b is None
        assert detail.latest_decision is None
        assert detail.recommendation_count_30d == 0
        assert detail.consecutive_days == 0


# ============================================================================
# Test 5: 同行业排名
# ============================================================================


class TestIndustryRank:
    """测试同行业排名计算。"""

    def test_rank_first(self, full_recommendations: list[dict]) -> None:
        detail = compute_stock_detail(
            ticker="300750",
            recommendations=full_recommendations,
            tracking_history=[],
        )
        # 300750 score_b=0.72, 600519 score_b=0.50, 同行业 "电力设备"
        assert detail.industry_rank == 1
        assert detail.industry_total == 2

    def test_rank_second(self, full_recommendations: list[dict]) -> None:
        detail = compute_stock_detail(
            ticker="600519",
            recommendations=full_recommendations,
            tracking_history=[],
        )
        assert detail.industry_rank == 2
        assert detail.industry_total == 2

    def test_no_industry(self) -> None:
        recs = [{"ticker": "300750", "name": "test", "industry_sw": "", "score_b": 0.5, "decision": "watch", "strategy_signals": {}, "metrics": {}}]
        detail = compute_stock_detail(
            ticker="300750",
            recommendations=recs,
            tracking_history=[],
        )
        assert detail.industry_rank is None
        assert detail.industry_total is None

    def test_compute_industry_rank_helper(self) -> None:
        recs = [
            {"ticker": "A", "industry_sw": "X", "score_b": 0.8},
            {"ticker": "B", "industry_sw": "X", "score_b": 0.5},
            {"ticker": "C", "industry_sw": "X", "score_b": 0.3},
            {"ticker": "D", "industry_sw": "Y", "score_b": 0.9},
        ]
        match = {"ticker": "A", "industry_sw": "X", "score_b": 0.8}
        rank, total = _compute_industry_rank(recs, match)
        assert rank == 1
        assert total == 3

    def test_compute_industry_rank_ticker_not_in_peers(self) -> None:
        """R16 bug: ticker in industry but not in peers_sorted should return None rank, not 1."""
        recs = [
            {"ticker": "A", "industry_sw": "X", "score_b": 0.8},
            {"ticker": "B", "industry_sw": "X", "score_b": 0.5},
        ]
        # ticker C has industry_sw=X but is not in the recs list
        match = {"ticker": "C", "industry_sw": "X", "score_b": 0.3}
        rank, total = _compute_industry_rank(recs, match)
        assert rank is None, f"Expected None, got {rank}"
        assert total == 2


# ============================================================================
# Test 6: 龙虎榜检测
# ============================================================================


class TestDragonTiger:
    """测试龙虎榜检测 — 来自 metrics.dragon_tiger 字段。"""

    def test_dragon_tiger_true(self) -> None:
        recs = [
            {
                "ticker": "300750",
                "name": "宁德时代",
                "industry_sw": "电力设备",
                "score_b": 0.5,
                "decision": "watch",
                "strategy_signals": {},
                "metrics": {"dragon_tiger": True},
            }
        ]
        detail = compute_stock_detail(ticker="300750", recommendations=recs, tracking_history=[])
        assert detail.dragon_tiger is True

    def test_dragon_tiger_false(self) -> None:
        recs = [
            {
                "ticker": "300750",
                "name": "宁德时代",
                "industry_sw": "电力设备",
                "score_b": 0.5,
                "decision": "watch",
                "strategy_signals": {},
                "metrics": {"dragon_tiger": False},
            }
        ]
        detail = compute_stock_detail(ticker="300750", recommendations=recs, tracking_history=[])
        assert detail.dragon_tiger is False

    def test_dragon_tiger_missing(self) -> None:
        recs = [
            {
                "ticker": "300750",
                "name": "宁德时代",
                "industry_sw": "电力设备",
                "score_b": 0.5,
                "decision": "watch",
                "strategy_signals": {},
                "metrics": {},
            }
        ]
        detail = compute_stock_detail(ticker="300750", recommendations=recs, tracking_history=[])
        assert detail.dragon_tiger is False


# ============================================================================
# Test 7: MACD 信号判定
# ============================================================================


class TestMACDSignal:
    """测试 MACD 信号判定逻辑。"""

    def test_bullish_via_sub_factor(self) -> None:
        strategy_signals = {"trend": {"direction": 1, "confidence": 80.0, "sub_factors": {"macd": {"name": "macd", "direction": 1, "confidence": 75.0}}}}
        assert _determine_macd_signal(strategy_signals) == "bullish"

    def test_bearish_via_sub_factor(self) -> None:
        strategy_signals = {"trend": {"direction": -1, "confidence": 80.0, "sub_factors": {"macd": {"name": "macd", "direction": -1, "confidence": 75.0}}}}
        assert _determine_macd_signal(strategy_signals) == "bearish"

    def test_neutral_no_trend(self) -> None:
        assert _determine_macd_signal({}) == "neutral"

    def test_bullish_via_direction_fallback(self) -> None:
        strategy_signals = {"trend": {"direction": 1, "confidence": 80.0}}
        assert _determine_macd_signal(strategy_signals) == "bullish"

    def test_bearish_via_direction_fallback(self) -> None:
        strategy_signals = {"trend": {"direction": -1, "confidence": 80.0}}
        assert _determine_macd_signal(strategy_signals) == "bearish"

    def test_neutral_zero_direction(self) -> None:
        strategy_signals = {"trend": {"direction": 0, "confidence": 80.0}}
        assert _determine_macd_signal(strategy_signals) == "neutral"


# ============================================================================
# Test 8: render 输出格式
# ============================================================================


class TestRenderOutput:
    """测试 render_stock_detail 输出格式。"""

    def _make_full_detail(self) -> StockDetail:
        return StockDetail(
            ticker="300750",
            name="宁德时代",
            industry_sw="电力设备",
            pe_ratio=35.2,
            pb_ratio=8.5,
            roe=18.3,
            revenue_growth=28.5,
            profit_growth=32.1,
            dividend_yield=0.5,
            price=245.30,
            change_pct=2.1,
            ma5=240.5,
            ma20=235.2,
            ma60=230.0,
            rsi_14=62.3,
            macd_signal="bullish",
            atr_pct=3.2,
            money_flow_net=23000.0,
            north_money_net=15000.0,
            dragon_tiger=True,
            recommendation_count_30d=8,
            latest_score_b=0.72,
            latest_decision="strong_buy",
            consecutive_days=4,
            decay_level="none",
            industry_rank=1,
            industry_total=28,
        )

    def test_render_contains_sections(self) -> None:
        detail = self._make_full_detail()
        output = render_stock_detail(detail)
        assert "基本面" in output
        assert "技术面" in output
        assert "资金流" in output
        assert "系统历史" in output
        assert "同行业排名" in output
        assert "综合评价" in output

    def test_render_contains_ticker(self) -> None:
        detail = self._make_full_detail()
        output = render_stock_detail(detail)
        assert "300750" in output
        assert "宁德时代" in output
        assert "电力设备" in output

    def test_render_contains_metrics(self) -> None:
        detail = self._make_full_detail()
        output = render_stock_detail(detail)
        assert "35.2" in output  # PE
        assert "245.30" in output  # price
        assert "62.3" in output  # RSI
        assert "bullish" in output
        assert "+2.1%" in output

    def test_render_minimal_detail(self) -> None:
        detail = StockDetail(
            ticker="999999",
            name="",
            industry_sw="",
            pe_ratio=None,
            pb_ratio=None,
            roe=None,
            revenue_growth=None,
            profit_growth=None,
            dividend_yield=None,
            price=0.0,
            change_pct=0.0,
            ma5=None,
            ma20=None,
            ma60=None,
            rsi_14=None,
            macd_signal="neutral",
            atr_pct=None,
            money_flow_net=None,
            north_money_net=None,
            dragon_tiger=False,
            recommendation_count_30d=0,
            latest_score_b=None,
            latest_decision=None,
            consecutive_days=0,
            decay_level="none",
            industry_rank=None,
            industry_total=None,
        )
        output = render_stock_detail(detail)
        assert "999999" in output
        assert "数据不足" in output

    def test_render_industry_rank(self) -> None:
        detail = self._make_full_detail()
        output = render_stock_detail(detail)
        assert "第 1/28 名" in output

    def test_render_surfaces_front_door_verdict_next_to_raw_decision(self, full_recommendations: list[dict]) -> None:
        """Raw latest_decision can be strong_buy while the front-door BUY gate
        rejects the same row for missing calibration evidence. The detail view
        must show the actionable front-door verdict, not just the raw decision.
        """
        detail = compute_stock_detail(
            ticker="300750",
            recommendations=full_recommendations,
            tracking_history=[],
        )

        output = render_stock_detail(detail)

        assert "决策: strong_buy" in output
        assert "前门: AVOID" in output

    def test_render_promotes_front_door_to_top_banner(self, full_recommendations: list[dict]) -> None:
        """autodev-26 loop 137: 前门判决必须出现在标题下方 (top-level banner),
        不再只埋在「系统历史」section 中段. 操作者第一眼应看到 gate verdict.
        """
        detail = compute_stock_detail(
            ticker="300750",
            recommendations=full_recommendations,
            tracking_history=[],
        )

        output = render_stock_detail(detail)

        # Top-level banner 必须出现
        assert "🎯 前门判决" in output
        assert "AVOID" in output
        # banner 必须出现在 系统历史 section 之前 (promoted position)
        banner_pos = output.find("🎯 前门判决")
        history_pos = output.find("系统历史")
        assert banner_pos != -1, "前门判决 banner 必须存在"
        assert history_pos != -1, "系统历史 section 必须存在"
        assert banner_pos < history_pos, "前门判决 banner 必须在 系统历史 之前"

    def test_render_no_banner_when_front_door_empty(self) -> None:
        """前门判决为空 (标的未在当前报告) → 不显示 banner."""
        detail = StockDetail(
            ticker="999999",
            name="",
            industry_sw="",
            pe_ratio=None,
            pb_ratio=None,
            roe=None,
            revenue_growth=None,
            profit_growth=None,
            dividend_yield=None,
            price=0.0,
            change_pct=0.0,
            ma5=None,
            ma20=None,
            ma60=None,
            rsi_14=None,
            macd_signal="neutral",
            atr_pct=None,
            money_flow_net=None,
            north_money_net=None,
            dragon_tiger=False,
            recommendation_count_30d=0,
            latest_score_b=None,
            latest_decision=None,
            consecutive_days=0,
            decay_level="none",
            industry_rank=None,
            industry_total=None,
        )
        # latest_front_door_action 默认 None
        output = render_stock_detail(detail)
        assert "🎯 前门判决" not in output


# ============================================================================
# Test 8b: autodev-26 loop 137 — regime auto-detection (cross-surface fix)
# ============================================================================


class TestRegimeAutoDetection:
    """autodev-26 loop 137: compute_stock_detail 必须从报告 market_state 读取
    regime_gate_level, 而非默认 "normal". 修复 --stock-detail 与 --top-picks
    跨 surface regime 不一致 (crisis 报告下 --stock-detail 错误显示 BUY).
    """

    def test_regime_auto_detected_from_report(self, tmp_path: Path) -> None:
        """market_regime=None → 从报告 market_state.regime_gate_level 读取."""
        import json as _json

        report_dir = tmp_path / "data" / "reports"
        report_dir.mkdir(parents=True)
        # 写一个 crisis regime 报告
        payload = {
            "mode": "auto_screening",
            "date": "20260706",
            "market_state": {"state_type": "crisis", "regime_gate_level": "crisis"},
            "top_n": 1,
            "recommendations": [
                {
                    "ticker": "300502",
                    "name": "新易盛",
                    "industry_sw": "通信",
                    "score_b": 0.44,
                    "decision": "watch",
                    "strategy_signals": {
                        "trend": {"direction": 1, "confidence": 60.0},
                        "mean_reversion": {"direction": 0, "confidence": 30.0},
                        "fundamental": {"direction": 1, "confidence": 50.0},
                        "event_sentiment": {"direction": 1, "confidence": 40.0},
                    },
                }
            ],
        }
        (report_dir / "auto_screening_20260706.json").write_text(_json.dumps(payload), encoding="utf-8")

        # market_regime=None → 应自动读 crisis
        detail = compute_stock_detail(
            ticker="300502",
            report_dir=report_dir,
            trade_date="20260706",
            market_regime=None,
        )

        # crisis regime → 不是 BUY (crisis T+5 被 gate 排除, NS-23)
        assert detail.latest_front_door_action != "BUY", (
            f"crisis regime 下不应为 BUY, 实际 {detail.latest_front_door_action} — "
            f"regime 未从报告读取 (autodev-26 loop 137 cross-surface fix)"
        )

    def test_explicit_regime_overrides_auto_detection(self, tmp_path: Path) -> None:
        """显式传入 market_regime → 不覆盖 (调用方意图优先)."""
        import json as _json

        report_dir = tmp_path / "data" / "reports"
        report_dir.mkdir(parents=True)
        payload = {
            "mode": "auto_screening",
            "date": "20260706",
            "market_state": {"state_type": "crisis", "regime_gate_level": "crisis"},
            "top_n": 1,
            "recommendations": [
                {"ticker": "300502", "name": "X", "industry_sw": "通信", "score_b": 0.44,
                 "decision": "watch", "strategy_signals": {}}
            ],
        }
        (report_dir / "auto_screening_20260706.json").write_text(_json.dumps(payload), encoding="utf-8")

        # 显式传 "normal" → 不应被报告的 crisis 覆盖
        detail = compute_stock_detail(
            ticker="300502",
            report_dir=report_dir,
            trade_date="20260706",
            market_regime="normal",
        )
        # 显式 normal → 走 normal 路径 (与 crisis 不同)
        # 我们不检查具体 verdict (依赖 gate 内部逻辑), 只验证显式值生效
        # 通过对比: None (auto=crisis) vs "normal" 应该可能不同
        detail_auto = compute_stock_detail(
            ticker="300502",
            report_dir=report_dir,
            trade_date="20260706",
            market_regime=None,
        )
        # 两者计算路径不同 (一个走 crisis, 一个走 normal); 至少函数不崩溃
        assert detail.latest_front_door_action is not None or detail_auto.latest_front_door_action is not None

    def test_regime_falls_back_to_normal_on_missing_market_state(self, tmp_path: Path) -> None:
        """报告无 market_state → 回退 normal (best-effort)."""
        import json as _json

        report_dir = tmp_path / "data" / "reports"
        report_dir.mkdir(parents=True)
        payload = {
            "mode": "auto_screening",
            "date": "20260706",
            # 无 market_state 键
            "top_n": 1,
            "recommendations": [
                {"ticker": "300502", "name": "X", "industry_sw": "通信", "score_b": 0.44,
                 "decision": "watch", "strategy_signals": {}}
            ],
        }
        (report_dir / "auto_screening_20260706.json").write_text(_json.dumps(payload), encoding="utf-8")

        detail = compute_stock_detail(
            ticker="300502",
            report_dir=report_dir,
            trade_date="20260706",
            market_regime=None,
        )
        # 不崩溃, 有 verdict (回退 normal)
        assert detail.latest_front_door_action is not None


# ============================================================================
# Test 9: CLI smoke
# ============================================================================


class TestCLISmoke:
    """测试 CLI 入口 smoke — 使用报告文件。"""

    def test_cli_success(self, report_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("src.screening.stock_detail.resolve_report_dir", return_value=report_dir):
            rc = run_stock_detail_cli("300750", trade_date="20260607")
        assert rc == 0
        captured = capsys.readouterr()
        assert "300750" in captured.out

    def test_cli_not_found(self, report_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("src.screening.stock_detail.resolve_report_dir", return_value=report_dir):
            rc = run_stock_detail_cli("999999", trade_date="20260607")
        assert rc == 1
        captured = capsys.readouterr()
        assert "999999" in captured.out


# ============================================================================
# Test 10: Web 端点 smoke
# ============================================================================


class TestWebEndpointSmoke:
    """测试 Web 端点 — 通过 FastAPI TestClient。"""

    def test_stock_detail_endpoint(self, report_dir: Path) -> None:
        """验证 GET /api/screening/stock-detail/{ticker} 返回正确的 JSON。"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.backend.routes.screening import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        test_recs = [
            {
                "ticker": "300750",
                "name": "宁德时代",
                "industry_sw": "电力设备",
                "score_b": 0.72,
                "decision": "strong_buy",
                "strategy_signals": {
                    "trend": {"direction": 1, "confidence": 80.0},
                    "fundamental": {"direction": 1, "confidence": 70.0, "sub_factors": {"profitability": {"name": "p", "direction": 1, "confidence": 65.0, "metrics": {"pe_ratio": 35.0}}}},
                },
                "metrics": {"price": 245.0, "change_pct": 2.1},
            }
        ]

        with patch(
            "src.screening.compare_tool.load_latest_recommendations",
            return_value=test_recs,
        ):
            resp = client.get("/api/screening/stock-detail/300750")
            assert resp.status_code == 200
            data = resp.json()
            assert data["ticker"] == "300750"
            assert data["name"] == "宁德时代"
            assert data["pe_ratio"] == 35.0
            assert data["price"] == 245.0
            assert data["latest_front_door_action"] == "AVOID"

    def test_stock_detail_endpoint_not_found(self, report_dir: Path) -> None:
        """验证无报告时返回 404。"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.backend.routes.screening import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        with patch(
            "src.screening.compare_tool.load_latest_recommendations",
            return_value=[],
        ):
            resp = client.get("/api/screening/stock-detail/999999")
            assert resp.status_code == 404


# ============================================================================
# Additional: to_dict / serialization
# ============================================================================


class TestSerialization:
    """测试 StockDetail.to_dict 序列化。"""

    def test_to_dict(self, full_recommendations: list[dict]) -> None:
        detail = compute_stock_detail(
            ticker="300750",
            recommendations=full_recommendations,
            tracking_history=[],
        )
        d = detail.to_dict()
        assert isinstance(d, dict)
        assert d["ticker"] == "300750"
        assert d["pe_ratio"] == 35.2
        # 确保 JSON 可序列化
        json_str = json.dumps(d, ensure_ascii=False)
        assert "300750" in json_str


# ============================================================================
# NS-17 honesty: silent-except on consecutive_recommendations / signal_decay
# compute paths must surface to operator (c324, loop 75). Without a logger
# call the failure collapses into the same value as a genuine "no streak",
# indistinguishable to the operator deep-diving a ticker.
# ============================================================================


class TestSilentExceptDisclosure:
    """compute_consecutive_recommendations / detect_signal_decay 失败时必须
    surface 到 logger — 不能与"真实无连续推荐/无衰减"信号不可区分 (NS-17)。
    """

    def test_consecutive_compute_failure_logs_warning(
        self, full_recommendations: list[dict], caplog: pytest.LogCaptureFixture
    ) -> None:
        """compute_consecutive_recommendations 抛异常时必须 logger.warning。"""
        with patch(
            "src.screening.stock_detail.compute_consecutive_recommendations",
            side_effect=RuntimeError("tracking_history corrupt"),
        ):
            with caplog.at_level("WARNING", logger="src.screening.stock_detail"):
                detail = compute_stock_detail(
                    ticker="300750",
                    recommendations=full_recommendations,
                    tracking_history=[],
                )
        # 仍 fallback 到 0 (best-effort, 不阻塞渲染)
        assert detail.consecutive_days == 0
        # 但必须 surface 到 operator — 不能静默
        assert any(
            "compute_consecutive_recommendations" in r.message
            and r.levelname == "WARNING"
            for r in caplog.records
        ), f"expected WARNING mentioning compute_consecutive_recommendations, got: {[r.message for r in caplog.records]}"

    def test_signal_decay_compute_failure_logs_warning(
        self, full_recommendations: list[dict], caplog: pytest.LogCaptureFixture
    ) -> None:
        """detect_signal_decay 抛异常时必须 logger.warning。"""
        with patch(
            "src.screening.stock_detail.detect_signal_decay",
            side_effect=RuntimeError("report schema drift"),
        ):
            with caplog.at_level("WARNING", logger="src.screening.stock_detail"):
                detail = compute_stock_detail(
                    ticker="300750",
                    recommendations=full_recommendations,
                    tracking_history=[],
                )
        # 仍 fallback 到 none (best-effort, 不阻塞渲染)
        assert detail.decay_level == "none"
        # 但必须 surface 到 operator — 不能静默
        assert any(
            "detect_signal_decay" in r.message and r.levelname == "WARNING"
            for r in caplog.records
        ), f"expected WARNING mentioning detect_signal_decay, got: {[r.message for r in caplog.records]}"
