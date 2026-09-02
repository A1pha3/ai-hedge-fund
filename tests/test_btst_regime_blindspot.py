"""btst_regime_blindspot — 三层解剖的 fixture 驱动测试 (零网络/零 gitignored 资产)."""

from __future__ import annotations

import pandas as pd

from scripts.btst_regime_blindspot import (
    MIN_CELL_N,
    add_prior_momentum,
    day_level_stats,
    market_axes_from_panel,
    separation_table,
    split_massacre,
    strength_bucket_table,
)


def _panel(days: dict[str, list[float]]) -> pd.DataFrame:
    """{date: [pct_chg, ...]} → raw 面板帧 (含北交所行应被剔除)."""
    rows = []
    for day, pcts in days.items():
        for i, pct in enumerate(pcts):
            rows.append({"ts_code": f"60000{i}.SH", "trade_date": day, "pct_chg": pct})
        rows.append({"ts_code": "830001.BJ", "trade_date": day, "pct_chg": 29.0})  # 北交所 — 剔除
    return pd.DataFrame(rows)


def _events(rows: list[dict]) -> pd.DataFrame:
    base = {"ts_code": [], "signal_date": [], "regime": [], "trigger_strength": [], "gross_ret_t10": []}
    for r in rows:
        base["ts_code"].append(r["ts"])
        base["signal_date"].append(r["date"])
        base["regime"].append(r.get("regime", "normal"))
        base["trigger_strength"].append(r["strength"])
        base["gross_ret_t10"].append(r["ret"])
    return pd.DataFrame(base)


class TestMarketAxes:
    def test_axes_exclude_beijing(self):
        panel = _panel({"20260710": [10.0, -2.0, 1.0]})
        axes = market_axes_from_panel(panel)
        assert len(axes) == 1
        row = axes.iloc[0]
        assert row["lu_count"] == 1  # 29% 的北交所行不计
        assert row["down_frac"] == 1 / 3
        assert abs(row["mean_ret"] - (10.0 - 2.0 + 1.0) / 3 / 100) < 1e-9


class TestPriorMomentumPIT:
    def test_mkt5_excludes_signal_day(self):
        axes = pd.DataFrame(
            {
                "date": ["20260701", "20260702", "20260703", "20260706", "20260707", "20260708"],
                "mean_ret": [0.01, 0.01, 0.01, 0.01, 0.01, -0.50],
                "down_frac": [0.3] * 6,
                "lu_count": [10] * 6,
            }
        )
        out = add_prior_momentum(axes, lookback=5)
        # 07-08 的 mkt5 只含 0701..0707 五天 (+1%×5 ≈ +5.10%), 信号日 −50% 不入
        expected = 1.01**5 - 1
        assert abs(out.iloc[-1]["mkt5"] - expected) < 1e-9
        # 前四天窗口不足 → NaN
        assert out.iloc[:4]["mkt5"].isna().all()


class TestDayPhenotype:
    def test_split_massacre_threshold(self):
        stats = pd.DataFrame(
            {
                "date": ["20260701", "20260709", "20260723"],
                "n_events": [10, 20, 30],
                "mean_net_e": [-10.0, -25.0, +6.0],
            }
        )
        massacre, ordinary = split_massacre(stats, threshold=-5.0)
        assert massacre == {"20260701", "20260709"}
        assert ordinary == {"20260723"}

    def test_day_level_stats_filters_regime_and_costs(self):
        events = _events(
            [
                {"ts": "A", "date": 20260709, "strength": 0.6, "ret": -0.20},
                {"ts": "B", "date": 20260709, "strength": 0.7, "ret": -0.10},
                {"ts": "C", "date": 20260709, "strength": 0.6, "ret": 0.30, "regime": "crisis"},  # 剔除
                {"ts": "D", "date": 20260723, "strength": 0.6, "ret": 0.10},
            ]
        )
        stats = day_level_stats(events)
        by_day = {r["date"]: r for _, r in stats.iterrows()}
        assert by_day["20260709"]["n_events"] == 2
        # net = gross*100 − 0.65: (−20 −0.65 + −10 −0.65)/2 = −15.65
        assert abs(by_day["20260709"]["mean_net_e"] - (-15.65)) < 1e-9


class TestSeparation:
    def test_separation_table_groups(self):
        axes = pd.DataFrame(
            {
                "date": ["20260709", "20260723"],
                "mean_ret": [-0.01, 0.01],
                "down_frac": [0.6, 0.3],
                "lu_count": [100, 80],
                "mkt5": [0.001, 0.005],
            }
        )
        table = separation_table(axes, {"20260709"}, {"20260723"})
        assert table["massacre_days"]["n_days"] == 1
        assert table["massacre_days"]["mkt5_mean_pct"] == 0.1
        assert table["ordinary_days"]["mkt5_mean_pct"] == 0.5


class TestStrengthBuckets:
    def test_buckets_and_small_n_disclosure(self):
        rows = (
            [{"ts": f"T{i}", "date": 20260701, "strength": 0.45, "ret": -0.05} for i in range(MIN_CELL_N)]
            + [{"ts": f"H{i}", "date": 20260701, "strength": 0.75, "ret": 0.02} for i in range(3)]
        )
        table = strength_bucket_table(_events(rows), window="test")
        by_band = {r["band"]: r for r in table}
        assert by_band["<0.50"]["n"] == MIN_CELL_N
        assert "mean_net_e_pct" in by_band["<0.50"]
        assert by_band[">=0.70"]["n"] == 3
        assert "mean_net_e_pct" not in by_band[">=0.70"]  # n<20 只披露

    def test_regime_filter_normal_only(self):
        rows = [{"ts": "X", "date": 20260701, "strength": 0.55, "ret": 0.10, "regime": "crisis"}]
        table = strength_bucket_table(_events(rows), window="test")
        assert all(r["n"] == 0 for r in table)
