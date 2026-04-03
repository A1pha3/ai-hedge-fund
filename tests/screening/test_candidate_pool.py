"""Layer A 候选池构建器单元测试"""

import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.screening.candidate_pool import (
    _estimate_trading_days,
    _estimate_amount_from_daily_basic,
    _enforce_tushare_daily_rate_limit,
    _get_avg_amount_20d_map,
    _is_disclosure_window,
    add_cooldown,
    build_candidate_pool,
    build_candidate_pool_with_shadow,
    get_cooled_tickers,
    load_cooldown_registry,
    save_cooldown_registry,
)
from src.screening.models import CandidateStock
import src.screening.candidate_pool as candidate_pool_module


# ============================================================================
# Fixtures
# ============================================================================

def _make_stock_basic_df(rows: list[dict]) -> pd.DataFrame:
    """构造 stock_basic 格式的 DataFrame"""
    defaults = {
        "ts_code": "", "symbol": "", "name": "", "area": "",
        "industry": "", "market": "主板", "list_date": "20100101",
        "list_status": "L", "is_hs": "N",
    }
    data = []
    for r in rows:
        row = {**defaults, **r}
        data.append(row)
    return pd.DataFrame(data)


def _make_daily_basic_df(rows: list[dict]) -> pd.DataFrame:
    """构造 daily_basic 格式的 DataFrame"""
    defaults = {
        "ts_code": "", "trade_date": "20260305", "close": 10.0,
        "turnover_rate": 1.0, "pe": 15.0, "pe_ttm": 14.0,
        "pb": 1.5, "ps": 2.0, "ps_ttm": 1.8,
        "dv_ratio": 2.0, "dv_ttm": 2.0,
        "total_share": 100000, "float_share": 80000,
        "free_share": 60000, "total_mv": 1000000, "circ_mv": 800000,
    }
    data = [{**defaults, **r} for r in rows]
    return pd.DataFrame(data)


# ============================================================================
# 单元测试
# ============================================================================

class TestHelpers:
    def test_default_candidate_pool_size_is_300(self):
        assert candidate_pool_module.MAX_CANDIDATE_POOL_SIZE == 300

    def test_estimate_trading_days(self):
        """上市日距今的交易日估算"""
        # 100 自然日 ≈ 70 交易日
        result = _estimate_trading_days("20260101", "20260411")
        assert result == 70

    def test_estimate_trading_days_invalid(self):
        """无效日期返回 0"""
        assert _estimate_trading_days("", "20260305") == 0
        assert _estimate_trading_days("invalid", "20260305") == 0

    def test_disclosure_window(self):
        """财报窗口期检测"""
        assert _is_disclosure_window("20260401") is True
        assert _is_disclosure_window("20260815") is True
        assert _is_disclosure_window("20261020") is True
        assert _is_disclosure_window("20260601") is False
        assert _is_disclosure_window("20260115") is False

    def test_estimate_amount_from_daily_basic(self):
        """用换手率和流通市值估算当日成交额。"""
        row = pd.Series({"turnover_rate": 2.5, "circ_mv": 200000.0})
        assert _estimate_amount_from_daily_basic(row) == 5000.0

    def test_tushare_rate_limit_skips_sleep_when_batch_is_already_slow(self):
        """如果批次本身已经耗时足够，不应再额外 sleep。"""
        with patch("src.screening.candidate_pool.perf_counter", return_value=20.0), \
             patch("src.screening.candidate_pool.time.sleep") as mock_sleep:
            slept = _enforce_tushare_daily_rate_limit(batch_started_at=0.0, processed_calls=50, has_more_batches=True)

        assert slept == 0.0
        mock_sleep.assert_not_called()

    def test_tushare_rate_limit_only_sleeps_remaining_budget(self):
        """如果批次运行较快，只补足剩余限流窗口，不再固定睡满。"""
        with patch("src.screening.candidate_pool.perf_counter", return_value=10.0), \
             patch("src.screening.candidate_pool.time.sleep") as mock_sleep:
            slept = _enforce_tushare_daily_rate_limit(batch_started_at=0.0, processed_calls=50, has_more_batches=True)

        assert slept == pytest.approx(5.0)
        mock_sleep.assert_called_once_with(pytest.approx(5.0))

    def test_get_avg_amount_20d_map_uses_market_daily_batches(self):
        """应按交易日批量拉取 daily，再本地聚合目标股票的 20 日均额。"""
        mock_pro = MagicMock()
        with patch(
            "src.screening.candidate_pool._cached_tushare_dataframe_call",
            side_effect=[
                pd.DataFrame([
                    {"cal_date": "20260303"},
                    {"cal_date": "20260304"},
                ]),
                pd.DataFrame([
                    {"ts_code": "000001.SZ", "amount": 10000.0},
                    {"ts_code": "000002.SZ", "amount": 20000.0},
                ]),
                pd.DataFrame([
                    {"ts_code": "000001.SZ", "amount": 30000.0},
                    {"ts_code": "000002.SZ", "amount": 40000.0},
                ]),
            ],
        ) as mock_cached_call:
            result = _get_avg_amount_20d_map(mock_pro, ["000001.SZ", "000002.SZ"], "20260304", lookback_sessions=2)

        assert result["000001.SZ"] == pytest.approx(2000.0)
        assert result["000002.SZ"] == pytest.approx(3000.0)
        assert mock_cached_call.call_count == 3


