"""btst_daily_selection_anatomy — 日内选择结构解剖的 fixture 驱动测试 (R99).

覆盖: 日内排名镜像生产排序键、top-k 池化、带内配对对照 (singleton 双侧
排除)、top_1 恒等归因零残差、拥挤度分桶、split-half 资格判定、确定性、
宇宙加载 fail-closed。
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts.btst_daily_selection_anatomy import (
    MIN_CELL_N,
    ROUNDTRIP_COST,
    crowding_table,
    cross_window_premium,
    load_universe,
    rank_premium_stability,
    segment_premium,
    top1_gap_attribution,
    topk_curve,
    with_daily_rank,
    within_band_rank_table,
)


def _frame(rows: list[dict]) -> pd.DataFrame:
    """最小宇宙帧 → with_daily_rank 输入形态 (production_aligned 之后)。"""
    base = {
        "signal_date": [],
        "ts_code": [],
        "trigger_strength": [],
        "gross_ret_t10": [],
    }
    for r in rows:
        base["signal_date"].append(r["date"])
        base["ts_code"].append(r["ts"])
        base["trigger_strength"].append(r["str"])
        base["gross_ret_t10"].append(r["ret"])
    return pd.DataFrame(base)


# 三日宇宙: D1 带≥0.70 双候选 (强度并列, ts_code 决胜负); D2 两带 (0.60-0.70
# singleton / 0.50-0.60 双候选); D3 全日 singleton (拥挤桶 "1")。
UNIVERSE = _frame(
    [
        {"date": "20260101", "ts": "AAA", "str": 0.80, "ret": 0.10},
        {"date": "20260101", "ts": "BBB", "str": 0.80, "ret": -0.05},
        {"date": "20260102", "ts": "CCC", "str": 0.65, "ret": 0.02},
        {"date": "20260102", "ts": "DDD", "str": 0.55, "ret": -0.01},
        {"date": "20260102", "ts": "EEE", "str": 0.55, "ret": 0.03},
        {"date": "20260103", "ts": "FFF", "str": 0.90, "ret": -0.02},
    ]
)


class TestWithDailyRank:
    def test_rank_mirrors_production_sort(self):
        df = with_daily_rank(UNIVERSE, 10)
        day1 = df[df["signal_date"] == "20260101"]
        assert day1.iloc[0]["ts_code"] == "AAA" and day1.iloc[0]["day_rank"] == 1
        assert day1.iloc[1]["ts_code"] == "BBB" and day1.iloc[1]["day_rank"] == 2
        day2 = df[df["signal_date"] == "20260102"].sort_values("day_rank")
        assert list(day2["ts_code"]) == ["CCC", "DDD", "EEE"]

    def test_candidates_per_day_and_buckets(self):
        df = with_daily_rank(UNIVERSE, 10)
        per_day = df.groupby("signal_date")["candidates_per_day"].first().to_dict()
        assert per_day == {"20260101": 2, "20260102": 3, "20260103": 1}

    def test_net_return_cost_applied(self):
        df = with_daily_rank(UNIVERSE, 10)
        aaa = df[df["ts_code"] == "AAA"].iloc[0]
        assert aaa["net_ret_t10"] == pytest.approx(0.10 - ROUNDTRIP_COST)

    def test_missing_return_dropped(self):
        u = _frame(
            [
                {"date": "20260101", "ts": "AAA", "str": 0.8, "ret": 0.1},
                {"date": "20260101", "ts": "BBB", "str": 0.8, "ret": None},
            ]
        )
        df = with_daily_rank(u, 10)
        assert len(df) == 1

    def test_signal_date_normalization(self):
        u = _frame([{"date": "2026-01-01", "ts": "AAA", "str": 0.8, "ret": 0.1}])
        df = with_daily_rank(u, 10)
        assert df.iloc[0]["signal_date"] == "20260101"

    def test_malformed_date_fail_closed(self):
        u = _frame([{"date": "not-a-date", "ts": "AAA", "str": 0.8, "ret": 0.1}])
        with pytest.raises(ValueError):
            with_daily_rank(u, 10)


class TestTopkCurve:
    def test_views_and_pooled_mean(self):
        df = with_daily_rank(UNIVERSE, 10)
        rows = {r["view"]: r for r in topk_curve(df, 10)}
        assert set(rows) == {"all", "top_1", "top_2", "top_3", "top_5"}
        assert rows["all"]["n"] == 6 and rows["all"]["days"] == 3
        assert rows["top_1"]["n"] == 3 and rows["top_1"]["days"] == 3
        # top_2 恰含 D1 两笔 + D2 前两笔 + D3 一笔
        assert rows["top_2"]["n"] == 5
        e_all = df["net_ret_t10"].mean()
        assert rows["all"]["expectancy"] == pytest.approx(e_all)

    def test_top1_selection_is_day_best_strength(self):
        df = with_daily_rank(UNIVERSE, 10)
        top1 = df[df["day_rank"] == 1]
        assert set(top1["ts_code"]) == {"AAA", "CCC", "FFF"}


class TestWithinBandRank:
    def test_singleton_excluded_from_both_cells_but_disclosed(self):
        df = with_daily_rank(UNIVERSE, 10)
        table = {r["band"]: r for r in within_band_rank_table(df, 10)}
        hi = table["≥0.70"]
        assert hi["rank1"]["n"] == 1 and hi["rank2plus"]["n"] == 1  # 只有 D1 组
        assert hi["singleton_days_excluded"]["n"] == 1  # FFF 独苗披露
        mid = table["0.60-0.70"]
        assert mid["rank1"]["n"] == 0 and mid["rank2plus"]["n"] == 0  # CCC 独苗排除
        assert mid["singleton_days_excluded"]["n"] == 1
        low = table["0.50-0.60"]
        assert low["rank1"]["n"] == 1 and low["rank2plus"]["n"] == 1  # DDD vs EEE

    def test_premium_sign(self):
        df = with_daily_rank(UNIVERSE, 10)
        low = {r["band"]: r for r in within_band_rank_table(df, 10)}["0.50-0.60"]
        # rank1=DDD(-0.01) rank2+=EEE(+0.03) → premium > 0 (rank-1 更差)
        assert low["premium_rank2plus_minus_rank1"] == pytest.approx(0.03 - (-0.01))


class TestTop1GapAttribution:
    def test_identity_zero_residual_on_fixture(self):
        df = with_daily_rank(UNIVERSE, 10)
        att = top1_gap_attribution(df, 10)
        assert abs(att["residual"]) < 1e-9
        assert att["rank_contribution"] + att["composition_contribution"] == pytest.approx(
            att["delta"]
        )

    def test_composition_only_when_rank_has_no_info(self):
        # 同带内 rank1/rank2+ 分布刻意相同 → rank 贡献≈0, 落差全由构成驱动
        rows = []
        for i in range(6):
            rows.append({"date": f"2026010{i + 1}", "ts": f"A{i}", "str": 0.80, "ret": 0.04})
            rows.append({"date": f"2026010{i + 1}", "ts": f"B{i}", "str": 0.55, "ret": -0.04})
            rows.append({"date": f"2026010{i + 1}", "ts": f"C{i}", "str": 0.52, "ret": -0.04})
        df = with_daily_rank(_frame(rows), 10)
        att = top1_gap_attribution(df, 10)
        assert abs(att["rank_contribution"]) < 1e-12
        assert abs(att["composition_contribution"] - att["delta"]) < 1e-9

    def test_rank_only_when_mix_identical(self):
        # 全部同带 → 构成贡献=0, 落差全由带内排名驱动
        rows = []
        for i in range(6):
            rows.append({"date": f"2026010{i + 1}", "ts": f"A{i}", "str": 0.80, "ret": 0.06})
            rows.append({"date": f"2026010{i + 1}", "ts": f"B{i}", "str": 0.75, "ret": -0.02})
        df = with_daily_rank(_frame(rows), 10)
        att = top1_gap_attribution(df, 10)
        assert abs(att["composition_contribution"]) < 1e-12
        assert att["rank_contribution"] == pytest.approx(att["delta"])


class TestCrowding:
    def test_bucket_boundaries(self):
        rows = [
            {"date": "20260101", "ts": "A", "str": 0.8, "ret": 0.01},
            {"date": "20260102", "ts": "B", "str": 0.8, "ret": 0.01},
            {"date": "20260102", "ts": "C", "str": 0.7, "ret": 0.01},
            {"date": "20260103", "ts": "D", "str": 0.8, "ret": 0.01},
            {"date": "20260103", "ts": "E", "str": 0.7, "ret": 0.01},
            {"date": "20260103", "ts": "F", "str": 0.6, "ret": 0.01},
            {"date": "20260104", "ts": "G", "str": 0.8, "ret": 0.01},
            {"date": "20260104", "ts": "H", "str": 0.7, "ret": 0.01},
            {"date": "20260104", "ts": "I", "str": 0.6, "ret": 0.01},
            {"date": "20260104", "ts": "J", "str": 0.55, "ret": 0.01},
        ]
        df = with_daily_rank(_frame(rows), 10)
        table = {r["bucket"]: r for r in crowding_table(df, 10)}
        assert table["1"]["n"] == 1 and table["1"]["days"] == 1
        assert table["2-3"]["n"] == 5 and table["2-3"]["days"] == 2
        assert table["≥4"]["n"] == 4 and table["≥4"]["days"] == 1
        assert set(table["≥4"]["band_mix"]) == {"0.50-0.60", "0.60-0.70", "≥0.70"}


class TestRankPremiumStability:
    @staticmethod
    def _band_frame(n_days: int, start: int, r1_ret: float, r2_ret: float) -> list[dict]:
        rows = []
        for i in range(n_days):
            d = f"2026{start + i:04d}"
            rows.append({"date": d, "ts": f"A{i}", "str": 0.80, "ret": r1_ret})
            rows.append({"date": d, "ts": f"B{i}", "str": 0.75, "ret": r2_ret})
        return rows

    def test_qualified_when_sign_consistent_and_n_sufficient(self):
        # 60 日同带双候选: rank1 恒优 → premium 恒负 → 资格判定
        rows = self._band_frame(30, 101, 0.06, -0.02) + self._band_frame(30, 201, 0.05, -0.01)
        df = with_daily_rank(_frame(rows), 10)
        table = {r["band"]: r for r in rank_premium_stability(df, 10)}
        hi = table["≥0.70"]
        assert hi["half1"]["rank1_n"] >= MIN_CELL_N and hi["half1"]["rank2plus_n"] >= MIN_CELL_N
        assert hi["half1"]["premium"] < 0 and hi["half2"]["premium"] < 0
        assert hi["verdict"] == "qualified_sign_consistent"

    def test_sign_flip_detected(self):
        rows = self._band_frame(30, 101, 0.06, -0.02) + self._band_frame(30, 201, -0.02, 0.06)
        df = with_daily_rank(_frame(rows), 10)
        table = {r["band"]: r for r in rank_premium_stability(df, 10)}
        assert table["≥0.70"]["verdict"] == "sign_flip"

    def test_insufficient_when_n_below_min(self):
        rows = self._band_frame(3, 101, 0.06, -0.02)
        df = with_daily_rank(_frame(rows), 10)
        table = {r["band"]: r for r in rank_premium_stability(df, 10)}
        assert table["≥0.70"]["verdict"] == "insufficient"

    def test_determinism_with_ci(self):
        rows = self._band_frame(30, 101, 0.06, -0.02) + self._band_frame(30, 201, 0.05, -0.01)
        df = with_daily_rank(_frame(rows), 10)
        # topk_curve 含聚类 CI (n≥30) — 两次调用逐字节相等 (per-call seeded RNG)
        a = json.dumps(topk_curve(df, 10), sort_keys=True)
        b = json.dumps(topk_curve(df, 10), sort_keys=True)
        assert a == b
        assert json.dumps(rank_premium_stability(df, 10), sort_keys=True) == json.dumps(
            rank_premium_stability(df, 10), sort_keys=True
        )


class TestSegmentAndCrossWindow:
    def test_segment_premium_buckets_by_registered_slices(self):
        rows = TestRankPremiumStability._band_frame(10, 101, 0.06, -0.02)
        df = with_daily_rank(_frame(rows), 10)
        segs = segment_premium(df, 10)
        # 2026 年 1 月 (0101..0130) → 2026H1 唯一非空段
        non_empty = [s for s in segs if s["n"] > 0]
        assert [s["segment"] for s in non_empty] == ["2026H1"]

    def test_cross_window_none_when_early_missing(self):
        assert cross_window_premium(None, 10) is None
        assert cross_window_premium(pd.DataFrame(), 10) is None

    def test_cross_window_premium_computed(self):
        rows = TestRankPremiumStability._band_frame(4, 101, 0.06, -0.02)
        df = with_daily_rank(_frame(rows), 10)
        cw = cross_window_premium(df, 10)
        hi = {r["band"]: r for r in cw}["≥0.70"]
        assert hi["rank1_n"] == 4 and hi["premium"] == pytest.approx(-0.02 - 0.06)


class TestLoadUniverse:
    def test_missing_production_columns_fail_closed(self, tmp_path):
        csv = tmp_path / "ev.csv"
        pd.DataFrame({"signal_date": ["20260101"], "ts_code": ["A"]}).to_csv(csv, index=False)
        with pytest.raises(SystemExit) as exc:
            load_universe(csv)
        assert "缺少生产过滤列" in str(exc.value)
