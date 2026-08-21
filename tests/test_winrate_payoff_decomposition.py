"""winrate_payoff_decomposition — 胜率×赔率分解纯函数 (第十轮, 2026-08-22).

钉死的正确性面:
- 恒等式: expectancy (p·W−(1−p)·L) 与逐事件 mean 逐位一致;
- 归因分解精确可加: 胜率贡献 + 赔付贡献 == ΔE, 无残差;
- 边界: 全胜组 payoff=None / 空组 / 桶边界恰落界 / 小样本纪律。
"""

from __future__ import annotations

import json
import math

import pytest

from scripts.winrate_payoff_decomposition import (
    MIN_CELL_N,
    attribution,
    net_returns,
    strength_bucket,
    win_loss_stats,
)


class TestWinLossStats:
    def test_identity_expectancy_equals_mean(self):
        rets = [0.05, -0.02, 0.10, -0.03, 0.01]
        s = win_loss_stats(rets)
        assert s["n"] == 5
        assert s["wins"] == 3
        assert s["winrate"] == pytest.approx(3 / 5)
        assert s["avg_win"] == pytest.approx((0.05 + 0.10 + 0.01) / 3)
        assert s["avg_loss"] == pytest.approx((-0.02 - 0.03) / 2)
        assert s["expectancy"] == pytest.approx(sum(rets) / len(rets), abs=1e-12)
        assert s["payoff"] == pytest.approx(s["avg_win"] / abs(s["avg_loss"]))

    def test_all_winners_payoff_none(self):
        s = win_loss_stats([0.01, 0.02])
        assert s["winrate"] == 1.0
        assert s["payoff"] is None  # 无亏损 → 赔付比未定义, 显式 None
        assert s["expectancy"] == pytest.approx(0.015)

    def test_all_losers(self):
        s = win_loss_stats([-0.01, -0.02])
        assert s["winrate"] == 0.0
        assert s["avg_win"] == 0.0  # 无盈利 → avg_win 取 0
        assert s["payoff"] == 0.0  # 0/|avg_loss| 数学良定义 (区别于全胜组的除零 None)

    def test_empty_group_safe(self):
        s = win_loss_stats([])
        assert s["n"] == 0
        assert s["winrate"] is None
        assert s["expectancy"] is None
        assert s["payoff"] is None

    def test_zero_return_counts_as_loss(self):
        """净收益恰 0 记负侧 (保守: 不把零收益当胜)。"""
        s = win_loss_stats([0.01, 0.0])
        assert s["wins"] == 1
        assert s["winrate"] == pytest.approx(0.5)


class TestAttribution:
    def test_exact_additivity(self):
        base = win_loss_stats([0.04, -0.02, 0.06, -0.03])
        grp = win_loss_stats([0.08, -0.01, 0.05, -0.04, 0.02])
        a = attribution(grp, base)
        delta_e = grp["expectancy"] - base["expectancy"]
        assert a["winrate_contribution"] == pytest.approx(
            (grp["winrate"] - base["winrate"])
            * (base["avg_win"] + abs(base["avg_loss"])),
            abs=1e-12,
        )
        assert a["delta_expectancy"] == pytest.approx(delta_e, abs=1e-12)
        # 精确恒等: ΔE = 胜率贡献 + 赔付贡献, 无残差
        assert (
            a["winrate_contribution"] + a["payoff_contribution"]
            == pytest.approx(a["delta_expectancy"], abs=1e-12)
        )

    def test_payoff_contribution_decomposition(self):
        """赔付贡献 = 胜侧均值变化 − 负侧均值变化 (以组胜率加权)。"""
        base = win_loss_stats([0.04, -0.02])
        grp = win_loss_stats([0.10, -0.05])
        a = attribution(grp, base)
        expected = grp["winrate"] * (grp["avg_win"] - base["avg_win"]) - (
            1 - grp["winrate"]
        ) * (abs(grp["avg_loss"]) - abs(base["avg_loss"]))
        assert a["payoff_contribution"] == pytest.approx(expected, abs=1e-12)

    def test_identical_group_zero_contributions(self):
        base = win_loss_stats([0.04, -0.02, 0.05, -0.01])
        a = attribution(win_loss_stats([0.04, -0.02, 0.05, -0.01]), base)
        assert a["delta_expectancy"] == pytest.approx(0.0, abs=1e-12)
        assert a["winrate_contribution"] == pytest.approx(0.0, abs=1e-12)
        assert a["payoff_contribution"] == pytest.approx(0.0, abs=1e-12)