class TestCooldownRegistry:
    def test_cooldown_lifecycle(self, tmp_path):
        """冷却期注册表的完整生命周期"""
        cooldown_file = tmp_path / "cooldown_registry.json"

        with patch("src.screening.candidate_pool._COOLDOWN_FILE", cooldown_file):
            # 初始为空
            registry = load_cooldown_registry()
            assert registry == {}

            # 添加冷却期
            add_cooldown("000001", "20260301", days=15)
            registry = load_cooldown_registry()
            assert "000001" in registry

            # 在冷却期内
            cooled = get_cooled_tickers("20260305")
            assert "000001" in cooled

            # 冷却期过后
            cooled = get_cooled_tickers("20260401")
            assert "000001" not in cooled

    def test_cooldown_expiry_cleanup(self, tmp_path):
        """过期冷却记录自动清理"""
        cooldown_file = tmp_path / "cooldown_registry.json"

        with patch("src.screening.candidate_pool._COOLDOWN_FILE", cooldown_file):
            # 手动写入已过期的记录
            save_cooldown_registry({"000001": "20260101", "000002": "20260401"})

            # 查询时自动清理过期的 000001
            cooled = get_cooled_tickers("20260305")
            assert "000001" not in cooled
            assert "000002" in cooled

            # 验证注册表已清理
            registry = load_cooldown_registry()
            assert "000001" not in registry
            assert "000002" in registry


class TestExcludeRules:
    """测试各项排除规则"""

    @patch("src.screening.candidate_pool.get_sw_industry_classification")
    @patch("src.screening.candidate_pool._get_avg_amount_20d")
    @patch("src.screening.candidate_pool.get_daily_basic_batch")
    @patch("src.screening.candidate_pool.get_limit_list")
    @patch("src.screening.candidate_pool.get_suspend_list")
    @patch("src.screening.candidate_pool.get_all_stock_basic")
    @patch("src.screening.candidate_pool._get_pro")
    def _run_build(self, mock_pro, mock_basic, mock_suspend, mock_limit,
                   mock_daily, mock_avg_amt, mock_sw, stocks, **overrides):
        """辅助方法：用 mock 数据运行 build_candidate_pool"""
        mock_pro.return_value = MagicMock()
        mock_basic.return_value = _make_stock_basic_df(stocks)
        mock_suspend.return_value = overrides.get("suspend_df", pd.DataFrame())
        mock_limit.return_value = overrides.get("limit_df", pd.DataFrame())
        mock_daily.return_value = overrides.get("daily_df", _make_daily_basic_df(
            [{"ts_code": s["ts_code"], "total_mv": 1000000} for s in stocks]
        ))
        # 默认所有标的的成交额都满足条件
        mock_avg_amt.return_value = overrides.get("avg_amount", 10000.0)
        mock_sw.return_value = overrides.get("sw_map", {})

        with patch("src.screening.candidate_pool._SNAPSHOT_DIR", Path(tempfile.mkdtemp())):
            with patch("src.screening.candidate_pool._get_avg_amount_20d_map", return_value=overrides.get("avg_amount_map", {})):
                return build_candidate_pool("20260305", use_cache=False, cooldown_tickers=overrides.get("cooldown", set()))

    def test_exclude_st(self):
        """ST 标的被正确过滤"""
        stocks = [
            {"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行"},
            {"ts_code": "000002.SZ", "symbol": "000002", "name": "ST万科"},
            {"ts_code": "000003.SZ", "symbol": "000003", "name": "*ST退市股"},
        ]
        result = self._run_build(stocks=stocks)
        tickers = {c.ticker for c in result}
        assert "000001" in tickers
        assert "000002" not in tickers
        assert "000003" not in tickers

    def test_exclude_new_stock(self):
        """上市不满 60 交易日的标的被过滤"""
        stocks = [
            {"ts_code": "000001.SZ", "symbol": "000001", "name": "老股", "list_date": "20100101"},
            {"ts_code": "000099.SZ", "symbol": "000099", "name": "新股", "list_date": "20260301"},
        ]
        result = self._run_build(stocks=stocks)
        tickers = {c.ticker for c in result}
        assert "000001" in tickers
        assert "000099" not in tickers

    def test_exclude_low_liquidity(self):
        """成交额 < 5000 万的标的被过滤"""
        stocks = [
            {"ts_code": "000001.SZ", "symbol": "000001", "name": "够流动"},
        ]
        # 高于阈值：保留
        result = self._run_build(stocks=stocks, avg_amount_map={"000001.SZ": 10000.0}, avg_amount=10000.0)
        assert len(result) == 1

        # 低于阈值：过滤
        result = self._run_build(stocks=stocks, avg_amount_map={"000001.SZ": 3000.0}, avg_amount=3000.0)
        assert len(result) == 0

    def test_exclude_limit_up(self):
        """当日涨停的标的被过滤"""
        stocks = [
            {"ts_code": "000001.SZ", "symbol": "000001", "name": "正常股"},
            {"ts_code": "000002.SZ", "symbol": "000002", "name": "涨停股"},
        ]
        limit_df = pd.DataFrame([
            {"ts_code": "000002.SZ", "limit": "U", "trade_date": "20260305"},
        ])
        result = self._run_build(stocks=stocks, limit_df=limit_df)
        tickers = {c.ticker for c in result}
        assert "000001" in tickers
        assert "000002" not in tickers

    def test_exclude_bj(self):
        """北交所标的被过滤"""
        stocks = [
            {"ts_code": "000001.SZ", "symbol": "000001", "name": "深市", "market": "主板"},
            {"ts_code": "600001.SH", "symbol": "600001", "name": "沪市", "market": "主板"},
            {"ts_code": "430001.BJ", "symbol": "430001", "name": "北交所A", "market": "BJ"},
            {"ts_code": "830001.BJ", "symbol": "830001", "name": "北交所B", "market": "BJ"},
            {"ts_code": "920001.BJ", "symbol": "920001", "name": "北交所C", "market": "北交所"},
            {"ts_code": "920375.BJ", "symbol": "920375", "name": "北交所D", "market": "主板"},
        ]
        result = self._run_build(stocks=stocks)
        tickers = {c.ticker for c in result}
        assert "000001" in tickers
        assert "600001" in tickers
        assert "430001" not in tickers
        assert "830001" not in tickers
        assert "920001" not in tickers
        assert "920375" not in tickers

    def test_cooldown(self):
        """冷却期内的标的被过滤，到期后解除"""
        stocks = [
            {"ts_code": "000001.SZ", "symbol": "000001", "name": "冷却中"},
            {"ts_code": "000002.SZ", "symbol": "000002", "name": "正常"},
        ]
        # 000001 在冷却期内
        result = self._run_build(stocks=stocks, cooldown={"000001"})
        tickers = {c.ticker for c in result}
        assert "000001" not in tickers
        assert "000002" in tickers

        # 冷却期解除
        result = self._run_build(stocks=stocks, cooldown=set())
        tickers = {c.ticker for c in result}
        assert "000001" in tickers

    def test_exclude_suspended(self):
        """当日停牌的标的被过滤"""
        stocks = [
            {"ts_code": "000001.SZ", "symbol": "000001", "name": "正常"},
            {"ts_code": "000003.SZ", "symbol": "000003", "name": "停牌"},
        ]
        suspend_df = pd.DataFrame([
            {"ts_code": "000003.SZ", "trade_date": "20260305", "suspend_timing": "全天"},
        ])
        result = self._run_build(stocks=stocks, suspend_df=suspend_df)
        tickers = {c.ticker for c in result}
        assert "000001" in tickers
        assert "000003" not in tickers

    def test_output_format(self):
        """输出 CandidateStock 格式正确"""
        stocks = [
            {"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行",
             "industry": "银行", "list_date": "19910403"},
        ]
        result = self._run_build(stocks=stocks, sw_map={"000001.SZ": "银行"})
        assert len(result) == 1
        c = result[0]
        assert isinstance(c, CandidateStock)
        assert c.ticker == "000001"
        assert c.name == "平安银行"
        assert c.industry_sw == "银行"
        assert c.listing_date == "19910403"
        # 可以序列化为 JSON
        d = c.model_dump()
        assert "ticker" in d
        assert "market_cap" in d
        assert "avg_volume_20d" in d

    def test_disclosure_risk_marking(self):
        """4月/8月/10月标记为财报窗口期"""
        stocks = [
            {"ts_code": "000001.SZ", "symbol": "000001", "name": "测试"},
        ]
        # 4月是财报窗口期
        with patch("src.screening.candidate_pool._SNAPSHOT_DIR", Path(tempfile.mkdtemp())):
            with patch("src.screening.candidate_pool.get_all_stock_basic") as mock_basic, \
                 patch("src.screening.candidate_pool._get_pro") as mock_pro, \
                 patch("src.screening.candidate_pool.get_suspend_list") as mock_suspend, \
                 patch("src.screening.candidate_pool.get_limit_list") as mock_limit, \
                 patch("src.screening.candidate_pool.get_daily_basic_batch") as mock_daily, \
                 patch("src.screening.candidate_pool._get_avg_amount_20d") as mock_avg, \
                 patch("src.screening.candidate_pool.get_sw_industry_classification") as mock_sw:
                mock_pro.return_value = MagicMock()
                mock_basic.return_value = _make_stock_basic_df(stocks)
                mock_suspend.return_value = pd.DataFrame()
                mock_limit.return_value = pd.DataFrame()
                mock_daily.return_value = _make_daily_basic_df([{"ts_code": "000001.SZ"}])
                mock_avg.return_value = 10000.0
                mock_sw.return_value = {}

                result = build_candidate_pool("20260415", use_cache=False)
                assert result[0].disclosure_risk is True

                result = build_candidate_pool("20260615", use_cache=False)
                assert result[0].disclosure_risk is False

    def test_exclude_low_estimated_liquidity_before_20d_fetch(self):
        """低当日估算流动性的标的应在逐只计算 20 日均额前被过滤。"""
        stocks = [
            {"ts_code": "000001.SZ", "symbol": "000001", "name": "高流动性"},
            {"ts_code": "000002.SZ", "symbol": "000002", "name": "低流动性"},
        ]

        daily_df = _make_daily_basic_df([
            {"ts_code": "000001.SZ", "turnover_rate": 4.0, "circ_mv": 200000.0},
            {"ts_code": "000002.SZ", "turnover_rate": 1.0, "circ_mv": 100000.0},
        ])

        result = self._run_build(stocks=stocks, daily_df=daily_df, avg_amount_map={"000001.SZ": 10000.0}, avg_amount=10000.0)
        tickers = {candidate.ticker for candidate in result}

        assert "000001" in tickers
        assert "000002" not in tickers

    def test_candidate_pool_is_capped_by_default(self):
        """候选池默认应被截断到可控规模。"""
        stocks = [
            {"ts_code": f"{i:06d}.SZ", "symbol": f"{i:06d}", "name": f"股票{i}"}
            for i in range(250)
        ]

        with patch("src.screening.candidate_pool.MAX_CANDIDATE_POOL_SIZE", 200):
            result = self._run_build(
                stocks=stocks,
                avg_amount=10000.0,
                avg_amount_map={f"{i:06d}.SZ": 10000.0 for i in range(250)},
            )

        assert len(result) == 200

    @patch("src.screening.candidate_pool.get_sw_industry_classification")
    @patch("src.screening.candidate_pool.get_daily_basic_batch")
    @patch("src.screening.candidate_pool.get_limit_list")
    @patch("src.screening.candidate_pool.get_suspend_list")
    @patch("src.screening.candidate_pool.get_all_stock_basic")
    @patch("src.screening.candidate_pool._get_pro")
    def test_candidate_pool_shadow_recall_selects_corridor_and_rebucket_lanes(
        self,
        mock_pro,
        mock_basic,
        mock_suspend,
        mock_limit,
        mock_daily,
        mock_sw,
    ):
        stocks = [
            {"ts_code": f"{i:06d}.SZ", "symbol": f"{i:06d}", "name": f"股票{i}"}
            for i in range(305)
        ]
        avg_amount_map = {f"{i:06d}.SZ": float(100_000 - i) for i in range(300)}
        avg_amount_map["000300.SZ"] = 15_000.0
        avg_amount_map["000301.SZ"] = 45_000.0
        avg_amount_map["000302.SZ"] = 18_000.0
        avg_amount_map["000303.SZ"] = 9_000.0
        avg_amount_map["000304.SZ"] = 4_500.0

        snapshot_dir = Path(tempfile.mkdtemp())
        mock_pro.return_value = MagicMock()
        mock_basic.return_value = _make_stock_basic_df(stocks)
        mock_suspend.return_value = pd.DataFrame()
        mock_limit.return_value = pd.DataFrame()
        mock_daily.return_value = _make_daily_basic_df(
            [{"ts_code": stock["ts_code"], "total_mv": 1_000_000} for stock in stocks]
        )
        mock_sw.return_value = {}

        with patch("src.screening.candidate_pool._SNAPSHOT_DIR", snapshot_dir), \
             patch("src.screening.candidate_pool.MAX_CANDIDATE_POOL_SIZE", 300), \
             patch("src.screening.candidate_pool._get_avg_amount_20d_map", return_value=avg_amount_map):
            selected_candidates, shadow_candidates, shadow_summary = build_candidate_pool_with_shadow(
                "20260305",
                use_cache=False,
                cooldown_tickers=set(),
            )

        assert len(selected_candidates) == 300
        assert [candidate.ticker for candidate in shadow_candidates] == ["000302", "000300", "000301"]
        assert [candidate.candidate_pool_lane for candidate in shadow_candidates] == [
            "layer_a_liquidity_corridor",
            "layer_a_liquidity_corridor",
            "post_gate_liquidity_competition",
        ]
        assert shadow_summary["lane_counts"] == {
            "layer_a_liquidity_corridor": 2,
            "post_gate_liquidity_competition": 1,
        }
        assert shadow_summary["selected_tickers"] == ["000302", "000300", "000301"]

    def test_candidate_pool_shadow_recall_preserves_cached_main_pool_when_shadow_backfill_unavailable(self):
        snapshot_dir = Path(tempfile.mkdtemp())
        cached_candidates = [
            CandidateStock(
                ticker="000001",
                name="缓存主池",
                industry_sw="银行",
                avg_volume_20d=12345.0,
                market_cap=100.0,
                listing_date="20100101",
            )
        ]
        snapshot_path = snapshot_dir / "candidate_pool_20260305_top300.json"
        snapshot_path.write_text(json.dumps([candidate.model_dump() for candidate in cached_candidates], ensure_ascii=False, indent=2), encoding="utf-8")

        with patch("src.screening.candidate_pool._SNAPSHOT_DIR", snapshot_dir), \
             patch("src.screening.candidate_pool._compute_candidate_pool_candidates", return_value=[]):
            selected_candidates, shadow_candidates, shadow_summary = build_candidate_pool_with_shadow("20260305", use_cache=True)

        assert [candidate.ticker for candidate in selected_candidates] == ["000001"]
        assert shadow_candidates == []
        assert shadow_summary["selected_count"] == 1
        assert shadow_summary["lane_counts"] == {}
        assert (snapshot_dir / "candidate_pool_20260305_top300_shadow.json").exists()

    @patch("src.screening.candidate_pool.get_sw_industry_classification")
    @patch("src.screening.candidate_pool.get_daily_basic_batch")
    @patch("src.screening.candidate_pool.get_limit_list")
    @patch("src.screening.candidate_pool.get_suspend_list")
    @patch("src.screening.candidate_pool.get_all_stock_basic")
    @patch("src.screening.candidate_pool._get_pro")
    def test_candidate_pool_shadow_recall_prioritizes_lane_focus_tickers(
        self,
        mock_pro,
        mock_basic,
        mock_suspend,
        mock_limit,
        mock_daily,
        mock_sw,
    ):
        stocks = [
            {"ts_code": f"{i:06d}.SZ", "symbol": f"{i:06d}", "name": f"股票{i}"}
            for i in range(304)
        ]
        avg_amount_map = {f"{i:06d}.SZ": float(100_000 - i) for i in range(300)}
        avg_amount_map["000300.SZ"] = 19_000.0
        avg_amount_map["000301.SZ"] = 17_000.0
        avg_amount_map["000302.SZ"] = 62_000.0
        avg_amount_map["000303.SZ"] = 58_000.0

        snapshot_dir = Path(tempfile.mkdtemp())
        mock_pro.return_value = MagicMock()
        mock_basic.return_value = _make_stock_basic_df(stocks)
        mock_suspend.return_value = pd.DataFrame()
        mock_limit.return_value = pd.DataFrame()
        mock_daily.return_value = _make_daily_basic_df(
            [{"ts_code": stock["ts_code"], "total_mv": 1_000_000} for stock in stocks]
        )
        mock_sw.return_value = {}

        with patch("src.screening.candidate_pool._SNAPSHOT_DIR", snapshot_dir), \
             patch("src.screening.candidate_pool.MAX_CANDIDATE_POOL_SIZE", 300), \
             patch("src.screening.candidate_pool.SHADOW_LIQUIDITY_CORRIDOR_MAX_TICKERS", 1), \
             patch("src.screening.candidate_pool.SHADOW_REBUCKET_MAX_TICKERS", 1), \
             patch("src.screening.candidate_pool.SHADOW_FOCUS_LIQUIDITY_CORRIDOR_TICKERS", {"000301"}), \
             patch("src.screening.candidate_pool.SHADOW_FOCUS_REBUCKET_TICKERS", {"000303"}), \
             patch("src.screening.candidate_pool._get_avg_amount_20d_map", return_value=avg_amount_map):
            _, shadow_candidates, shadow_summary = build_candidate_pool_with_shadow(
                "20260305",
                use_cache=False,
                cooldown_tickers=set(),
            )

        assert [candidate.ticker for candidate in shadow_candidates] == ["000301", "000303"]
        assert shadow_summary["focus_tickers"] == ["000301", "000303"]
        assert [entry["shadow_focus_selected"] for entry in shadow_summary["tickers"]] == [True, True]

    @patch("src.screening.candidate_pool.get_sw_industry_classification")
    @patch("src.screening.candidate_pool.get_daily_basic_batch")
    @patch("src.screening.candidate_pool.get_limit_list")
    @patch("src.screening.candidate_pool.get_suspend_list")
    @patch("src.screening.candidate_pool.get_all_stock_basic")
    @patch("src.screening.candidate_pool._get_pro")
    def test_candidate_pool_shadow_recall_focus_uses_distinct_shadow_cache(
        self,
        mock_pro,
        mock_basic,
        mock_suspend,
        mock_limit,
        mock_daily,
        mock_sw,
    ):
        stocks = [
            {"ts_code": f"{i:06d}.SZ", "symbol": f"{i:06d}", "name": f"股票{i}"}
            for i in range(304)
        ]
        avg_amount_map = {f"{i:06d}.SZ": float(100_000 - i) for i in range(300)}
        avg_amount_map["000300.SZ"] = 19_000.0
        avg_amount_map["000301.SZ"] = 17_000.0
        avg_amount_map["000302.SZ"] = 62_000.0
        avg_amount_map["000303.SZ"] = 58_000.0

        snapshot_dir = Path(tempfile.mkdtemp())
        mock_pro.return_value = MagicMock()
        mock_basic.return_value = _make_stock_basic_df(stocks)
        mock_suspend.return_value = pd.DataFrame()
        mock_limit.return_value = pd.DataFrame()
        mock_daily.return_value = _make_daily_basic_df(
            [{"ts_code": stock["ts_code"], "total_mv": 1_000_000} for stock in stocks]
        )
        mock_sw.return_value = {}

        with patch("src.screening.candidate_pool._SNAPSHOT_DIR", snapshot_dir), \
             patch("src.screening.candidate_pool.MAX_CANDIDATE_POOL_SIZE", 300), \
             patch("src.screening.candidate_pool.SHADOW_LIQUIDITY_CORRIDOR_MAX_TICKERS", 1), \
             patch("src.screening.candidate_pool.SHADOW_REBUCKET_MAX_TICKERS", 1), \
             patch("src.screening.candidate_pool._get_avg_amount_20d_map", return_value=avg_amount_map):
            _, baseline_shadow_candidates, baseline_shadow_summary = build_candidate_pool_with_shadow(
                "20260305",
                use_cache=False,
                cooldown_tickers=set(),
            )

            with patch("src.screening.candidate_pool.SHADOW_FOCUS_LIQUIDITY_CORRIDOR_TICKERS", {"000301"}), \
                 patch("src.screening.candidate_pool.SHADOW_FOCUS_REBUCKET_TICKERS", {"000303"}):
                _, focused_shadow_candidates, focused_shadow_summary = build_candidate_pool_with_shadow(
                    "20260305",
                    use_cache=True,
                    cooldown_tickers=set(),
                )
                focused_shadow_snapshot_path = candidate_pool_module._candidate_pool_shadow_snapshot_path("20260305")

        assert [candidate.ticker for candidate in baseline_shadow_candidates] == ["000300", "000302"]
        assert baseline_shadow_summary["focus_signature"] == ""
        assert [candidate.ticker for candidate in focused_shadow_candidates] == ["000301", "000303"]
        assert focused_shadow_summary["focus_tickers"] == ["000301", "000303"]
        assert focused_shadow_summary["focus_signature"]
        assert focused_shadow_snapshot_path.exists()

    @patch("src.screening.candidate_pool.get_sw_industry_classification")
    @patch("src.screening.candidate_pool.get_daily_basic_batch")
    @patch("src.screening.candidate_pool.get_limit_list")
    @patch("src.screening.candidate_pool.get_suspend_list")
    @patch("src.screening.candidate_pool.get_all_stock_basic")
    @patch("src.screening.candidate_pool._get_pro")
    def test_candidate_pool_cache_is_scoped_by_pool_size(
        self,
        mock_pro,
        mock_basic,
        mock_suspend,
        mock_limit,
        mock_daily,
        mock_sw,
    ):
        """不同候选池规模不应复用同一个日期缓存。"""
        stocks = [
            {"ts_code": f"{i:06d}.SZ", "symbol": f"{i:06d}", "name": f"股票{i}"}
            for i in range(250)
        ]
        snapshot_dir = Path(tempfile.mkdtemp())

        mock_pro.return_value = MagicMock()
        mock_basic.return_value = _make_stock_basic_df(stocks)
        mock_suspend.return_value = pd.DataFrame()
        mock_limit.return_value = pd.DataFrame()
        mock_daily.return_value = _make_daily_basic_df(
            [{"ts_code": stock["ts_code"], "total_mv": 1000000} for stock in stocks]
        )
        mock_sw.return_value = {}

        with patch("src.screening.candidate_pool._SNAPSHOT_DIR", snapshot_dir), \
             patch(
                 "src.screening.candidate_pool._get_avg_amount_20d_map",
                 return_value={f"{i:06d}.SZ": 10000.0 for i in range(250)},
             ):
            with patch("src.screening.candidate_pool.MAX_CANDIDATE_POOL_SIZE", 200):
                cached_200 = build_candidate_pool("20260305", use_cache=True, cooldown_tickers=set())

            with patch("src.screening.candidate_pool.MAX_CANDIDATE_POOL_SIZE", 300):
                cached_300 = build_candidate_pool("20260305", use_cache=True, cooldown_tickers=set())

        assert len(cached_200) == 200
        assert len(cached_300) == 250
        assert (snapshot_dir / "candidate_pool_20260305_top200.json").exists()
        assert (snapshot_dir / "candidate_pool_20260305_top300.json").exists()
        assert (snapshot_dir / "candidate_pool_20260305.json").exists()