class TestStrengthBucket:
    def test_boundaries_align_with_panel_convention(self):
        """0.50/0.60/0.70 恰落界 → 归下一桶 (左闭右开, 与 panel 桶界同侧)。"""
        assert strength_bucket(0.4999) == "<0.50"
        assert strength_bucket(0.50) == "0.50-0.60"
        assert strength_bucket(0.5999) == "0.50-0.60"
        assert strength_bucket(0.60) == "0.60-0.70"
        assert strength_bucket(0.70) == "≥0.70"
        assert strength_bucket(0.95) == "≥0.70"

    def test_none_strength_bucketed(self):
        assert strength_bucket(None) == "unknown"


class TestNetReturns:
    def test_cost_convention_matches_court(self):
        """30bps/边滑点 + 5bps 卖出印花税 = 往返 0.65%。"""
        out = net_returns([0.10, None, 0.0])
        assert out[0] == pytest.approx(0.10 - 0.0065)
        assert out[1] is None
        assert out[2] == pytest.approx(-0.0065)


class TestSampleDiscipline:
    def test_small_cell_has_null_verdict_fields(self):
        s = win_loss_stats([0.01] * (MIN_CELL_N - 1))
        assert s["n"] < MIN_CELL_N
        # 判定性字段 (聚类 CI) 只在 n>=MIN_CELL_N 时给出
        assert s.get("cluster_ci_low_90") is None

    def test_min_cell_n_constant(self):
        assert MIN_CELL_N == 30


class TestEndToEndFixture:
    """fixture court 表端到端 (R10 教训: court 表是 gitignored 本地资产,
    slot 隔离 worktree 必缺 — verification 必须不依赖它, 用 tmp fixture)。"""

    def _fixture_table(self, tmp_path):
        import pandas as pd
        rows = []
        for regime, rets in {
            "normal": [0.08, -0.05, 0.12, -0.03, 0.06, -0.02, 0.15, -0.08, 0.04, -0.06,
                        0.10, -0.04, 0.09, -0.07, 0.03, -0.05, 0.11, -0.02, 0.07, -0.09,
                        0.05, -0.04, 0.08, -0.06, 0.02, -0.03, 0.06, -0.05, 0.04, -0.02,
                        0.09, -0.04],
            "crisis": [-0.10, -0.15, 0.05, -0.08, -0.12, 0.03, -0.09, -0.11],
        }.items():
            for i, r in enumerate(rets):
                rows.append({
                    "symbol": f"{600000+i}", "signal_date": f"2026-01-{(i % 20) + 1:02d}",
                    "regime": regime,
                    "trigger_strength": 0.55 + (i % 3) * 0.08,
                    "gross_ret_t10": r + 0.0065,  # 反向扣成本 → 净收益恰为 r
                    "gross_ret_t5": r / 2 + 0.0065,
                })
        df = pd.DataFrame(rows)
        path = tmp_path / "fixture_court.csv.gz"
        df.to_csv(path, index=False)
        return path

    def test_end_to_end_generates_report(self, tmp_path, monkeypatch, capsys):
        from scripts import winrate_payoff_decomposition as mod
        table = self._fixture_table(tmp_path)
        # fixture 是最小列集 (不含生产过滤列) — 端到端只走全候选口径;
        # 生产对齐口径的过滤正确性由 TestProductionAlignedUniverse 专测。
        rc = mod.main(["--court-table", str(table),
                       "--report-dir", str(tmp_path / "rep"),
                       "--universes", "all_candidates"])
        assert rc == 0
        out = tmp_path / "rep"
        from datetime import date as _date
        stamp = _date.today().strftime("%Y%m%d")
        md = (out / f"winrate_payoff_decomposition_{stamp}.md").read_text(encoding="utf-8")
        js = (out / f"winrate_payoff_decomposition_{stamp}.json").read_text(encoding="utf-8")
        assert "court 全候选胜率×赔率分解" in md
        assert "regime=crisis" in md and "regime=normal" in md
        payload = json.loads(js)
        t10 = {r["group"]: r for r in payload["horizons"]["t10"]}
        crisis = t10["regime=crisis"]
        assert crisis["n"] == 8
        all_row = t10["ALL"]
        ident = all_row["winrate"] * all_row["avg_win"] + (1 - all_row["winrate"]) * all_row["avg_loss"]
        assert ident == pytest.approx(all_row["expectancy"], abs=1e-12)
        # 小格子 (crisis n=8 < 30) 不给判定性 CI
        assert crisis["cluster_ci_low_90"] is None

    def test_missing_table_fail_closed(self, tmp_path, monkeypatch):
        from scripts import winrate_payoff_decomposition as mod
        with pytest.raises(SystemExit, match="court 事件表缺失"):
            mod.main(["--court-table", str(tmp_path / "nope.csv.gz"),
                      "--report-dir", str(tmp_path / "rep")])


class TestProductionAlignedUniverse:
    """双口径: 全候选 vs 生产对齐 (复用 review_btst_prior_court 单一实现)。"""

    def _fixture_ev(self, tmp_path):
        import pandas as pd
        rows = []
        for i in range(12):
            rows.append({
                "symbol": f"{600000+i}",
                "signal_date": f"2026-01-{(i % 5) + 1:02d}",
                "regime": "normal" if i % 3 else "crisis",
                "trigger_strength": 0.55 + (i % 3) * 0.1,
                "gross_ret_t10": 0.05 * (1 if i % 2 else -1),
                "gross_ret_t5": 0.02,
                "fillable": True,
                "gate_blocked": i == 10,       # 1 行 gate 拦截
                "degraded": i == 11,           # 1 行降级
                "st_name": False,
                "industry_missing": False,
                "excluded_ticker": False,
                "price_ge_3": True,
            })
        return pd.DataFrame(rows)

    def test_aligned_excludes_gate_and_degraded(self, tmp_path):
        from scripts.winrate_payoff_decomposition import production_aligned
        ev = self._fixture_ev(tmp_path)
        aligned = production_aligned(ev)
        assert len(ev) == 12
        assert len(aligned) == 10  # 排除 gate_blocked(1) + degraded(1)
        assert "600010" not in set(aligned["symbol"])
        assert "600011" not in set(aligned["symbol"])

    def test_missing_filter_column_fails_closed(self, tmp_path):
        """列缺失 = 口径理解错误, fail-closed 不静默当作不过滤 (镜像 review 纪律)。"""
        from scripts.winrate_payoff_decomposition import production_aligned
        ev = self._fixture_ev(tmp_path).drop(columns=["degraded"])
        with pytest.raises(SystemExit, match="court 事件表缺少生产过滤列"):
            production_aligned(ev)

    def test_decompose_dual_universe_payload(self, tmp_path):
        from scripts.winrate_payoff_decomposition import decompose
        ev = self._fixture_ev(tmp_path)
        payload = decompose(ev, universes=("all_candidates", "production_aligned"))
        assert set(payload["universes"]) == {"all_candidates", "production_aligned"}
        all_n = payload["universes"]["all_candidates"]["horizons"]["t10"][0]["n"]
        aligned_n = payload["universes"]["production_aligned"]["horizons"]["t10"][0]["n"]
        assert all_n == 12 and aligned_n == 10
