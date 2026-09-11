"""winrate_payoff_decomposition — 胜率×赔率分解纯函数 (第十轮, 2026-08-22).

钉死的正确性面:
- 恒等式: expectancy (p·W−(1−p)·L) 与逐事件 mean 逐位一致;
- 归因分解精确可加: 胜率贡献 + 赔付贡献 == ΔE, 无残差;
- 边界: 全胜组 payoff=None / 空组 / 桶边界恰落界 / 小样本纪律。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from scripts.winrate_payoff_decomposition import (
    MIN_CELL_N,
    THRESHOLD_TRIGGER_MIN_N,
    attribution,
    attach_threshold_trigger,
    court_window_from_events,
    net_returns,
    record_trigger_status,
    strength_bucket,
    threshold_trigger_status,
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


class TestThresholdTriggerStatus:
    """预注册阈值触发器机械判定面 (AGENTS.md 项1; R77 Op3 判定表自动化)。

    锚定 production_aligned/T+10 分组行:
      条件① strength=≥0.70     n≥min_n 且净口径聚类 CI90 下界 > 0
      条件② strength=0.50-0.60  n≥min_n 且净期望 < 0
    合取点亮才进入阈值上调正式评估资格; n<min_n / 桶行缺失 / 统计缺失 =
    未判定 = 恒不点亮 (保守: 未知不驱动参数变更)。
    """

    @staticmethod
    def _row(group, n, expectancy=None, ci=None, winrate=None):
        return {
            "group": group, "n": n, "wins": 0, "winrate": winrate,
            "avg_win": None, "avg_loss": None, "payoff": None,
            "expectancy": expectancy, "cluster_ci_low_90": ci,
            "attribution_vs_all": None,
        }

    def _rows(self, strong=None, mid=None):
        rows = []
        if strong is not None:
            rows.append(self._row("strength=≥0.70", **strong))
        if mid is not None:
            rows.append(self._row("strength=0.50-0.60", **mid))
        return rows

    def test_min_n_constant_matches_discipline(self):
        assert THRESHOLD_TRIGGER_MIN_N == 30  # R10/R77 判定纪律

    def test_conjunction_armed_when_both_lit(self):
        status = threshold_trigger_status(self._rows(
            strong=dict(n=315, expectancy=0.0201, ci=0.0023),
            mid=dict(n=303, expectancy=-0.0097, ci=-0.018),
        ))
        assert status["condition_1_strong_bucket_ci_above_zero"]["lit"] is True
        assert status["condition_2_mid_bucket_expectancy_negative"]["lit"] is True
        assert status["conjunction_armed"] is True
        assert "正式评估" in status["verdict"]

    def test_condition1_only(self):
        status = threshold_trigger_status(self._rows(
            strong=dict(n=315, expectancy=0.0201, ci=0.0023),
            mid=dict(n=303, expectancy=0.0097, ci=-0.018),
        ))
        assert status["condition_1_strong_bucket_ci_above_zero"]["lit"] is True
        assert status["condition_2_mid_bucket_expectancy_negative"]["lit"] is False
        assert status["conjunction_armed"] is False
        assert "维持" in status["verdict"]

    def test_condition2_only(self):
        status = threshold_trigger_status(self._rows(
            strong=dict(n=315, expectancy=0.0201, ci=-0.001),
            mid=dict(n=303, expectancy=-0.0097, ci=-0.018),
        ))
        assert status["condition_1_strong_bucket_ci_above_zero"]["lit"] is False
        assert status["condition_2_mid_bucket_expectancy_negative"]["lit"] is True
        assert status["conjunction_armed"] is False

    def test_condition1_strictly_above_zero(self):
        """CI90 下界恰为 0 不算越零 (严格 >)。"""
        status = threshold_trigger_status(self._rows(
            strong=dict(n=315, expectancy=0.02, ci=0.0)))
        assert status["condition_1_strong_bucket_ci_above_zero"]["lit"] is False

    def test_condition2_strictly_negative(self):
        """期望恰为 0 不算转负 (严格 <)。"""
        status = threshold_trigger_status(self._rows(
            mid=dict(n=303, expectancy=0.0, ci=-0.018)))
        assert status["condition_2_mid_bucket_expectancy_negative"]["lit"] is False

    def test_missing_ci_not_judged_never_lit(self):
        status = threshold_trigger_status(self._rows(
            strong=dict(n=315, expectancy=0.02, ci=None)))
        c1 = status["condition_1_strong_bucket_ci_above_zero"]
        assert c1["judged"] is False
        assert c1["lit"] is False

    def test_small_n_not_judged_never_lit(self):
        """n<min_n 只披露不判定 (R10): 即使点估计越界也恒不点亮。"""
        status = threshold_trigger_status(self._rows(
            strong=dict(n=29, expectancy=0.02, ci=0.05),
            mid=dict(n=10, expectancy=-0.09, ci=-0.2),
        ))
        assert status["condition_1_strong_bucket_ci_above_zero"]["judged"] is False
        assert status["condition_1_strong_bucket_ci_above_zero"]["lit"] is False
        assert status["condition_2_mid_bucket_expectancy_negative"]["judged"] is False
        assert status["condition_2_mid_bucket_expectancy_negative"]["lit"] is False
        assert status["conjunction_armed"] is False

    def test_missing_bucket_row_not_lit(self):
        status = threshold_trigger_status(self._rows(mid=dict(n=303, expectancy=-0.01)))
        c1 = status["condition_1_strong_bucket_ci_above_zero"]
        assert c1["judged"] is False and c1["lit"] is False
        assert "缺失" in c1["reason"]

    def test_custom_min_n_respected(self):
        status = threshold_trigger_status(
            self._rows(
                strong=dict(n=6, expectancy=0.02, ci=0.01),
                mid=dict(n=6, expectancy=-0.01, ci=-0.02),
            ),
            min_n=5,
        )
        assert status["conjunction_armed"] is True

    def test_pure_and_deterministic(self):
        rows = self._rows(
            strong=dict(n=315, expectancy=0.0201, ci=0.0023),
            mid=dict(n=303, expectancy=0.0097, ci=-0.018),
        )
        assert threshold_trigger_status(rows) == threshold_trigger_status(rows)
        # 输入行不被修改 (纯函数)
        assert rows[0]["n"] == 315

    def test_attach_noop_without_aligned_universe(self):
        payload = {"universes": {"all_candidates": {"horizons": {"t10": []}}}}
        out = attach_threshold_trigger(payload)
        assert "threshold_trigger" not in out

    def test_attach_and_render_integration(self):
        from scripts.winrate_payoff_decomposition import render_md
        rows = [
            self._row("ALL", 1500, expectancy=0.0055, ci=-0.0128, winrate=0.4633),
            self._row("strength=<0.50", 477, expectancy=-0.0153, ci=-0.0403),
            self._row("strength=0.50-0.60", 303, expectancy=0.0097, ci=-0.018),
            self._row("strength=0.60-0.70", 405, expectancy=0.0154, ci=0.0007),
            self._row("strength=≥0.70", 315, expectancy=0.0201, ci=0.0023),
        ]
        payload = {"universes": {"production_aligned": {"horizons": {"t10": rows}}}}
        attach_threshold_trigger(payload)
        assert "threshold_trigger" in payload
        md = render_md(payload, "20260831")
        assert "阈值触发器状态" in md
        assert "条件①" in md and "条件②" in md
        assert "合取" in md

    def test_render_without_trigger_unchanged(self):
        from scripts.winrate_payoff_decomposition import render_md
        payload = {"universes": {"all_candidates": {"horizons": {"t10": []}}}}
        md = render_md(payload, "20260831")
        assert "阈值触发器状态" not in md


class TestPriorAlignmentDisclosure:
    """R135 Op2 对抗审查: 先验对齐披露双守卫 — review_btst_prior_court
    同族对齐断言是双守卫 (E ±1pp 绝对带 + 先验胜率虚高<10pp 方向守卫),
    MD 披露状态此前只实现 E 单守卫且在并列披露两项偏离后宣称『对齐
    (±1pp 内)』——读者会把 ±1pp 误读为覆盖胜率 (R132 Op2 口径披露失真
    同族); 先验胜率虚高 ≥10pp (回到旧「虚高」关系的信号) 时 MD 仍宣称
    对齐。修复 = prior_alignment_status 纯函数 + payload 结构化键 +
    渲染行逐守卫精确措辞 (镜像 review 语义, 不发明第三守卫)。
    """

    PRIOR_E = 0.0056
    PRIOR_W = 0.4645  # known_distributions.BTST_BREAKOUT_T10

    @staticmethod
    def _aligned_payload(expectancy, winrate):
        row = {
            "group": "ALL", "n": 1627, "wins": 0, "winrate": winrate,
            "avg_win": None, "avg_loss": None, "payoff": None,
            "expectancy": expectancy, "cluster_ci_low_90": -0.0163,
            "attribution_vs_all": None,
        }
        return {
            "universes": {"production_aligned": {"horizons": {"t10": [row]}}},
        }

    def test_inflated_prior_winrate_never_claimed_aligned(self):
        """RED 主牙: E ±1pp 内但先验胜率虚高 ≥10pp → 现行 MD 宣称『对齐
        (±1pp 内)』(误导); 修复后必须不宣称对齐且显名虚高守卫。"""
        from scripts.winrate_payoff_decomposition import (
            attach_prior_alignment,
            render_md,
        )
        # E 偏离 |0.0055-0.0056|=0.01pp ≤1 (过); 胜率虚高 0.4645-0.30=16.45pp ≥10 (败)
        payload = attach_prior_alignment(self._aligned_payload(0.0055, 0.30))
        md = render_md(payload, "20260906")
        assert "对齐 (±1pp" not in md
        assert "先验胜率虚高" in md

    def test_alignment_status_wording_scopes_both_guards(self):
        """RED 次牙: 双守卫均过时状态句必须逐守卫精确限定 — 含『E ±1pp』
        与胜率守卫显式字样, 裸『对齐 (±1pp 内)』的歧义措辞不可再出现。"""
        from scripts.winrate_payoff_decomposition import (
            attach_prior_alignment,
            render_md,
        )
        # 真实数据形态: E 偏离 0.57pp / 胜率偏离 -1.89pp — 双守卫过
        payload = attach_prior_alignment(
            self._aligned_payload(0.0056 - 0.0057, 0.4645 - 0.0189)
        )
        md = render_md(payload, "20260906")
        line = next(ln for ln in md.splitlines() if "E 偏离" in ln)
        assert "E ±1pp" in line
        assert "胜率" in line

    def test_prior_alignment_status_pure_function_quadrants(self):
        from scripts.winrate_payoff_decomposition import prior_alignment_status

        # 双过 (真实数据形态)
        s = prior_alignment_status(0.0049, 0.4456, self.PRIOR_E, self.PRIOR_W)
        assert s["aligned"] is True
        assert s["e_within_1pp"] is True
        assert s["prior_winrate_inflated"] is False
        # E 败 / 胜率过
        s = prior_alignment_status(
            0.0056 + 0.02, 0.4456, self.PRIOR_E, self.PRIOR_W
        )
        assert s["aligned"] is False
        assert s["e_within_1pp"] is False
        assert s["prior_winrate_inflated"] is False
        # E 过 / 胜率虚高 (方向守卫: prior - prod >= 10pp)
        s = prior_alignment_status(0.0055, 0.30, self.PRIOR_E, self.PRIOR_W)
        assert s["aligned"] is False
        assert s["prior_winrate_inflated"] is True
        # 双败
        s = prior_alignment_status(
            0.0056 + 0.02, 0.30, self.PRIOR_E, self.PRIOR_W
        )
        assert s["aligned"] is False
        assert s["e_within_1pp"] is False
        assert s["prior_winrate_inflated"] is True

    def test_prior_alignment_status_non_finite_inputs_none(self):
        """R119 P1 家族: 非有限输入不假装 — None 由调用方降级为不可用行。"""
        from scripts.winrate_payoff_decomposition import prior_alignment_status
        assert prior_alignment_status(
            float("nan"), 0.44, self.PRIOR_E, self.PRIOR_W
        ) is None
        assert prior_alignment_status(
            0.005, float("inf"), self.PRIOR_E, self.PRIOR_W
        ) is None
        assert prior_alignment_status(
            0.005, 0.44, float("nan"), self.PRIOR_W
        ) is None

    def test_attach_prior_alignment_payload_key_and_noop(self):
        from scripts.winrate_payoff_decomposition import attach_prior_alignment
        payload = attach_prior_alignment(self._aligned_payload(0.0049, 0.4456))
        pa = payload["prior_alignment"]
        assert pa["aligned"] is True
        assert pa["prior_expected_return"] == self.PRIOR_E
        assert pa["prior_winrate"] == self.PRIOR_W
        # 无生产对齐宇宙 → no-op (镜像 attach_threshold_trigger)
        empty = {"universes": {"all_candidates": {"horizons": {"t10": []}}}}
        assert "prior_alignment" not in attach_prior_alignment(empty)


class TestDeterministicAcrossCalls:
    """R13 对抗审查 PoC: RNG 全局状态曾使同进程第二次调用 CI 漂移。"""

    def test_repeated_calls_identical_ci(self):
        import numpy as np
        from scripts.winrate_payoff_decomposition import cluster_boot_ci_low
        rng_data = np.random.default_rng(42)
        days = [f"d{i % 10}" for i in range(60)]
        rets = list(rng_data.normal(0.001, 0.02, 60))
        ci1 = cluster_boot_ci_low(rets, days)
        ci2 = cluster_boot_ci_low(rets, days)
        ci3 = cluster_boot_ci_low(rets, days)
        assert ci1 == ci2 == ci3  # 与进程内调用历史无关

    def test_decompose_repeated_byte_identical(self):
        from scripts.winrate_payoff_decomposition import decompose
        import numpy as np
        import pandas as pd
        rng = np.random.default_rng(7)
        ev = pd.DataFrame({
            "symbol": [f"s{i}" for i in range(80)],
            "signal_date": [f"2026-01-{(i % 15) + 1:02d}" for i in range(80)],
            "regime": ["normal" if i % 4 else "crisis" for i in range(80)],
            "trigger_strength": list(rng.uniform(0.45, 0.95, 80)),
            "gross_ret_t10": list(rng.normal(0.005, 0.1, 80)),
            "gross_ret_t5": list(rng.normal(0.002, 0.05, 80)),
        })
        first = decompose(ev, universes=("all_candidates",))
        second = decompose(ev, universes=("all_candidates",))
        assert first == second  # 两次完整分解逐字段相等 (含全部 CI)

    def test_decompose_deterministic_regardless_of_prior_noise(self):
        """预消耗全局 RNG 后 decompose 仍与干净进程一致 — 种子封闭在调用内。"""
        import numpy as np
        import pandas as pd
        from scripts.winrate_payoff_decomposition import cluster_boot_ci_low, decompose
        rng = np.random.default_rng(7)
        ev = pd.DataFrame({
            "symbol": [f"s{i}" for i in range(80)],
            "signal_date": [f"2026-01-{(i % 15) + 1:02d}" for i in range(80)],
            "regime": ["normal"] * 80,
            "trigger_strength": list(rng.uniform(0.45, 0.95, 80)),
            "gross_ret_t10": list(rng.normal(0.005, 0.1, 80)),
            "gross_ret_t5": list(rng.normal(0.002, 0.05, 80)),
        })
        clean = decompose(ev, universes=("all_candidates",))
        # 预消耗模块 RNG (若实现仍依赖全局态, 此后结果会漂移)
        junk_days = [f"j{i % 5}" for i in range(50)]
        cluster_boot_ci_low(list(np.random.default_rng(1).normal(0, 0.01, 50)), junk_days)
        after_noise = decompose(ev, universes=("all_candidates",))
        assert clean == after_noise


class TestTriggerStabilityLedger:
    """预注册触发器的『稳定越零』子句机械化 (R81 Op2)。

    R79 Op1 机械化了单次刷新的判定 (lit/armed), 但『稳定越零』是跨刷新性质 —
    累积记录此前只存在于人工翻日报。账本按刷新日期逐条记录判定快照,
    同日刷新替换 (court 表不变则数值恒等, 替换即幂等); 连亮计数从最新记录
    向前数连续 lit, 任何未点亮/未判定记录断链 (保守: 未知不延长连亮)。
    本工具只计数不判定 — 连亮多少次才算『稳定』(阈值 K) 属 owner 预注册范围。
    """

    @staticmethod
    def _trigger(c1_lit=True, c2_lit=False, c1_judged=True, c2_judged=True,
                 c1_stat=0.0023, c2_stat=0.0097, n=300):
        return {
            "rule": "预注册触发器", "anchor": "production_aligned/t10", "min_n": 30,
            "condition_1_strong_bucket_ci_above_zero": {
                "lit": c1_lit, "judged": c1_judged, "n": n, "stat": c1_stat},
            "condition_2_mid_bucket_expectancy_negative": {
                "lit": c2_lit, "judged": c2_judged, "n": n, "stat": c2_stat},
            "conjunction_armed": bool(c1_lit and c2_lit),
            "verdict": "测试夹具",
        }

    def _payload(self, trigger):
        return {"threshold_trigger": trigger}

    def test_record_and_streak_accumulates(self, tmp_path):
        from scripts.winrate_payoff_decomposition import (
            record_trigger_status, trigger_stability, load_trigger_ledger,
        )
        ledger = tmp_path / "ledger.jsonl"
        for i, day in enumerate(["20260829", "20260830", "20260831"]):
            meta = record_trigger_status(
                self._payload(self._trigger(c1_lit=i >= 1)), day, ledger_path=ledger
            )
            assert meta["recorded"] is True
        records = load_trigger_ledger(ledger)
        assert [r["date"] for r in records] == ["20260829", "20260830", "20260831"]
        st = trigger_stability(records)
        assert st["records"] == 3
        assert st["condition_1_streak"] == 2  # 0829 未点亮断链
        assert st["condition_2_streak"] == 0
        assert st["conjunction_streak"] == 0
        assert st["condition_1_last_lit"] is True

    def test_same_date_refresh_replaces(self, tmp_path):
        """同日二次刷新替换同日记录 (court 表不变 → 数值恒等, 幂等收敛)。"""
        from scripts.winrate_payoff_decomposition import (
            record_trigger_status, load_trigger_ledger, trigger_stability,
        )
        ledger = tmp_path / "ledger.jsonl"
        record_trigger_status(self._payload(self._trigger()), "20260831", ledger_path=ledger)
        record_trigger_status(
            self._payload(self._trigger(c1_stat=0.0099)), "20260831", ledger_path=ledger
        )
        records = load_trigger_ledger(ledger)
        assert len(records) == 1
        assert records[0]["condition_1"]["stat"] == 0.0099
        st = trigger_stability(records)
        assert st["records"] == 1 and st["condition_1_streak"] == 1

    def test_unjudged_breaks_streak(self, tmp_path):
        """未判定 (n<30) 记录断链 — 保守: 未知不延长连亮。"""
        from scripts.winrate_payoff_decomposition import (
            record_trigger_status, load_trigger_ledger, trigger_stability,
        )
        ledger = tmp_path / "ledger.jsonl"
        record_trigger_status(self._payload(self._trigger()), "20260829", ledger_path=ledger)
        record_trigger_status(
            self._payload(self._trigger(c1_judged=False, c1_lit=False)),
            "20260830", ledger_path=ledger,
        )
        record_trigger_status(self._payload(self._trigger()), "20260831", ledger_path=ledger)
        st = trigger_stability(load_trigger_ledger(ledger))
        assert st["condition_1_streak"] == 1

    def test_record_missing_trigger_noop(self, tmp_path):
        """payload 无 threshold_trigger (如全候选单口径) → 不写账本。"""
        from scripts.winrate_payoff_decomposition import record_trigger_status
        ledger = tmp_path / "ledger.jsonl"
        meta = record_trigger_status({"universes": {}}, "20260831", ledger_path=ledger)
        assert meta["recorded"] is False
        assert not ledger.exists()

    def test_corrupt_line_skipped(self, tmp_path):
        """损坏行跳过 (诊断面 advisory 语义), 好行照常计数。"""
        from scripts.winrate_payoff_decomposition import (
            record_trigger_status, load_trigger_ledger,
        )
        ledger = tmp_path / "ledger.jsonl"
        record_trigger_status(self._payload(self._trigger()), "20260831", ledger_path=ledger)
        with open(ledger, "a", encoding="utf-8") as fh:
            fh.write("garbage-not-json\n")
        records = load_trigger_ledger(ledger)
        assert [r["date"] for r in records] == ["20260831"]

    def test_render_md_stability_lines(self, tmp_path):
        from scripts.winrate_payoff_decomposition import (
            load_trigger_ledger,
            record_trigger_status,
            render_md,
            trigger_stability,
        )
        ledger = tmp_path / "ledger.jsonl"
        for day in ("20260830", "20260831"):
            record_trigger_status(self._payload(self._trigger()), day, ledger_path=ledger)
        payload = self._payload(self._trigger())
        payload["horizons"] = {"t10": []}
        payload["threshold_stability"] = trigger_stability(load_trigger_ledger(ledger))
        md = render_md(payload, "20260831")
        assert "稳定计数" in md
        assert "条件① 连亮 2/2" in md
        assert "合取连亮 0/2" in md
        assert "稳定阈值 K 属 owner 预注册" in md

    def test_render_md_stability_wording_and_fold_disclosure(self):
        """R130 Op2: MD 措辞收敛至数据状态语义; 折叠>0 显式披露。"""
        from scripts.winrate_payoff_decomposition import render_md
        payload = self._payload(self._trigger())
        payload["horizons"] = {"t10": []}
        payload["threshold_stability"] = {
            "records": 4, "first_date": "20260902", "last_date": "20260905",
            "condition_1_streak": 3, "condition_2_streak": 0,
            "conjunction_streak": 0, "max_conjunction_streak": 0,
            "condition_3_streak": 0, "conjunction_060_streak": 0,
            "max_conjunction_060_streak": 0, "folded_duplicates": 1,
        }
        md = render_md(payload, "20260905")
        assert "连亮按不同数据状态计数" in md
        assert "同数据重复观测不重复累积" in md
        assert "跨刷新逐次记录" not in md
        assert "折叠同数据重复观测 1 条" in md

        payload["threshold_stability"]["folded_duplicates"] = 0
        md_clean = render_md(payload, "20260905")
        assert "折叠" not in md_clean

    def test_render_md_k_registered_consumes_threshold_k(self):
        """K 预注册 → MD 稳定计数行消费 threshold_k 披露 (与渲染行同源)."""
        from src.screening.offensive.threshold_trigger import (
            k_qualification_disclosure,
        )
        from scripts.winrate_payoff_decomposition import render_md
        payload = self._payload(self._trigger())
        payload["horizons"] = {"t10": []}
        payload["threshold_stability"] = {
            "records": 2, "first_date": "20260830", "last_date": "20260831",
            "condition_1_streak": 2, "condition_2_streak": 0,
            "conjunction_streak": 2, "max_conjunction_streak": 2,
            "condition_3_streak": 0, "conjunction_060_streak": 0,
            "max_conjunction_060_streak": 0,
        }
        records = [
            {"date": "20260830", "anchor": "production_aligned/t10",
             "conjunction_armed": True},
            {"date": "20260831", "anchor": "production_aligned/t10",
             "conjunction_armed": True},
        ]
        reg = {"anchor": "production_aligned/t10", "k_070": 2, "k_060": None,
               "registered_date": "20260830"}
        payload["threshold_k"] = k_qualification_disclosure(records, ("registered", reg))
        md = render_md(payload, "20260831")
        assert "预注册 K=2" in md
        assert "正式评估资格达成" in md
        assert "稳定阈值 K 属 owner 预注册" not in md  # 矛盾句必须消失

    def test_render_md_k_absent_payload_keeps_default_sentence(self):
        """旧 payload 无 threshold_k 键 (或结构不符) → 默认句逐字保留."""
        from scripts.winrate_payoff_decomposition import render_md
        payload = self._payload(self._trigger())
        payload["horizons"] = {"t10": []}
        payload["threshold_stability"] = {
            "records": 1, "first_date": "20260831", "last_date": "20260831",
            "condition_1_streak": 1, "condition_2_streak": 0,
            "conjunction_streak": 0, "max_conjunction_streak": 0,
            "condition_3_streak": 0, "conjunction_060_streak": 0,
            "max_conjunction_060_streak": 0,
        }
        md = render_md(payload, "20260831")
        assert "稳定阈值 K 属 owner 预注册" in md

    def test_build_report_attaches_threshold_k(self, tmp_path, monkeypatch):
        """build 路径把 K 披露挂进 payload — JSON 落盘可复现, MD 只读 payload."""
        import pandas as pd
        from scripts import winrate_payoff_decomposition as mod
        rows = []
        for i in range(40):
            rows.append({
                "symbol": f"{600000+i}",
                "signal_date": f"2026-01-{(i % 20) + 1:02d}",
                "regime": "normal",
                "trigger_strength": 0.75 if i % 2 else 0.55,
                "gross_ret_t10": 0.03 * (1 if i % 2 else -1),
                "gross_ret_t5": 0.015,
                "fillable": True, "gate_blocked": False, "degraded": False,
                "st_name": False, "industry_missing": False,
                "excluded_ticker": False, "price_ge_3": True,
            })
        table = tmp_path / "court.csv.gz"
        pd.DataFrame(rows).to_csv(table, index=False)
        ledger = tmp_path / "trigger_ledger.jsonl"
        kfile = tmp_path / "k.json"
        kfile.write_text(json.dumps({
            "anchor": "production_aligned/t10", "k_070": 5,
            "registered_date": "20260101",
        }), encoding="utf-8")
        klog = tmp_path / "k_obs.jsonl"
        rc = mod.main([
            "--court-table", str(table), "--report-dir", str(tmp_path / "rep"),
            "--trigger-ledger", str(ledger),
            "--k-registration", str(kfile),
            "--k-observation-log", str(klog),
        ])
        assert rc == 0
        import json as _json
        from datetime import date as _date
        stamp = _date.today().strftime("%Y%m%d")
        payload = _json.loads(
            (tmp_path / "rep" / f"winrate_payoff_decomposition_{stamp}.json").read_text(encoding="utf-8")
        )
        assert payload["threshold_k"]["state"] == "registered"
        assert "预注册 K=5" in payload["threshold_k"]["line_070"]
        # R113: 先观测后披露 — 首次 build 落观测凭证, 幂等重放不重复追加
        assert payload["threshold_k_observation"]["observed"] is True
        assert mod.load_k_observations(klog)
        mod.main([
            "--court-table", str(table), "--report-dir", str(tmp_path / "rep"),
            "--trigger-ledger", str(ledger),
            "--k-registration", str(kfile),
            "--k-observation-log", str(klog),
        ])
        assert len(mod.load_k_observations(klog)) == 1

    def test_main_writes_ledger_and_md(self, tmp_path, monkeypatch):
        """端到端: 生产对齐口径刷新 → 账本落盘 + MD 稳定计数行。"""
        import pandas as pd
        from datetime import date as _date
        from scripts import winrate_payoff_decomposition as mod
        rows = []
        for i in range(40):
            rows.append({
                "symbol": f"{600000+i}",
                "signal_date": f"2026-01-{(i % 20) + 1:02d}",
                "regime": "normal",
                "trigger_strength": 0.75 if i % 2 else 0.55,
                "gross_ret_t10": 0.03 * (1 if i % 2 else -1),
                "gross_ret_t5": 0.015,
                "fillable": True, "gate_blocked": False, "degraded": False,
                "st_name": False, "industry_missing": False,
                "excluded_ticker": False, "price_ge_3": True,
            })
        table = tmp_path / "court.csv.gz"
        pd.DataFrame(rows).to_csv(table, index=False)
        ledger = tmp_path / "trigger_ledger.jsonl"
        rc = mod.main([
            "--court-table", str(table), "--report-dir", str(tmp_path / "rep"),
            "--trigger-ledger", str(ledger),
        ])
        assert rc == 0
        records = mod.load_trigger_ledger(ledger)
        assert len(records) == 1
        assert records[0]["anchor"] == "production_aligned/t10"
        stamp = _date.today().strftime("%Y%m%d")
        md = (tmp_path / "rep" / f"winrate_payoff_decomposition_{stamp}.md").read_text(encoding="utf-8")
        assert "稳定计数" in md

    def test_main_all_candidates_only_skips_ledger(self, tmp_path):
        """全候选单口径 (无生产对齐锚) → 不写账本 (无判定即无记录)。"""
        import pandas as pd
        from scripts import winrate_payoff_decomposition as mod
        rows = []
        for i in range(32):
            rows.append({
                "symbol": f"{600000+i}", "signal_date": f"2026-01-{(i % 20) + 1:02d}",
                "regime": "normal", "trigger_strength": 0.55,
                "gross_ret_t10": 0.02, "gross_ret_t5": 0.01,
            })
        table = tmp_path / "court.csv.gz"
        pd.DataFrame(rows).to_csv(table, index=False)
        ledger = tmp_path / "trigger_ledger.jsonl"
        rc = mod.main([
            "--court-table", str(table), "--report-dir", str(tmp_path / "rep"),
            "--universes", "all_candidates", "--trigger-ledger", str(ledger),
        ])
        assert rc == 0
        assert not ledger.exists()


class TestCourtGrowthCoupling:
    """触发器判定与 court 数据增长机械耦合 (R84 Op1)。

    R81 Op2 账本按刷新日期记录, 但记录不绑定 court 表身份: court 陈旧时
    逐日判定会写下『新日期旧数据』记录, streak 虚假增长。本族钉死三件事:
    ① 每条快照绑定 court 身份 (window/rows/指纹/内容摘要);
    ② 数据前进门 (require_advance): 任一历史记录绑定相同 → skip 不追加;
    ③ 旧形态无绑定记录放行 (向后兼容, 不追溯拒绝);
    ④ build 成功后机械刷新 (fail-open)。
    """

    BINDING_A = {"window_start": "20250701", "window_end": "20260830",
                 "rows": 1746, "formula_fingerprint": "aa" * 32,
                 "content_digest": "sha256:" + "a1" * 32, "universe_audit_complete": True}
    BINDING_B = {"window_start": "20250701", "window_end": "20260831",
                 "rows": 1782, "formula_fingerprint": "bb" * 32,
                 "content_digest": "sha256:" + "b2" * 32, "universe_audit_complete": True}

    @staticmethod
    def _trigger():
        return {
            "rule": "预注册触发器", "anchor": "production_aligned/t10", "min_n": 30,
            "condition_1_strong_bucket_ci_above_zero": {
                "lit": True, "judged": True, "n": 315, "stat": 0.0023},
            "condition_2_mid_bucket_expectancy_negative": {
                "lit": False, "judged": True, "n": 303, "stat": 0.0097},
            "conjunction_armed": False,
            "verdict": "测试夹具",
        }

    def test_record_binds_court_identity(self, tmp_path):
        from scripts.winrate_payoff_decomposition import (
            record_trigger_status, load_trigger_ledger,
        )
        ledger = tmp_path / "ledger.jsonl"
        meta = record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260830",
            ledger_path=ledger, court_binding=dict(self.BINDING_A),
        )
        assert meta["recorded"] is True
        rec = load_trigger_ledger(ledger)[0]
        assert rec["court"] == self.BINDING_A

    def test_advance_gate_skips_same_binding_cross_date(self, tmp_path):
        """同绑定跨日 → skip (同数据重判不产生新证据, streak 不虚假增长)。"""
        from scripts.winrate_payoff_decomposition import (
            record_trigger_status, load_trigger_ledger,
        )
        ledger = tmp_path / "ledger.jsonl"
        record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260830",
            ledger_path=ledger, court_binding=dict(self.BINDING_A),
        )
        meta = record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260831",
            ledger_path=ledger, court_binding=dict(self.BINDING_A),
            require_advance=True,
        )
        assert meta["recorded"] is False
        assert meta["reason"] == "court_not_advanced"
        assert [r["date"] for r in load_trigger_ledger(ledger)] == ["20260830"]

    def test_advance_gate_records_on_binding_advance(self, tmp_path):
        """绑定前进 (court 重建) 跨日 → 落新记录 (真实数据状态)。"""
        from scripts.winrate_payoff_decomposition import (
            record_trigger_status, load_trigger_ledger,
        )
        ledger = tmp_path / "ledger.jsonl"
        record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260830",
            ledger_path=ledger, court_binding=dict(self.BINDING_A),
        )
        meta = record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260831",
            ledger_path=ledger, court_binding=dict(self.BINDING_B),
            require_advance=True,
        )
        assert meta["recorded"] is True
        records = load_trigger_ledger(ledger)
        assert [r["date"] for r in records] == ["20260830", "20260831"]
        assert records[1]["court"] == self.BINDING_B

    def test_advance_gate_same_date_advanced_binding_replaces(self, tmp_path):
        """同日 court 前进 → 替换同日记录 (当日重建后最新事实)。"""
        from scripts.winrate_payoff_decomposition import (
            record_trigger_status, load_trigger_ledger,
        )
        ledger = tmp_path / "ledger.jsonl"
        record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260831",
            ledger_path=ledger, court_binding=dict(self.BINDING_A),
        )
        meta = record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260831",
            ledger_path=ledger, court_binding=dict(self.BINDING_B),
            require_advance=True,
        )
        assert meta["recorded"] is True
        records = load_trigger_ledger(ledger)
        assert len(records) == 1
        assert records[0]["court"] == self.BINDING_B

    def test_advance_gate_legacy_record_without_binding_passes(self, tmp_path):
        """旧形态记录无 court 字段 → 门放行 (不追溯拒绝, 绑定自此开始积累)。"""
        from scripts.winrate_payoff_decomposition import (
            record_trigger_status, load_trigger_ledger,
        )
        ledger = tmp_path / "ledger.jsonl"
        record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260830", ledger_path=ledger
        )
        assert "court" not in load_trigger_ledger(ledger)[0]
        meta = record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260831",
            ledger_path=ledger, court_binding=dict(self.BINDING_B),
            require_advance=True,
        )
        assert meta["recorded"] is True

    def test_gate_off_preserves_legacy_semantics(self, tmp_path):
        """require_advance 缺省 False → 同绑定跨日仍落记录 (手动路径原语义)。"""
        from scripts.winrate_payoff_decomposition import (
            record_trigger_status, load_trigger_ledger,
        )
        ledger = tmp_path / "ledger.jsonl"
        record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260830",
            ledger_path=ledger, court_binding=dict(self.BINDING_A),
        )
        meta = record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260831",
            ledger_path=ledger, court_binding=dict(self.BINDING_A),
        )
        assert meta["recorded"] is True

    def test_advance_gate_skips_request_state_only_change(self, tmp_path):
        """R130 Op1: 仅请求态字段 (window_end) 漂移、content_digest 同 → skip。

        2026-09-05 生产实录 (周六休市): 18:30 research refresh court_build
        推进 window_end 20260904→20260905 而事件表零变化, 整字典比较使前进门
        放行, 账本写入『新日期旧数据』重复判定记录, 条件①连亮被非交易日
        重复观测膨胀。数据状态身份只认 content_digest。
        """
        from scripts.winrate_payoff_decomposition import (
            record_trigger_status, load_trigger_ledger,
        )
        ledger = tmp_path / "ledger.jsonl"
        record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260904",
            ledger_path=ledger, court_binding=dict(self.BINDING_A),
        )
        request_state_drift = dict(self.BINDING_A, window_end="20260905")
        meta = record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260905",
            ledger_path=ledger, court_binding=request_state_drift,
            require_advance=True,
        )
        assert meta["recorded"] is False
        assert meta["reason"] == "court_not_advanced"
        assert [r["date"] for r in load_trigger_ledger(ledger)] == ["20260904"]

    def test_advance_gate_request_state_change_cohort_family(self, tmp_path):
        """R130 Op1: 日层族前进门同款 — 共享单一实现, window 漂移不写重复记录。"""
        from scripts.btst_signal_day_cohort import record_cohort_trigger_status
        from src.screening.offensive.cohort_trigger import load_cohort_trigger_ledger
        ledger = tmp_path / "cohort_ledger.jsonl"
        trigger = {
            "anchor": "production_aligned/t10/cohort_size", "min_n": 30,
            "condition_strong_bucket_ci_above_zero": {
                "lit": True, "judged": True, "n": 100, "stat": 0.001},
            "condition_mid_buckets_expectancy_negative": {
                "lit": False, "judged": True, "n": 90, "stat": 0.002},
            "conjunction_armed": False,
        }
        record_cohort_trigger_status(
            {"cohort_trigger": trigger}, "20260904",
            ledger_path=ledger, court_binding=dict(self.BINDING_A),
        )
        request_state_drift = dict(self.BINDING_A, window_end="20260905")
        meta = record_cohort_trigger_status(
            {"cohort_trigger": trigger}, "20260905",
            ledger_path=ledger, court_binding=request_state_drift,
            require_advance=True,
        )
        assert meta["recorded"] is False
        assert meta["reason"] == "court_not_advanced"
        assert [r["date"] for r in load_cohort_trigger_ledger(ledger)] == ["20260904"]

    def test_main_records_binding_and_gate(self, tmp_path, monkeypatch):
        """端到端: main 走前进门 — 同绑定重跑 skip 且披露 reason, 报告照常写出。"""
        import json
        import pandas as pd
        from datetime import date as _date
        from scripts import winrate_payoff_decomposition as mod
        rows = []
        for i in range(40):
            rows.append({
                "symbol": f"{600000+i}",
                "signal_date": f"2026-01-{(i % 20) + 1:02d}",
                "regime": "normal", "trigger_strength": 0.75 if i % 2 else 0.55,
                "gross_ret_t10": 0.03 * (1 if i % 2 else -1),
                "gross_ret_t5": 0.015,
                "fillable": True, "gate_blocked": False, "degraded": False,
                "st_name": False, "industry_missing": False,
                "excluded_ticker": False, "price_ge_3": True,
            })
        tables = tmp_path / "event_tables"
        tables.mkdir()
        table = tables / "court.csv.gz"
        pd.DataFrame(rows).to_csv(table, index=False)
        ledger = tmp_path / "trigger_ledger.jsonl"
        rep = tmp_path / "rep"
        argv = ["--court-table", str(table), "--report-dir", str(rep),
                "--trigger-ledger", str(ledger)]

        stamp = _date.today().strftime("%Y%m%d")
        json_path = rep / f"winrate_payoff_decomposition_{stamp}.json"

        monkeypatch.setattr(mod, "TABLE_DIR", tables)
        mod.main(argv)
        records = mod.load_trigger_ledger(ledger)
        assert len(records) == 1
        court = records[0]["court"]
        assert court["window_start"] is None
        assert court["window_end"] is None and court["rows"] == 40
        assert court["formula_fingerprint"] is None
        assert court["content_digest"].startswith("sha256:")
        assert court["universe_audit_complete"] is None  # fixture 无 manifest

        # 同表同绑定当日重跑 (前进门): 账本不动, 报告刷新, reason 披露进 JSON
        mod.main(argv)
        assert len(mod.load_trigger_ledger(ledger)) == 1
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload["threshold_record"]["reason"] == "court_not_advanced"


class TestAdversarialAuditR84Op1:
    """Op1 交付面对抗审查三缺陷收口 (R84 Op2)。

    A 畸形 manifest 裸 AttributeError — court_binding 自述『缺失/损坏不假装
      知道』却只捕 OSError/JSONDecodeError; window 非 dict / manifest 非 dict /
      built_at 非字符串时 .get 裸逃逸。
    B 前进门单点 (最新记录) 比对 — 数据状态回退 A→B→A (备份恢复旧 court)
      放行同状态重复判定; 判定是 (数据状态, 规则) 的确定性纯函数, 任一
      已见过的绑定都不产生新证据, 门必须对比全历史。
    C 绑定缺公式指纹 — 同日公式变更重建且行数不变时绑定恒等 → 门静默
      skip 吞掉新判定; manifest formula_fingerprint 是现成强判别。
    """

    def _trigger(self):
        return TestCourtGrowthCoupling._trigger()

    def test_binding_malformed_manifest_degrades_to_none(self, tmp_path):
        from scripts.winrate_payoff_decomposition import court_binding
        tables = tmp_path / "event_tables"
        tables.mkdir()
        table = tables / "court.csv.gz"
        table.write_bytes(b"x")
        # 整文件垃圾
        (tables / "manifest_v1.json").write_text("not json at all", encoding="utf-8")
        b = court_binding(table, rows=7)
        assert b == {"window_start": None, "window_end": None,
                     "data_window": {"start": None, "end": None},
                     "rows": 7, "formula_fingerprint": None,
                     "content_digest": None, "universe_audit_complete": None}
        # manifest 非 dict (JSON 数组)
        (tables / "manifest_v1.json").write_text("[1,2]", encoding="utf-8")
        assert "built_at" not in court_binding(table, rows=7)
        # window 非 dict (built_at 已不进身份, 畸形与否无关)
        (tables / "manifest_v1.json").write_text(
            json.dumps({"built_at": 5, "window": ["bad"]}), encoding="utf-8")
        b = court_binding(table, rows=7)
        assert "built_at" not in b and b["window_end"] is None

    def test_binding_includes_formula_fingerprint(self, tmp_path):
        from scripts.winrate_payoff_decomposition import court_binding
        tables = tmp_path / "event_tables"
        tables.mkdir()
        table = tables / "court.csv.gz"
        table.write_bytes(b"x")
        fp = "aa" * 32
        (tables / "manifest_v1.json").write_text(json.dumps({
            "built_at": "2026-08-31", "window": {"end": "20260831"},
            "formula_fingerprint": {"btst_breakout_sha256": fp},
        }), encoding="utf-8")
        b = court_binding(table, rows=99)
        assert b == {"window_start": None,
                     "window_end": "20260831",
                     "data_window": {"start": None, "end": None},
                     "rows": 99,
                     "formula_fingerprint": fp,
                     "content_digest": None, "universe_audit_complete": None}

    def test_gate_skips_regressed_binding_seen_in_history(self, tmp_path):
        """数据状态回退 (A→B→A) — A 已判定过, 门必须 skip (B 单点比对会放行)。"""
        from scripts.winrate_payoff_decomposition import (
            record_trigger_status, load_trigger_ledger,
        )
        ledger = tmp_path / "ledger.jsonl"
        c1 = TestCourtGrowthCoupling.BINDING_A
        c2 = TestCourtGrowthCoupling.BINDING_B
        record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260829",
            ledger_path=ledger, court_binding=dict(c1))
        record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260830",
            ledger_path=ledger, court_binding=dict(c2), require_advance=True)
        meta = record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260831",
            ledger_path=ledger, court_binding=dict(c1), require_advance=True)
        assert meta["recorded"] is False
        assert meta["reason"] == "court_not_advanced"
        assert [r["date"] for r in load_trigger_ledger(ledger)] == ["20260829", "20260830"]

    def test_gate_allows_unseen_binding_after_history(self, tmp_path):
        """全历史比对不误伤真正前进的新状态 (C→D 前进照常落记录)。"""
        from scripts.winrate_payoff_decomposition import (
            record_trigger_status, load_trigger_ledger,
        )
        ledger = tmp_path / "ledger.jsonl"
        c1 = TestCourtGrowthCoupling.BINDING_A
        c3 = {"window_end": "20260901", "rows": 1900}
        record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260829",
            ledger_path=ledger, court_binding=dict(c1))
        meta = record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260901",
            ledger_path=ledger, court_binding=dict(c3), require_advance=True)
        assert meta["recorded"] is True
        assert [r["date"] for r in load_trigger_ledger(ledger)] == ["20260829", "20260901"]


class TestWindowStartIdentity:
    """R89: 窗口起点是数据状态身份 — binding 含 window_start, 同 end/rows/
    指纹但异起点是不同数据状态 (R84-Op2C 强身份教训; 生产窗口前扩的前置)。"""

    def test_binding_includes_window_start(self, tmp_path):
        import pandas as pd
        from scripts.winrate_payoff_decomposition import court_binding
        tables = tmp_path / "event_tables"
        tables.mkdir()
        table = tables / "court.csv.gz"
        table.write_bytes(b"x")
        (tables / "manifest_v1.json").write_text(json.dumps({
            "built_at": "2026-09-01", "window": {"start": "20250102", "end": "20260831"},
            "formula_fingerprint": {"btst_breakout_sha256": "aa" * 32},
        }), encoding="utf-8")
        b = court_binding(table, rows=99)
        assert b == {"window_start": "20250102",
                     "window_end": "20260831",
                     # R186 Op1: 表不可读 (b"x") → 数据内容窗口退化 None, 不冒充
                     "data_window": {"start": None, "end": None},
                     "rows": 99,
                     "formula_fingerprint": "aa" * 32,
                     "content_digest": None, "universe_audit_complete": None}

    def test_advance_gate_same_end_rows_different_start_is_new_state(self, tmp_path):
        """同 end/rows/指纹但起点不同 (20250102 vs 20250701) → 门不 skip, 落新记录。"""
        from scripts.winrate_payoff_decomposition import (
            record_trigger_status, load_trigger_ledger,
        )
        ledger = tmp_path / "ledger.jsonl"
        trigger = TestCourtGrowthCoupling._trigger()
        binding_a = {"window_start": "20250701",
                     "window_end": "20260831", "rows": 100, "formula_fingerprint": "aa" * 32}
        binding_b = dict(binding_a, window_start="20250102", rows=100)
        record_trigger_status({"threshold_trigger": trigger}, "20260831",
                              ledger_path=ledger, court_binding=binding_a)
        meta = record_trigger_status({"threshold_trigger": trigger}, "20260901",
                                     ledger_path=ledger, court_binding=binding_b,
                                     require_advance=True)
        assert meta["recorded"] is True
        records = load_trigger_ledger(ledger)
        assert {r["court"]["window_start"] for r in records} == {"20250701", "20250102"}

    def test_binding_malformed_window_start_degrades_to_none(self, tmp_path):
        from scripts.winrate_payoff_decomposition import court_binding
        tables = tmp_path / "event_tables"
        tables.mkdir()
        table = tables / "court.csv.gz"
        table.write_bytes(b"x")
        (tables / "manifest_v1.json").write_text(json.dumps({
            "window": {"start": 55, "end": "20260831"}}), encoding="utf-8")
        b = court_binding(table, rows=1)
        assert b["window_start"] is None and b["window_end"] == "20260831"


class TestCourtBindingContentIdentity:
    """R90 Op2: binding 增内容身份 — 同日内容修正重建必须能推进判定账本。

    2026-09-01 实例: 零审计构建与本会话回填修正构建的 built_at/rows/
    formula_fingerprint 全同 (同日同行数同公式), 旧 binding 不可区分 →
    前进门把修正判定误判为 court_not_advanced。
    """

    def _write_table(self, tmp_path, df, name="court.csv.gz"):
        table = tmp_path / name
        df.to_csv(table, index=False, compression="gzip")
        return table

    def _table_df(self):
        import pandas as pd
        return pd.DataFrame({
            "symbol": ["600000", "600001"],
            "signal_date": ["20260105", "20260106"],
            "trigger_strength": [0.7, 0.55],
            "gross_ret_t10": [0.03, -0.02],
            "regime": ["normal", "normal"],
        })

    def _manifest(self, tmp_path, *, empty_days=0, include_empty=True,
                  days_checked=2, sessions=2):
        audit = {"days_checked": days_checked}
        if include_empty:
            audit["empty_days"] = empty_days
        (tmp_path / "manifest_v1.json").write_text(json.dumps({
            "built_at": "2026-09-01",
            "window": {"start": "20260101", "end": "20260131", "sessions": sessions},
            "formula_fingerprint": {"btst_breakout_sha256": "f" * 64},
            "universe_audit": audit,
        }), encoding="utf-8")

    def test_content_digest_detects_same_shape_content_change(self, tmp_path):
        """同行数 + 同 manifest 的内容修正 → digest 变, 其余身份字段全同。"""
        from scripts.winrate_payoff_decomposition import court_binding
        df = self._table_df()
        self._manifest(tmp_path)
        b1 = court_binding(self._write_table(tmp_path, df), rows=len(df))
        df.loc[0, "gross_ret_t10"] = 0.99  # panel 价格修正类: 行数/manifest 全同
        b2 = court_binding(self._write_table(tmp_path, df, name="fixed.csv.gz"),
                           rows=len(df))
        for k in ("window_start", "window_end", "rows", "formula_fingerprint"):
            assert b1[k] == b2[k]  # 旧 binding 对此两表不可区分 (缺陷形态)
        assert b1["content_digest"] != b2["content_digest"]

    def test_content_digest_stable_across_rewrite(self, tmp_path):
        """同内容重写 (新 mtime/新 gzip 头) → digest 恒同 (幂等跳过语义保持)。"""
        import time
        from scripts.winrate_payoff_decomposition import court_binding
        df = self._table_df()
        self._manifest(tmp_path)
        b1 = court_binding(self._write_table(tmp_path, df), rows=len(df))
        time.sleep(1.1)  # gzip mtime 秒级分辨率 — 字节不同的同内容重写
        b2 = court_binding(self._write_table(tmp_path, df, name="rewrite.csv.gz"),
                           rows=len(df))
        assert b2["content_digest"] == b1["content_digest"]

    def test_advance_gate_admits_same_day_content_fix(self, tmp_path):
        """同日内容修正重建: binding 其余字段全同也必须落账 (缺陷修复面)。"""
        from scripts.winrate_payoff_decomposition import (
            court_binding, load_trigger_ledger, record_trigger_status,
        )
        df = self._table_df()
        self._manifest(tmp_path)
        trigger = {"anchor": "production_aligned/t10", "min_n": 30}
        b_stale = court_binding(self._write_table(tmp_path, df), rows=len(df))
        df.loc[0, "gross_ret_t10"] = 0.99
        b_fixed = court_binding(
            self._write_table(tmp_path, df, name="fixed.csv.gz"), rows=len(df))
        assert b_stale["content_digest"] != b_fixed["content_digest"]
        ledger = tmp_path / "ledger.jsonl"
        record_trigger_status({"threshold_trigger": trigger}, "20260901",
                              ledger_path=ledger, court_binding=b_stale,
                              require_advance=True)
        meta = record_trigger_status({"threshold_trigger": trigger}, "20260901",
                                     ledger_path=ledger, court_binding=b_fixed,
                                     require_advance=True)
        assert meta["recorded"] is True  # 旧字段全同也曾被吞 (20260901 实例)
        records = load_trigger_ledger(ledger)
        assert len(records) == 1  # 同日替换
        assert records[0]["court"]["content_digest"] == b_fixed["content_digest"]

    def test_advance_gate_still_idempotent_for_identical_table(self, tmp_path):
        """同一份数据重放 → court_not_advanced 幂等跳过 (语义保持)。"""
        from scripts.winrate_payoff_decomposition import (
            court_binding, record_trigger_status,
        )
        df = self._table_df()
        self._manifest(tmp_path)
        binding = court_binding(self._write_table(tmp_path, df), rows=len(df))
        trigger = {"anchor": "production_aligned/t10", "min_n": 30}
        ledger = tmp_path / "ledger.jsonl"
        record_trigger_status({"threshold_trigger": trigger}, "20260901",
                              ledger_path=ledger, court_binding=binding,
                              require_advance=True)
        meta = record_trigger_status({"threshold_trigger": trigger}, "20260901",
                                     ledger_path=ledger, court_binding=binding,
                                     require_advance=True)
        assert meta == {"recorded": False, "reason": "court_not_advanced",
                        "records": 1}

    def test_universe_audit_complete_three_states(self, tmp_path):
        """True (闭合) / False (键全在但不闭合) / None (legacy 无 empty_days
        或 manifest 损坏 — 旧形态无该计数, 不得推断)。"""
        from scripts.winrate_payoff_decomposition import court_binding
        df = self._table_df()
        # True: 计数闭合
        self._manifest(tmp_path, empty_days=0, days_checked=2, sessions=2)
        b = court_binding(self._write_table(tmp_path, df), rows=len(df))
        assert b["universe_audit_complete"] is True
        # False: 键全在但不闭合
        self._manifest(tmp_path, empty_days=0, days_checked=1, sessions=2)
        b = court_binding(self._write_table(tmp_path, df, name="t2.csv.gz"),
                          rows=len(df))
        assert b["universe_audit_complete"] is False
        # None: legacy manifest 无 empty_days 键
        self._manifest(tmp_path, days_checked=1, sessions=2, include_empty=False)
        b = court_binding(self._write_table(tmp_path, df, name="t3.csv.gz"),
                          rows=len(df))
        assert b["universe_audit_complete"] is None
        # None: manifest 损坏
        (tmp_path / "m2").mkdir()
        (tmp_path / "m2" / "manifest_v1.json").write_text("{broken", encoding="utf-8")
        b = court_binding(self._write_table(tmp_path, df, name="m2/t4.csv.gz"),
                          rows=len(df))
        assert b["universe_audit_complete"] is None
        assert b["content_digest"] is not None  # 表可读 → 摘要在场

    def test_legacy_binding_records_never_block_advance(self, tmp_path):
        """旧形态账本记录 (court 无新字段) ≠ 新 binding → 不阻断追加 (多记不漏记)。"""
        from scripts.winrate_payoff_decomposition import (
            court_binding, record_trigger_status,
        )
        df = self._table_df()
        self._manifest(tmp_path)
        binding = court_binding(self._write_table(tmp_path, df), rows=len(df))
        legacy = {k: v for k, v in binding.items()
                  if k not in ("content_digest", "universe_audit_complete")}
        trigger = {"anchor": "production_aligned/t10", "min_n": 30}
        ledger = tmp_path / "ledger.jsonl"
        # 旧形态记录以 legacy 形态写入 (R84 时代无新字段)
        record_trigger_status({"threshold_trigger": trigger}, "20260831",
                              ledger_path=ledger,
                              court_binding=legacy, require_advance=True)
        meta = record_trigger_status({"threshold_trigger": trigger}, "20260901",
                                     ledger_path=ledger, court_binding=binding,
                                     require_advance=True)
        assert meta["recorded"] is True


class TestSliceBucketStability:
    """切片×强度桶稳定性 (R91 Op1): 触发器窗口敏感性的跨段证据视图。

    动机: 窗口前扩使条件① 从 lit (CI90 +0.23%) 翻转为未点亮 (−0.46%) —
    全窗口单点统计无法区分『结构性 edge』与『单段驱动』; 本视图把触发器
    锚定分组 (强度桶) 逐预注册切片展开。
    """

    def _frame(self):
        """数值非对称 fixture (R13 教训): 逐格期望各不相同, 断言防漂移。

        净收益 = gross − 0.0065 → fixture gross 反向加回, 断言直用净额。
        """
        import pandas as pd
        rows = []
        # 2026H1 ≥0.70: n=3, E=+0.04 (0.10/−0.02/+0.04)
        for sd, s, r in [("20260310", 0.90, 0.10), ("20260311", 0.80, -0.02), ("20260312", 0.75, 0.04)]:
            rows.append({"signal_date": sd, "trigger_strength": s,
                         "gross_ret_t10": r + 0.0065})
        # 2026H1 <0.50: n=2, E=−0.02 (−0.05/+0.01)
        for sd, s, r in [("20260313", 0.30, -0.05), ("20260313", 0.40, 0.01)]:
            rows.append({"signal_date": sd, "trigger_strength": s, "gross_ret_t10": r + 0.0065})
        # 2025H2 ≥0.70: n=2, E=+0.025 (≠ 2026H1 的 +0.04 — 跨段非对称)
        for sd, s, r in [("20250914", 0.95, 0.02), ("20250915", 0.85, 0.03)]:
            rows.append({"signal_date": sd, "trigger_strength": s, "gross_ret_t10": r + 0.0065})
        # 2025H2 0.60-0.70: n=1, E=−0.04
        rows.append({"signal_date": "20250916", "trigger_strength": 0.65, "gross_ret_t10": -0.04 + 0.0065})
        # 2026H1 unknown (强度缺失): n=1 — 诚实披露 unknown 桶
        rows.append({"signal_date": "20260316", "trigger_strength": None, "gross_ret_t10": 0.01 + 0.0065})
        return pd.DataFrame(rows).astype({"signal_date": str})

    def test_cells_asymmetric_expectancies(self):
        from scripts.winrate_payoff_decomposition import slice_bucket_stability
        blocks = {b["slice"]: b for b in slice_bucket_stability(self._frame())}
        h1 = {c["bucket"]: c for c in blocks["2026H1"]["buckets"]}
        h2 = {c["bucket"]: c for c in blocks["2025H2"]["buckets"]}
        assert h1["≥0.70"]["n"] == 3
        assert h1["≥0.70"]["expectancy"] == pytest.approx((0.10 - 0.02 + 0.04) / 3, abs=1e-12)
        assert h1["<0.50"]["n"] == 2
        assert h1["<0.50"]["expectancy"] == pytest.approx((-0.05 + 0.01) / 2, abs=1e-12)
        assert h2["≥0.70"]["n"] == 2
        assert h2["≥0.70"]["expectancy"] == pytest.approx((0.02 + 0.03) / 2, abs=1e-12)
        assert h2["0.60-0.70"]["n"] == 1
        # 跨段非对称: 同桶不同段期望不同 (防 fixture 对称漂移假阴性)
        assert h1["≥0.70"]["expectancy"] != h2["≥0.70"]["expectancy"]

    def test_empty_and_unknown_cells_honest(self):
        from scripts.winrate_payoff_decomposition import slice_bucket_stability
        blocks = {b["slice"]: b for b in slice_bucket_stability(self._frame())}
        h1 = {c["bucket"]: c for c in blocks["2026H1"]["buckets"]}
        h2 = {c["bucket"]: c for c in blocks["2025H2"]["buckets"]}
        # 空格: 2026H1 的 0.60-0.70 无行 → n=0 全 None
        assert h1["0.60-0.70"]["n"] == 0
        assert h1["0.60-0.70"]["expectancy"] is None
        assert h1["0.60-0.70"]["cluster_ci_low_90"] is None
        # 强度缺失行 → unknown 桶诚实入格
        assert h1["unknown"]["n"] == 1
        # 2026H2+ / 2025H1 整段空 → 每桶 n=0
        plus = {c["bucket"]: c for c in blocks["2026H2+"]["buckets"]}
        assert plus["≥0.70"]["n"] == 0 and plus["≥0.70"]["winrate"] is None

    def test_small_cell_ci_honest_none(self):
        """小样本格 CI 缺失 (win_loss_stats 内建 n<MIN_CELL_N 门槛)。"""
        from scripts.winrate_payoff_decomposition import MIN_CELL_N
        from scripts.winrate_payoff_decomposition import slice_bucket_stability
        assert MIN_CELL_N > 3
        blocks = {b["slice"]: b for b in slice_bucket_stability(self._frame())}
        h1 = {c["bucket"]: c for c in blocks["2026H1"]["buckets"]}
        assert h1["≥0.70"]["n"] < MIN_CELL_N
        assert h1["≥0.70"]["cluster_ci_low_90"] is None

    def test_ci_cell_deterministic_across_calls(self):
        """n≥MIN_CELL_N 格给 CI; 同输入两次调用逐字节一致 (R13 纪律)。"""
        import pandas as pd
        from scripts.winrate_payoff_decomposition import MIN_CELL_N
        from scripts.winrate_payoff_decomposition import slice_bucket_stability
        n = MIN_CELL_N + 2
        rows = [{"signal_date": f"202603{10 + (i % 5):02d}", "trigger_strength": 0.9,
                 "gross_ret_t10": (0.01 * (1 if i % 2 else -1)) + 0.0065}
                for i in range(n)]
        frame = pd.DataFrame(rows).astype({"signal_date": str})
        a = slice_bucket_stability(frame)
        b = slice_bucket_stability(frame)
        assert json.dumps(a) == json.dumps(b)
        h1 = next(blk for blk in a if blk["slice"] == "2026H1")
        cell = next(c for c in h1["buckets"] if c["bucket"] == "≥0.70")
        assert cell["n"] == n
        assert isinstance(cell["cluster_ci_low_90"], float)

    def test_outside_rows_fail_closed(self):
        """越界行 (未覆盖窗口) → fail-closed, 复用单一覆盖守卫不静默缺段。"""
        import pandas as pd
        from scripts.winrate_payoff_decomposition import slice_bucket_stability
        frame = pd.DataFrame([
            {"signal_date": "20211231", "trigger_strength": 0.9, "gross_ret_t10": 0.01},
            {"signal_date": "20260310", "trigger_strength": 0.9, "gross_ret_t10": 0.01},
        ]).astype({"signal_date": str})
        with pytest.raises(ValueError, match="coverage gap"):
            slice_bucket_stability(frame)

    def test_decompose_mounts_slice_stability_and_md(self, tmp_path):
        """decompose 两宇宙挂载同构块; MD 报告含生产对齐锚定表。"""
        import pandas as pd
        from scripts.winrate_payoff_decomposition import decompose, render_md
        rows = []
        for i in range(12):
            rows.append({
                "symbol": f"{600000+i}",
                "signal_date": f"2026-01-{(i % 5) + 1:02d}",
                "regime": "normal",
                "trigger_strength": 0.55 + (i % 3) * 0.1,
                "gross_ret_t10": 0.05 * (1 if i % 2 else -1),
                "gross_ret_t5": 0.02,
                "fillable": True,
                "gate_blocked": False,
                "degraded": False,
                "st_name": False,
                "industry_missing": False,
                "excluded_ticker": False,
                "price_ge_3": True,
            })
        ev = pd.DataFrame(rows)
        payload = decompose(ev, universes=("all_candidates", "production_aligned"))
        for uni_name in ("all_candidates", "production_aligned"):
            blocks = payload["universes"][uni_name]["slice_bucket_stability"]
            assert [b["slice"] for b in blocks] == [
                "2022H1", "2022H2", "2023H1", "2023H2", "2024H1", "2024H2",
                "2025H1", "2025H2", "2026H1", "2026H2+",
            ]
            # ISO 短横日期归一后全部落 2026H1
            h1 = next(b for b in blocks if b["slice"] == "2026H1")
            assert sum(c["n"] for c in h1["buckets"]) == 12
        md = render_md(payload, "20260901")
        assert "切片×强度桶稳定性" in md
        assert "2025H1" in md and "≥0.70" in md


class TestGapBucket:
    """T+1 开盘缺口分桶 (R92 Op1): 左闭右开, 恰落边界钉死。"""

    def test_bucket_boundaries(self):
        from scripts.winrate_payoff_decomposition import gap_bucket
        assert gap_bucket(-0.06) == "<-5%"
        assert gap_bucket(-0.05) == "-5~0"   # 恰落边界: 左闭
        assert gap_bucket(-0.001) == "-5~0"
        assert gap_bucket(0.0) == "0~2%"     # 恰落边界: 平开归 0~2%
        assert gap_bucket(0.019) == "0~2%"
        assert gap_bucket(0.02) == "2~5%"
        assert gap_bucket(0.049) == "2~5%"
        assert gap_bucket(0.05) == "5~10%"   # 恰落边界 = GAP_HIGH_THRESHOLD 下界
        assert gap_bucket(0.099) == "5~10%"
        assert gap_bucket(0.10) == ">10%"    # 恰落边界
        assert gap_bucket(0.20) == ">10%"

    def test_missing_gap_honest_unknown(self):
        from scripts.winrate_payoff_decomposition import gap_bucket
        assert gap_bucket(None) == "unknown"
        assert gap_bucket(float("nan")) == "unknown"


class TestGapAnatomy:
    """执行面 gap 解剖 (R92 Op1): 分桶 + close-anchor 分离 + 桶内条件 + 切片共变。

    fixture 数值非对称 (R13 教训): 每格期望各不相同, close-anchor 与
    entry-net 方向相反制造可检测的分离面。
    """

    def _frame(self):
        import pandas as pd
        rows = []
        # gap=0.01 (0~2%): n=3, entry-net E=+0.04 (0.10/−0.02/+0.04), close-anchor = net + 0.03
        for sd, s, r, ca in [("20260310", 0.90, 0.10, 0.13), ("20260311", 0.80, -0.02, 0.01),
                             ("20260312", 0.75, 0.04, 0.07)]:
            rows.append({"signal_date": sd, "trigger_strength": s, "gap_t1_open": 0.01,
                         "gross_ret_t10": r + 0.0065, "ret_close_anchor_t10": ca})
        # gap=0.07 (5~10%): n=2, entry-net E=−0.045 (−0.05/−0.04), close-anchor = net + 0.02
        for sd, s, r, ca in [("20260313", 0.60, -0.05, -0.03), ("20260314", 0.55, -0.04, -0.02)]:
            rows.append({"signal_date": sd, "trigger_strength": s, "gap_t1_open": 0.07,
                         "gross_ret_t10": r + 0.0065, "ret_close_anchor_t10": ca})
        # gap=0.07 但强度缺失 → 桶内条件面 unknown 排除 + 分桶面入 5~10%
        rows.append({"signal_date": "20260315", "trigger_strength": None, "gap_t1_open": 0.07,
                     "gross_ret_t10": 0.01 + 0.0065, "ret_close_anchor_t10": 0.04})
        # gap 缺失 (net 有值) → gap_missing 只披露
        rows.append({"signal_date": "20260316", "trigger_strength": 0.80, "gap_t1_open": None,
                     "gross_ret_t10": 0.02 + 0.0065, "ret_close_anchor_t10": 0.05})
        # net 缺失 (未成熟) → 不入任何格
        rows.append({"signal_date": "20260317", "trigger_strength": 0.80, "gap_t1_open": 0.03,
                     "gross_ret_t10": None, "ret_close_anchor_t10": 0.06})
        # 2025H2 gap=−0.01 (−5~0): 跨段非对称
        rows.append({"signal_date": "20250914", "trigger_strength": 0.90, "gap_t1_open": -0.01,
                     "gross_ret_t10": 0.03 + 0.0065, "ret_close_anchor_t10": 0.06})
        return pd.DataFrame(rows).astype({"signal_date": str})

    def test_bucket_cells_asymmetric(self):
        from scripts.winrate_payoff_decomposition import gap_anatomy
        out = gap_anatomy(self._frame())
        cells = {c["bucket"]: c for c in out["buckets"]}
        assert [c["bucket"] for c in out["buckets"]] == [
            "<-5%", "-5~0", "0~2%", "2~5%", "5~10%", ">10%"]
        assert cells["0~2%"]["n"] == 3
        assert cells["0~2%"]["expectancy"] == pytest.approx((0.10 - 0.02 + 0.04) / 3, abs=1e-12)
        assert cells["5~10%"]["n"] == 3
        assert cells["5~10%"]["expectancy"] == pytest.approx((-0.05 - 0.04 + 0.01) / 3, abs=1e-12)
        assert cells["-5~0"]["n"] == 1
        assert cells["-5~0"]["expectancy"] == pytest.approx(0.03, abs=1e-12)
        # 空格诚实 n=0 全 None
        for empty in ("<-5%", "2~5%", ">10%"):
            assert cells[empty]["n"] == 0
            assert cells[empty]["expectancy"] is None
            assert cells[empty]["cluster_ci_low_90"] is None
        # 分桶面不含 net 缺失行与 gap 缺失行
        assert sum(c["n"] for c in out["buckets"]) == 7

    def test_close_anchor_separation(self):
        """close-anchored 毛期望并列披露 — 与 entry-net 方向可分离 (非对称)。"""
        from scripts.winrate_payoff_decomposition import gap_anatomy
        out = gap_anatomy(self._frame())
        cells = {c["bucket"]: c for c in out["buckets"]}
        # 0~2%: close-anchor = net + 0.03 → +0.07
        assert cells["0~2%"]["close_anchor_gross_e"] == pytest.approx((0.13 + 0.01 + 0.07) / 3, abs=1e-12)
        assert cells["0~2%"]["close_anchor_n"] == 3
        # 5~10%: close-anchor = net + 0.02 → −0.025
        assert cells["5~10%"]["close_anchor_gross_e"] == pytest.approx((-0.03 - 0.02 + 0.04) / 3, abs=1e-12)
        # entry-net 与 close-anchor 逐格不同 (非对称防漂移)
        assert cells["0~2%"]["expectancy"] != cells["0~2%"]["close_anchor_gross_e"]
        # close-anchor 缺失行 → n 诚实下降
        assert cells["-5~0"]["close_anchor_n"] == 1

    def test_gap_missing_disclosed_not_judged(self):
        from scripts.winrate_payoff_decomposition import gap_anatomy
        out = gap_anatomy(self._frame())
        assert out["gap_missing"]["n"] == 1

    def test_within_strength_conditional(self):
        from scripts.winrate_payoff_decomposition import gap_anatomy
        out = gap_anatomy(self._frame())
        within = {w["strength_bucket"]: w for w in out["within_strength"]}
        assert [w["strength_bucket"] for w in out["within_strength"]] == [
            "<0.50", "0.50-0.60", "0.60-0.70", "≥0.70"]
        hi = within["0.60-0.70"]["gap_high"]
        lo = within["0.60-0.70"]["gap_low"]
        assert hi["n"] == 1 and hi["expectancy"] == pytest.approx(-0.05, abs=1e-12)
        assert lo["n"] == 0 and lo["expectancy"] is None
        assert within["0.50-0.60"]["gap_high"]["n"] == 1
        assert within["0.50-0.60"]["gap_high"]["expectancy"] == pytest.approx(-0.04, abs=1e-12)
        # <0.50 整桶空 → 两侧诚实 n=0 全 None
        assert within["<0.50"]["gap_high"]["n"] == 0
        assert within["<0.50"]["gap_low"]["expectancy"] is None
        # unknown 强度行不入条件面; 缺失 gap 在所属强度桶内单列计数
        assert within["0.60-0.70"]["gap_missing"] == 0
        s7 = within["≥0.70"]
        assert s7["gap_high"]["n"] == 0 and s7["gap_high"]["expectancy"] is None
        # within 视图是全窗口的 (切片维度由 R91 slice-bucket 面承担): 含 2025H2 那行
        assert s7["gap_low"]["n"] == 4
        assert s7["gap_low"]["expectancy"] == pytest.approx(
            (0.10 - 0.02 + 0.04 + 0.03) / 4, abs=1e-12)
        assert s7["gap_missing"] == 1

    def test_slice_co_movement(self):
        from scripts.winrate_payoff_decomposition import gap_anatomy
        out = gap_anatomy(self._frame())
        slices = {s["slice"]: s for s in out["slice_co_movement"]}
        h1 = slices["2026H1"]["all"]
        assert h1["n"] == 6
        assert h1["share_high"] == pytest.approx(3 / 6, abs=1e-12)
        assert h1["e_net"] == pytest.approx((0.10 - 0.02 + 0.04 - 0.05 - 0.04 + 0.01) / 6, abs=1e-12)
        assert h1["gap_missing"] == 1
        h2 = slices["2025H2"]["all"]
        assert h2["n"] == 1 and h2["share_high"] == 0.0
        # ≥0.70 锚桶 2026H1: gap-present 3 行全 low → share=0.0 (缺 gap 行单列)
        s7 = slices["2026H1"]["strong"]
        assert s7["n"] == 3 and s7["share_high"] == 0.0
        assert s7["gap_missing"] == 1

    def test_outside_rows_fail_closed(self):
        """越界行复用 slice_partitions 覆盖守卫 (fail-closed, 不静默缺段)。"""
        import pandas as pd
        from scripts.winrate_payoff_decomposition import gap_anatomy
        frame = pd.DataFrame([
            {"signal_date": "20211231", "trigger_strength": 0.9, "gap_t1_open": 0.01,
             "gross_ret_t10": 0.01, "ret_close_anchor_t10": 0.02},
            {"signal_date": "20260310", "trigger_strength": 0.9, "gap_t1_open": 0.01,
             "gross_ret_t10": 0.01, "ret_close_anchor_t10": 0.02},
        ]).astype({"signal_date": str})
        with pytest.raises(ValueError, match="coverage gap"):
            gap_anatomy(frame)

    def test_missing_columns_fail_closed(self):
        import pandas as pd
        from scripts.winrate_payoff_decomposition import gap_anatomy
        base = {"signal_date": ["20260310"], "trigger_strength": [0.9],
                "gross_ret_t10": [0.01]}
        with pytest.raises(SystemExit, match="gap_t1_open"):
            gap_anatomy(pd.DataFrame({**base, "ret_close_anchor_t10": [0.02]}))
        with pytest.raises(SystemExit, match="ret_close_anchor_t10"):
            gap_anatomy(pd.DataFrame({**base, "gap_t1_open": [0.01]}))

    def test_deterministic_across_calls(self):
        """n≥MIN_CELL_N 格带 CI; 同输入两次调用逐字节一致 (R13 纪律)。"""
        import pandas as pd
        from scripts.winrate_payoff_decomposition import gap_anatomy
        rows = [{"signal_date": f"202603{10 + (i % 5):02d}", "trigger_strength": 0.9,
                 "gap_t1_open": 0.01 * (i % 2),  # 全部落 0~2% 桶 → 该格 CI 活跃
                 "gross_ret_t10": (0.01 * (1 if i % 2 else -1)) + 0.0065,
                 "ret_close_anchor_t10": 0.005 * (i % 3)}
                for i in range(MIN_CELL_N + 4)]
        frame = pd.DataFrame(rows).astype({"signal_date": str})
        a = gap_anatomy(frame)
        b = gap_anatomy(frame)
        assert json.dumps(a) == json.dumps(b)
        cell = next(c for c in a["buckets"] if c["bucket"] == "0~2%")
        assert cell["n"] >= MIN_CELL_N
        assert isinstance(cell["cluster_ci_low_90"], float)


class TestGapAnatomyMountedAndRendered:
    """decompose 两宇宙挂载同构 gap_anatomy 块; MD 报告渲染锚定表 + 纪律标注。"""

    def _ev(self):
        import pandas as pd
        rows = []
        for i in range(12):
            rows.append({
                "symbol": f"{600000+i}",
                "signal_date": f"2026-01-{(i % 5) + 1:02d}",
                "regime": "normal",
                "trigger_strength": 0.55 + (i % 3) * 0.1,
                "gap_t1_open": 0.01 * (i % 4),
                "gross_ret_t10": 0.05 * (1 if i % 2 else -1),
                "gross_ret_t5": 0.02,
                "ret_close_anchor_t10": 0.03 * (1 if i % 3 else -1),
                "fillable": True,
                "gate_blocked": False,
                "degraded": False,
                "st_name": False,
                "industry_missing": False,
                "excluded_ticker": False,
                "price_ge_3": True,
            })
        return pd.DataFrame(rows)

    def test_mounted_on_both_universes(self):
        from scripts.winrate_payoff_decomposition import decompose
        payload = decompose(self._ev(), universes=("all_candidates", "production_aligned"))
        for uni_name in ("all_candidates", "production_aligned"):
            gap = payload["universes"][uni_name]["gap_anatomy"]
            assert gap["gap_high_threshold"] == 0.05
            assert [c["bucket"] for c in gap["buckets"]] == [
                "<-5%", "-5~0", "0~2%", "2~5%", "5~10%", ">10%"]
            assert sum(c["n"] for c in gap["buckets"]) == 12

    def test_md_renders_gap_section(self):
        from scripts.winrate_payoff_decomposition import decompose, render_md
        payload = decompose(self._ev(), universes=("all_candidates", "production_aligned"))
        md = render_md(payload, "20260901")
        assert "执行面 gap 解剖" in md
        assert "close-anchor" in md          # 机械/信息分离面标注
        assert "探索性" in md                 # in-sample 阈值纪律标注
        assert "只披露不判定" in md or "只披露" in md
        assert "5~10%" in md and ">10%" in md


class TestGapSplitHalf:
    """gap 判别 split-half 稳定性 (R92 Op2): R15 合取判据纪律镜像。

    R15 教训: in-sample 判别力 ≠ 可条件化 (强度桶 Kelly 排序稳定但符号
    跨半翻转) — gap 罚分同样必须过『方向跨半一致』的门。
    """

    def _rows(self, penalties, n_low=15, n_high=3, start_day=1):
        """构造跨半罚分 fixture: penalties = (first_hi_mean, second_hi_mean)。

        lo 侧均值恒 +0.01; hi 侧均值由参数给定 — penalty = 0.01 − hi_mean。
        n_low/n_high 控制半区桶内合计 n (15+3=18 < 30 可造小样本形态;
        传大值造可判定形态)。
        """
        import pandas as pd
        rows = []
        for half_idx, hi_mean in enumerate(penalties):
            for i in range(n_high):
                rows.append({
                    "signal_date": f"2026-0{1 + half_idx * 3}-{start_day + i:02d}",
                    "trigger_strength": 0.9,
                    "gap_t1_open": 0.07,
                    "gross_ret_t10": hi_mean + 0.0065,
                    "ret_close_anchor_t10": hi_mean + 0.02,
                })
            for i in range(n_low):
                rows.append({
                    "signal_date": f"2026-0{1 + half_idx * 3}-{start_day + i:02d}",
                    "trigger_strength": 0.9,
                    "gap_t1_open": 0.01,
                    "gross_ret_t10": 0.01 + 0.0065,
                    "ret_close_anchor_t10": 0.01 + 0.03,
                })
        return pd.DataFrame(rows).astype({"signal_date": str})

    def _split(self, frame):
        from scripts.winrate_payoff_decomposition import gap_anatomy
        return gap_anatomy(frame)["split_half"]

    def test_consistent_direction_earns_eligibility(self):
        # 两半 hi 均差于 lo (+0.01) → 罚分均正 → 一致 → 资格
        sh = self._split(self._rows(penalties=(-0.03, -0.02), n_low=28))
        b = next(x for x in sh["buckets"] if x["strength_bucket"] == "≥0.70")
        assert b["judgable"] is True
        assert b["direction_consistent"] is True
        assert b["penalty_first"] == pytest.approx(0.01 - (-0.03), abs=1e-12)
        assert b["penalty_second"] == pytest.approx(0.01 - (-0.02), abs=1e-12)
        assert sh["judgable_count"] == 1 and sh["consistent_count"] == 1
        assert "具备进一步评估资格" in sh["verdict_hint"]
        assert "仍非授权" in sh["verdict_hint"]

    def test_direction_flip_denies_eligibility(self):
        # 第一半 hi 差 (罚分正), 第二半 hi 反超 lo (罚分负) → 翻转 → 不足
        sh = self._split(self._rows(penalties=(-0.03, 0.05), n_low=28))
        b = next(x for x in sh["buckets"] if x["strength_bucket"] == "≥0.70")
        assert b["judgable"] is True
        assert b["direction_consistent"] is False
        assert b["penalty_second"] == pytest.approx(0.01 - 0.05, abs=1e-12)
        assert sh["consistent_count"] == 0
        assert "过拟合风险" in sh["verdict_hint"]

    def test_small_halves_not_judgable(self):
        # 半区桶内合计 n=3+3=6 < MIN_CELL_N → 不可判定 → 样本不足 verdict
        # (n_low=16 + n_high=3 = 19 仍 < 30 — 可判定形态需要 n_low>=28)
        sh = self._split(self._rows(penalties=(-0.03, -0.02), n_low=3, n_high=3))
        b = sh["buckets"][0]
        assert b["judgable"] is False
        assert b["direction_consistent"] is None
        assert sh["judgable_count"] == 0
        assert "样本不足" in sh["verdict_hint"]

    def test_split_date_deterministic_and_reported(self):
        frame = self._rows(penalties=(-0.03, -0.02), n_low=16)
        a = self._split(frame)
        b = self._split(frame)
        assert json.dumps(a) == json.dumps(b)
        # 切分日 = 中位唯一信号日 (披露面)
        sessions = sorted(frame["signal_date"].unique())
        assert a["split_date"] == sessions[len(sessions) // 2]

    def test_close_anchor_secondary_disclosure(self):
        sh = self._split(self._rows(penalties=(-0.03, -0.02), n_low=28))
        b = next(x for x in sh["buckets"] if x["strength_bucket"] == "≥0.70")
        # ca: hi = hi_mean + 0.02, lo = 0.04 → ca 罚分 = 0.04 − (hi_mean+0.02)
        assert b["ca_penalty_first"] == pytest.approx(0.04 - (-0.03 + 0.02), abs=1e-12)
        assert b["ca_penalty_second"] == pytest.approx(0.04 - (-0.02 + 0.02), abs=1e-12)

    # --- R188 Op1: 聚合 (全强度池化) 罚分跨半读数 ---------------------------
    # 执行面行文自身的问题是聚合层 (『高开>5% 子集历史期望』), 分桶合取
    # verdict 回答的是增量判别层, 两层不可互替。聚合 consistent 判定逐半
    # 逐侧 MIN_CELL_N 门槛 — 分桶面允许小样本 hi 侧驱动合取翻转的教训
    # (R188 Observe 实录 0.60-0.70 第二半 n_hi=11) 不得在聚合面重演。

    def _pooled_split(self, penalties, n_low, n_high):
        return self._split(self._rows(penalties, n_low=n_low, n_high=n_high))

    def test_pooled_penalty_direction_consistent(self):
        pooled = self._pooled_split((-0.03, -0.02), n_low=32, n_high=32)["pooled"]
        assert pooled["consistent"] is True
        assert pooled["penalty_first"] == pytest.approx(0.01 - (-0.03), abs=1e-12)
        assert pooled["penalty_second"] == pytest.approx(0.01 - (-0.02), abs=1e-12)
        assert pooled["e_hi_first"] == pytest.approx(-0.03, abs=1e-12)
        assert pooled["e_hi_second"] == pytest.approx(-0.02, abs=1e-12)
        assert pooled["n_hi_first"] == 32 and pooled["n_hi_second"] == 32

    def test_pooled_direction_flip_disclosed(self):
        pooled = self._pooled_split((-0.03, 0.05), n_low=32, n_high=32)["pooled"]
        assert pooled["consistent"] is False
        assert pooled["penalty_second"] == pytest.approx(0.01 - 0.05, abs=1e-12)
        # 聚合面与分桶面互不替代: 分桶合取此时也翻转, 两层读数并列
        assert "过拟合风险" in self._pooled_split((-0.03, 0.05), 32, 32)["verdict_hint"]

    def test_pooled_small_hi_side_not_judged(self):
        # 第二半 hi 侧 n=3 < MIN_CELL_N: penalty 可算但 consistent None;
        # 对照面 — 同一形态分桶面因『桶内合计 n』口径恰可判定 (后者正是
        # 小样本 hi 侧驱动合取的弱点, 聚合面逐侧门槛不继承)。
        sh = self._pooled_split((-0.03, -0.02), n_low=32, n_high=3)
        pooled = sh["pooled"]
        assert pooled["penalty_second"] is not None
        assert pooled["consistent"] is None
        bucket = next(x for x in sh["buckets"] if x["strength_bucket"] == "≥0.70")
        assert bucket["judgable"] is True

    def test_pooled_missing_hi_side_none(self):
        # 第二半无高开行 → penalty_second None → consistent None 不冒充方向
        frame = self._rows(penalties=(-0.03, -0.02), n_low=32, n_high=32)
        import pandas as pd
        second_hi = (frame["signal_date"].str.startswith("2026-04")) & (
            frame["gap_t1_open"] == 0.07)
        frame = frame[~second_hi].reset_index(drop=True)
        pooled = self._split(frame)["pooled"]
        assert pooled["penalty_second"] is None
        assert pooled["consistent"] is None
        assert pooled["n_hi_second"] == 0

    def test_pooled_existing_keys_unchanged(self):
        """pooled 是纯增量键 — 既有键与分桶 verdict 逻辑零变化。"""
        sh = self._pooled_split((-0.03, -0.02), n_low=32, n_high=32)
        for key in ("split_date", "buckets", "judgable_count", "consistent_count",
                    "close_anchor_penalty_stable", "verdict_hint"):
            assert key in sh
        assert sh["judgable_count"] == 1 and sh["consistent_count"] == 1
        assert "具备进一步评估资格" in sh["verdict_hint"]

    def test_pooled_deterministic_across_calls(self):
        a = self._pooled_split((-0.03, 0.05), n_low=32, n_high=32)
        b = self._pooled_split((-0.03, 0.05), n_low=32, n_high=32)
        assert json.dumps(a["pooled"]) == json.dumps(b["pooled"])

    def test_pooled_zero_penalty_sign_semantics(self):
        """零罚分符号语义 (R188 Op2 P03 钉子): consistent 用严格 >0 —
        罚分恰为零归『非正』: 单零对正罚分 = 异号 (False); 双零 = 同号
        (True, False==False)。>= 变异 (零冒充正号) 下本测试 RED。"""
        import pandas as pd

        def day_rows(sd, gap, net, n):
            return [
                {"signal_date": sd, "trigger_strength": 0.90, "gap_t1_open": gap,
                 "gross_ret_t10": net + 0.0065, "ret_close_anchor_t10": net + 0.02}
                for _ in range(n)
            ]

        # 第一半 hi 与 lo 同净值 → penalty_first 恰为 0.0; 第二半 +0.03 > 0
        rows = (
            day_rows("20260310", 0.07, 0.02, 32)
            + day_rows("20260311", 0.01, 0.02, 32)
            + day_rows("20260312", 0.07, -0.02, 32)
            + day_rows("20260313", 0.01, 0.01, 32)
        )
        pooled = self._split(pd.DataFrame(rows).astype({"signal_date": str}))["pooled"]
        assert pooled["penalty_first"] == 0.0
        assert pooled["penalty_second"] != 0.0
        assert pooled["consistent"] is False
        # 双零形态: (0>0)==(0>0) → True 同号
        rows2 = (
            day_rows("20260310", 0.07, 0.02, 32)
            + day_rows("20260311", 0.01, 0.02, 32)
            + day_rows("20260312", 0.07, 0.02, 32)
            + day_rows("20260313", 0.01, 0.02, 32)
        )
        pooled2 = self._split(pd.DataFrame(rows2).astype({"signal_date": str}))["pooled"]
        assert pooled2["penalty_first"] == 0.0 and pooled2["penalty_second"] == 0.0
        assert pooled2["consistent"] is True

    def test_mounted_in_gap_anatomy_and_rendered(self):
        import pandas as pd
        from scripts.winrate_payoff_decomposition import decompose, render_md
        rows = []
        for i in range(80):
            first = i < 40
            half_hi = -0.03 if first else -0.02
            hi = i % 8 == 0
            rows.append({
                "symbol": f"{600000+i}",
                "signal_date": f"2026-0{1 if first else 4}-{(i % 40) % 28 + 1:02d}",
                "regime": "normal",
                "trigger_strength": 0.9,
                "gap_t1_open": 0.07 if hi else 0.01,
                "gross_ret_t10": (half_hi if hi else 0.01) + 0.0065,
                "gross_ret_t5": 0.02,
                "ret_close_anchor_t10": 0.03,
                "fillable": True, "gate_blocked": False, "degraded": False,
                "st_name": False, "industry_missing": False,
                "excluded_ticker": False, "price_ge_3": True,
            })
        payload = decompose(pd.DataFrame(rows), universes=("production_aligned",))
        sh = payload["universes"]["production_aligned"]["gap_anatomy"]["split_half"]
        assert sh["judgable_count"] >= 1
        md = render_md(payload, "20260901")
        assert "split-half" in md
        assert "verdict" in md or "判定" in md

    # --- R189 Op1: MD 渲染面 pooled 聚合罚分块 (fail-open 接线家族) ---

    _POOLED_FIXTURE = {
        "penalty_first": 0.0563,
        "penalty_second": 0.0313,
        "e_hi_first": -0.049,
        "e_hi_second": -0.0286,
        "n_hi_first": 91,
        "n_hi_second": 67,
        "consistent": True,
    }

    @staticmethod
    def _render_with_pooled(pooled):
        """构造最小可判定 split-half payload 并按参数注入 pooled (None=旧形态)。"""
        import pandas as pd
        from scripts.winrate_payoff_decomposition import decompose, render_md
        rows = []
        for i in range(80):
            first = i < 40
            half_hi = -0.03 if first else -0.02
            hi = i % 8 == 0
            rows.append({
                "symbol": f"{600000+i}",
                "signal_date": f"2026-0{1 if first else 4}-{(i % 40) % 28 + 1:02d}",
                "regime": "normal",
                "trigger_strength": 0.9,
                "gap_t1_open": 0.07 if hi else 0.01,
                "gross_ret_t10": (half_hi if hi else 0.01) + 0.0065,
                "gross_ret_t5": 0.02,
                "ret_close_anchor_t10": 0.03,
                "fillable": True, "gate_blocked": False, "degraded": False,
                "st_name": False, "industry_missing": False,
                "excluded_ticker": False, "price_ge_3": True,
            })
        payload = decompose(pd.DataFrame(rows), universes=("production_aligned",))
        sh = payload["universes"]["production_aligned"]["gap_anatomy"]["split_half"]
        if pooled is not None:
            sh["pooled"] = pooled
        return render_md(payload, "20260912")

    def test_render_md_pooled_bullet_present(self):
        md = self._render_with_pooled(dict(self._POOLED_FIXTURE))
        assert (
            "- **聚合罚分 (全强度池化, 执行面行直答层)**: 聚合罚分两半"
            " +5.63pp/+3.13pp 同号（高开子集期望 -4.90%/-2.86% · n 91/67）"
        ) in md

    def test_render_md_pooled_bullet_single_implementation_no_drift(self):
        """MD 列表项正文与操作员子句同源 (pooled_penalty_body 单一实现)。"""
        from src.screening.offensive.gap_disclosure import (
            pooled_penalty_body,
            pooled_penalty_clause,
        )
        pooled = dict(self._POOLED_FIXTURE)
        md = self._render_with_pooled(pooled)
        body = pooled_penalty_body(pooled)
        assert body is not None
        assert pooled_penalty_clause(pooled) == f" · {body}"
        assert f"**聚合罚分 (全强度池化, 执行面行直答层)**: {body}" in md

    def test_render_md_pooled_absent_old_report_unchanged(self):
        """旧报告 (无 pooled 键) → 列表项缺席, split-half 节与修复前逐字节一致。"""
        md = self._render_with_pooled(None)
        assert "聚合罚分" not in md
        assert "判定 (R15 合取判据镜像" in md  # 节内其余行照常

    def test_render_md_pooled_malformed_omitted(self):
        """畸形 pooled → 列表项省略, 零异常 (半真披露比无披露更有害)。"""
        md = self._render_with_pooled({"consistent": "yes", "penalty_first": 0.05})
        assert "聚合罚分" not in md
        small = dict(self._POOLED_FIXTURE)
        small["n_hi_second"] = 0  # consistent 与零计数并存 = 自相矛盾载荷
        md2 = self._render_with_pooled(small)
        assert "聚合罚分" not in md2


class TestBuildTimestampNotIdentity:
    """R93 Op1: built_at 是构建事件时间戳, 不是数据状态身份。

    夜度保鲜自动化 (court_nightly_refresh, 同数据跨日重建是常态) 下,
    built_at 在身份中会让前进门每天把『同数据重建』误判为前进, 写下
    『新日期旧数据』假判定记录 — R84 封锁过的病被自动化重新点燃。
    content_digest (R90 Op2) 已字节级判定数据身份, 构建时刻不再进身份
    (built_at 保留在 manifest 供表龄审计, 不进账本快照身份)。
    """

    _MANIFEST = {
        "built_at": "PLACEHOLDER",
        "window": {"start": "20250102", "end": "20260901", "sessions": 396},
        "formula_fingerprint": {"btst_breakout_sha256": "f" * 64},
        "universe_audit": {"days_checked": 396, "empty_days": 0},
    }

    def test_binding_ignores_manifest_build_timestamp(self, tmp_path):
        import pandas as pd
        from scripts.winrate_payoff_decomposition import court_binding
        table = tmp_path / "court.csv.gz"
        pd.DataFrame({"a": [1, 2]}).to_csv(table, index=False, compression="gzip")
        bindings = []
        for built_at in ("2026-09-01", "2026-09-02"):
            manifest = dict(self._MANIFEST, built_at=built_at)
            (tmp_path / "manifest_v1.json").write_text(
                json.dumps(manifest), encoding="utf-8")
            bindings.append(court_binding(table, rows=2))
        assert bindings[0] == bindings[1]  # 仅构建时刻不同 → 身份恒等

    def test_gate_skips_identical_data_rebuilt_next_day(self, tmp_path):
        """夜度不变式端到端: 同数据跨日重建 (binding 恒等) → skip 不写假记录。"""
        from scripts.winrate_payoff_decomposition import (
            load_trigger_ledger, record_trigger_status,
        )
        b_day = {"window_start": "20250102", "window_end": "20260901",
                 "rows": 1900, "formula_fingerprint": "ff",
                 "content_digest": "sha256:" + "c0" * 32,
                 "universe_audit_complete": True}
        ledger = tmp_path / "ledger.jsonl"
        trigger = TestCourtGrowthCoupling._trigger()
        record_trigger_status({"threshold_trigger": trigger}, "20260901",
                              ledger_path=ledger, court_binding=dict(b_day))
        meta = record_trigger_status({"threshold_trigger": trigger}, "20260902",
                                     ledger_path=ledger, court_binding=dict(b_day),
                                     require_advance=True)
        assert meta["recorded"] is False
        assert meta["reason"] == "court_not_advanced"
        assert [r["date"] for r in load_trigger_ledger(ledger)] == ["20260901"]


class TestThreshold060AnchorTrigger:
    """R100 Op1: 0.60 锚触发器 (条件③ 0.60-0.70 CI>0 ∧ 条件② 转负) 的判定面."""

    @staticmethod
    def _row(group, n, expectancy=None, ci=None):
        return {
            "group": group, "n": n, "wins": 0, "winrate": None,
            "avg_win": None, "avg_loss": None, "payoff": None,
            "expectancy": expectancy, "cluster_ci_low_90": ci,
            "attribution_vs_all": None,
        }

    def _rows(self, *, strong=None, mid=None, midhigh=None):
        rows = []
        if strong is not None:
            rows.append(self._row("strength=≥0.70", **strong))
        if mid is not None:
            rows.append(self._row("strength=0.50-0.60", **mid))
        if midhigh is not None:
            rows.append(self._row("strength=0.60-0.70", **midhigh))
        return rows

    def test_conjunction_060_armed_when_c3_and_c2_lit(self):
        status = threshold_trigger_status(self._rows(
            mid=dict(n=303, expectancy=-0.0097),
            midhigh=dict(n=340, expectancy=0.0101, ci=0.0007),
        ))
        c3 = status["condition_3_midhigh_bucket_ci_above_zero"]
        assert c3["lit"] is True and c3["judged"] is True
        assert status["conjunction_060_armed"] is True
        assert "0.50→0.60" in status["verdict_060"]

    def test_conjunction_060_not_armed_when_c2_positive(self):
        status = threshold_trigger_status(self._rows(
            mid=dict(n=303, expectancy=0.0017),
            midhigh=dict(n=340, expectancy=0.0101, ci=0.0007),
        ))
        assert status["condition_3_midhigh_bucket_ci_above_zero"]["lit"] is True
        assert status["conjunction_060_armed"] is False
        assert "被保留带站稳但被砍带未转负" in status["verdict_060"]

    def test_conjunction_060_not_armed_when_c3_ci_negative(self):
        status = threshold_trigger_status(self._rows(
            mid=dict(n=303, expectancy=-0.0097),
            midhigh=dict(n=340, expectancy=0.0101, ci=-0.0041),
        ))
        assert status["condition_3_midhigh_bucket_ci_above_zero"]["lit"] is False
        assert status["conjunction_060_armed"] is False
        assert "被砍带转负但被保留带未站稳" in status["verdict_060"]

    def test_anchors_can_diverge(self):
        """① 与 ③ 分歧形态: ≥0.70 站稳而 0.60-0.70 未站稳 —
        0.70 锚合取可武装而 0.60 锚不武装 (新锚更精确: 被保留带未站稳)."""
        status = threshold_trigger_status(self._rows(
            strong=dict(n=315, expectancy=0.0169, ci=0.0007),
            mid=dict(n=303, expectancy=-0.0097),
            midhigh=dict(n=340, expectancy=0.0101, ci=-0.0041),
        ))
        assert status["conjunction_armed"] is True
        assert status["conjunction_060_armed"] is False

    def test_c3_missing_row_not_judged(self):
        status = threshold_trigger_status(self._rows(
            mid=dict(n=303, expectancy=-0.0097)))
        c3 = status["condition_3_midhigh_bucket_ci_above_zero"]
        assert c3["judged"] is False and c3["lit"] is False
        assert "缺失" in c3["reason"]
        assert status["conjunction_060_armed"] is False

    def test_c3_small_n_not_judged(self):
        status = threshold_trigger_status(self._rows(
            mid=dict(n=303, expectancy=-0.0097),
            midhigh=dict(n=29, expectancy=0.03, ci=0.01),
        ))
        c3 = status["condition_3_midhigh_bucket_ci_above_zero"]
        assert c3["judged"] is False and c3["lit"] is False

    def test_c3_strictly_above_zero(self):
        status = threshold_trigger_status(self._rows(
            mid=dict(n=303, expectancy=-0.0097),
            midhigh=dict(n=340, expectancy=0.01, ci=0.0),
        ))
        assert status["condition_3_midhigh_bucket_ci_above_zero"]["lit"] is False

    def test_rule_060_preregistration_disclosed(self):
        status = threshold_trigger_status(self._rows())
        assert "R100" in status["rule_060"]
        assert "共享" in status["rule_060"]  # 条件② 耦合披露


class TestTriggerSnapshot060AndRender:
    """R100 Op2 对抗收口: 落账快照新字段三形态 + MD 060 行渲染.

    Op1 审查结论: 判定/计数/状态行四面语义正确 (含锚分歧), 缺口在快照
    写入形态与报告渲染无测试钉死 — 未来重构可静默丢 condition_3 字段或
    060 行而不红。
    """

    @staticmethod
    def _trigger060(c3_lit=True, c2_lit=False, n=300):
        return {
            "rule": "预注册触发器", "rule_060": "R100 0.60 锚",
            "anchor": "production_aligned/t10", "min_n": 30,
            "condition_1_strong_bucket_ci_above_zero": {
                "lit": True, "judged": True, "n": n, "stat": 0.0023},
            "condition_2_mid_bucket_expectancy_negative": {
                "lit": c2_lit, "judged": True, "n": n, "stat": 0.0097},
            "condition_3_midhigh_bucket_ci_above_zero": {
                "lit": c3_lit, "judged": True, "n": n, "stat": 0.0007},
            "conjunction_armed": False,
            "conjunction_060_armed": bool(c3_lit and c2_lit),
            "verdict": "测试夹具", "verdict_060": "测试夹具 060",
        }

    def test_snapshot_writes_060_fields(self, tmp_path):
        from scripts.winrate_payoff_decomposition import (
            record_trigger_status, load_trigger_ledger,
        )
        ledger = tmp_path / "ledger.jsonl"
        record_trigger_status(
            {"threshold_trigger": self._trigger060()}, "20260902", ledger_path=ledger
        )
        rec = load_trigger_ledger(ledger)[0]
        assert rec["condition_3"]["lit"] is True
        assert rec["condition_3"]["stat"] == 0.0007
        assert rec["conjunction_060_armed"] is False

    def test_old_form_payload_writes_old_form_record(self, tmp_path):
        """旧形态 payload (无 060 键) → 记录无新键, 不假装判定 (向后兼容)."""
        from scripts.winrate_payoff_decomposition import (
            record_trigger_status, load_trigger_ledger,
        )
        old_trigger = TestTriggerStabilityLedger._trigger()
        ledger = tmp_path / "ledger.jsonl"
        record_trigger_status(
            {"threshold_trigger": old_trigger}, "20260831", ledger_path=ledger
        )
        rec = load_trigger_ledger(ledger)[0]
        assert "condition_3" not in rec
        assert "conjunction_060_armed" not in rec

    def test_same_day_replace_upgrades_record_form(self, tmp_path):
        """同日以新形态重刷 → 当日记录升级含 060 键 (同日替换语义, 跨日旧记录不动)."""
        from scripts.winrate_payoff_decomposition import (
            record_trigger_status, load_trigger_ledger,
        )
        ledger = tmp_path / "ledger.jsonl"
        record_trigger_status(
            {"threshold_trigger": TestTriggerStabilityLedger._trigger()},
            "20260901", ledger_path=ledger,
        )
        record_trigger_status(
            {"threshold_trigger": self._trigger060()}, "20260901", ledger_path=ledger
        )
        records = load_trigger_ledger(ledger)
        assert len(records) == 1
        assert "condition_3" in records[0]

    def test_render_md_contains_060_lines(self):
        from scripts.winrate_payoff_decomposition import render_md
        payload = {
            "horizons": {},
            "threshold_trigger": self._trigger060(),
            "threshold_stability": {
                "records": 2, "first_date": "20260901", "last_date": "20260902",
                "condition_1_streak": 2, "condition_2_streak": 0,
                "conjunction_streak": 0, "max_conjunction_streak": 0,
                "condition_3_streak": 1, "conjunction_060_streak": 0,
                "max_conjunction_060_streak": 0,
            },
        }
        text = render_md(payload, "20260902")
        assert "条件③ 0.60-0.70 桶净口径 CI90 下界>0 (R100 预注册 2026-09-02)" in text
        assert "0.60 锚合取 (③∧②)" in text
        assert "条件②被两合取共享" in text
        assert "0.60 锚稳定计数" in text
        assert "条件③ 连亮 1/2" in text

    def test_build_backdated_registration_poC(self, tmp_path):
        """R113 P1 回溯注册 PoC (经 main 全链): 声明日期早于首次观测 →
        披露以观测日起算并明语标注, 亮不追溯。"""
        import pandas as pd
        from src.screening.offensive.threshold_trigger import (
            k_registration_hash,
        )
        from scripts import winrate_payoff_decomposition as mod
        rows = []
        for i in range(40):
            rows.append({
                "symbol": f"{600000+i}",
                "signal_date": f"2026-01-{(i % 20) + 1:02d}",
                "regime": "normal",
                "trigger_strength": 0.75 if i % 2 else 0.55,
                "gross_ret_t10": 0.03 * (1 if i % 2 else -1),
                "gross_ret_t5": 0.015,
                "fillable": True, "gate_blocked": False, "degraded": False,
                "st_name": False, "industry_missing": False,
                "excluded_ticker": False, "price_ge_3": True,
            })
        table = tmp_path / "court.csv.gz"
        pd.DataFrame(rows).to_csv(table, index=False)
        ledger = tmp_path / "trigger_ledger.jsonl"
        reg_payload = {
            "anchor": "production_aligned/t10", "k_070": 2,
            "registered_date": "20260101",  # 事后回溯声明
        }
        kfile = tmp_path / "k.json"
        kfile.write_text(json.dumps(reg_payload), encoding="utf-8")
        klog = tmp_path / "k_obs.jsonl"
        from datetime import date as _date
        today = _date.today().strftime("%Y%m%d")
        # 观测哈希绑定 load 归一化后的消费内容 (k_060 缺省补 None 等) —
        # 与 build 侧 observe_k_registration(load_k_registration(...)) 同一形态
        from src.screening.offensive.threshold_trigger import load_k_registration
        _, normalized = load_k_registration(kfile)
        klog.write_text(json.dumps({
            "observed_date": today,
            "k_hash": k_registration_hash(normalized),
            "declared_registered_date": "20260101",
        }), encoding="utf-8")
        rc = mod.main([
            "--court-table", str(table), "--report-dir", str(tmp_path / "rep"),
            "--trigger-ledger", str(ledger),
            "--k-registration", str(kfile),
            "--k-observation-log", str(klog),
        ])
        assert rc == 0
        stamp = _date.today().strftime("%Y%m%d")
        payload = json.loads(
            (tmp_path / "rep" / f"winrate_payoff_decomposition_{stamp}.json").read_text(encoding="utf-8")
        )
        k_disc = payload["threshold_k"]
        assert k_disc["state"] == "registered"
        assert k_disc["backdated"] is True
        assert k_disc["effective_registered_date"] == today
        assert "以观测日起算" in k_disc["line_070"]

    def test_build_unregistered_k_no_observation_write(self, tmp_path):
        """K 未注册 → 不写观测日志 (无注册即无观测对象)."""
        import pandas as pd
        from scripts import winrate_payoff_decomposition as mod
        rows = []
        for i in range(40):
            rows.append({
                "symbol": f"{600000+i}",
                "signal_date": f"2026-01-{(i % 20) + 1:02d}",
                "regime": "normal",
                "trigger_strength": 0.75 if i % 2 else 0.55,
                "gross_ret_t10": 0.03 * (1 if i % 2 else -1),
                "gross_ret_t5": 0.015,
                "fillable": True, "gate_blocked": False, "degraded": False,
                "st_name": False, "industry_missing": False,
                "excluded_ticker": False, "price_ge_3": True,
            })
        table = tmp_path / "court.csv.gz"
        pd.DataFrame(rows).to_csv(table, index=False)
        klog = tmp_path / "k_obs.jsonl"
        rc = mod.main([
            "--court-table", str(table), "--report-dir", str(tmp_path / "rep"),
            "--trigger-ledger", str(tmp_path / "trigger_ledger.jsonl"),
            "--k-registration", str(tmp_path / "absent.json"),
            "--k-observation-log", str(klog),
        ])
        assert rc == 0
        assert not klog.exists()


def test_main_preserves_disclosure_when_ledger_write_failed(tmp_path):
    """F1 (修复前 RED = 稳定性/K 披露静默丢失): 账本写失败只降级写面本身 —
    稳定计数与 K 披露仍读账本现状真话, MD 渲染显式告警行, 报告生成本体不阻断
    (与 --daily-action 触发器行直读账本的降级口径一致)."""
    import pandas as pd
    from datetime import date as _date
    from scripts import winrate_payoff_decomposition as mod
    rows = []
    for i in range(40):
        rows.append({
            "symbol": f"{600000+i}",
            "signal_date": f"2026-01-{(i % 20) + 1:02d}",
            "regime": "normal",
            "trigger_strength": 0.75 if i % 2 else 0.55,
            "gross_ret_t10": 0.03 * (1 if i % 2 else -1),
            "gross_ret_t5": 0.015,
            "fillable": True, "gate_blocked": False, "degraded": False,
            "st_name": False, "industry_missing": False,
            "excluded_ticker": False, "price_ge_3": True,
        })
    table = tmp_path / "court.csv.gz"
    pd.DataFrame(rows).to_csv(table, index=False)
    ledger_dir = tmp_path / "ledger_dir"
    ledger_dir.mkdir()  # 目录路径 → os.replace 失败 → write_failed
    kfile = tmp_path / "k.json"
    kfile.write_text(json.dumps({
        "anchor": "production_aligned/t10", "k_070": 5,
        "registered_date": "20260101",
    }), encoding="utf-8")
    rc = mod.main([
        "--court-table", str(table), "--report-dir", str(tmp_path / "rep"),
        "--trigger-ledger", str(ledger_dir),
        "--k-registration", str(kfile),
        "--k-observation-log", str(tmp_path / "k_obs.jsonl"),
    ])
    assert rc == 0
    stamp = _date.today().strftime("%Y%m%d")
    payload = json.loads(
        (tmp_path / "rep" / f"winrate_payoff_decomposition_{stamp}.json").read_text(encoding="utf-8")
    )
    assert payload["threshold_record"]["reason"] == "write_failed"
    assert isinstance(payload["threshold_stability"], dict)
    assert payload["threshold_k"]["state"] == "registered"
    md = (tmp_path / "rep" / f"winrate_payoff_decomposition_{stamp}.md").read_text(encoding="utf-8")
    assert "触发器账本写入失败" in md

    def test_advance_gate_corrupt_manifest_none_digest_corner(self, tmp_path):
        """R130 Op3 B2 (已知边界钉死): 连续两次 manifest 损坏 (digest=None)
        的 build 互不等 → 门放行双记录 — 宁多记不漏记方向, 不假装能判等。"""
        from scripts.winrate_payoff_decomposition import (
            record_trigger_status, load_trigger_ledger,
        )
        ledger = tmp_path / "ledger.jsonl"
        corrupt_a = dict(self.BINDING_A, content_digest=None)
        corrupt_b = dict(self.BINDING_A, content_digest=None, window_end="20260831")
        record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260830",
            ledger_path=ledger, court_binding=corrupt_a,
        )
        meta = record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260831",
            ledger_path=ledger, court_binding=corrupt_b,
            require_advance=True,
        )
        assert meta["recorded"] is True
        assert len(load_trigger_ledger(ledger)) == 2

    def test_gate_purity_implies_fold_idle(self, tmp_path):
        """R130 Op3 B4 (Op1+Op2 合取不变式): 门正常时折叠恒空闲 —
        请求态漂移被写面拒收后, 账本/稳定计数零增长且 folded_duplicates=0
        (读面折叠是纵深防御, 稳态下不参与)。"""
        from scripts.winrate_payoff_decomposition import (
            record_trigger_status, load_trigger_ledger, trigger_stability,
        )
        from src.screening.offensive.threshold_trigger import trigger_stability as tt_stability
        ledger = tmp_path / "ledger.jsonl"
        record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260904",
            ledger_path=ledger, court_binding=dict(self.BINDING_A),
        )
        drift_meta = record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260905",
            ledger_path=ledger, court_binding=dict(self.BINDING_A, window_end="20260905"),
            require_advance=True,
        )
        assert drift_meta["recorded"] is False  # 门拒收重复判定
        # 新数据前进 (day3) 正常落账:
        record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260906",
            ledger_path=ledger, court_binding=dict(self.BINDING_B),
        )
        st = tt_stability(load_trigger_ledger(ledger))
        assert st["records"] == 2
        assert st["folded_duplicates"] == 0  # 折叠空闲 (门已拒收)
        assert st["condition_1_streak"] == 2

    def test_advance_gate_cross_family_same_verdict_on_drift(self, tmp_path):
        """R130 Op3 B3 (跨族单实现保证): 同一请求态漂移下强度族与日层族
        gate 必须同判 court_not_advanced — court_data_state_equal 单一实现
        的存在性宣言, 两族账本零追加。"""
        from scripts.winrate_payoff_decomposition import (
            record_trigger_status, load_trigger_ledger,
        )
        from scripts.btst_signal_day_cohort import record_cohort_trigger_status
        from src.screening.offensive.cohort_trigger import load_cohort_trigger_ledger
        strength_ledger = tmp_path / "ledger.jsonl"
        cohort_ledger = tmp_path / "cohort_ledger.jsonl"
        record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260904",
            ledger_path=strength_ledger, court_binding=dict(self.BINDING_A),
        )
        record_cohort_trigger_status(
            {"cohort_trigger": {"anchor": "a", "min_n": 30}}, "20260904",
            ledger_path=cohort_ledger, court_binding=dict(self.BINDING_A),
        )
        drifted = dict(self.BINDING_A, window_end="20260905")
        s_meta = record_trigger_status(
            {"threshold_trigger": self._trigger()}, "20260905",
            ledger_path=strength_ledger, court_binding=drifted,
            require_advance=True,
        )
        c_meta = record_cohort_trigger_status(
            {"cohort_trigger": {"anchor": "a", "min_n": 30}}, "20260905",
            ledger_path=cohort_ledger, court_binding=drifted,
            require_advance=True,
        )
        assert s_meta["recorded"] is False and s_meta["reason"] == "court_not_advanced"
        assert c_meta["recorded"] is False and c_meta["reason"] == "court_not_advanced"
        assert [r["date"] for r in load_trigger_ledger(strength_ledger)] == ["20260904"]
        assert [r["date"] for r in load_cohort_trigger_ledger(cohort_ledger)] == ["20260904"]


class TestCrossWindowValidation:
    """R136 Op1: 跨窗口外部验证披露 — 早期窗口 (2022-2024 交集宇宙) 与当前
    窗口的强度结构方向相反 (当前 ≥0.70 最好 / 早期 ≥0.70 最差), 而触发器
    账本只由当前窗口驱动 — owner K 预注册→正式评估的决策面必须看得见早期
    反证。对比读自早期报告结构化 payload (同一工具产出), 零重算零判定;
    fail-open: early 未构建形态零字节新增, 报告在场但畸形 → 显式不可用。
    """

    @staticmethod
    def _row(group, n, expectancy, winrate):
        return {
            "group": group, "n": n, "wins": 0, "winrate": winrate,
            "avg_win": None, "avg_loss": None, "payoff": None,
            "expectancy": expectancy, "cluster_ci_low_90": None,
            "attribution_vs_all": None,
        }

    CURRENT_ROWS = [
        _row("ALL", 1627, 0.0055, 0.4456),
        _row("strength=<0.50", 515, -0.0209, 0.4078),
        _row("strength=0.50-0.60", 341, 0.0014, 0.4575),
        _row("strength=0.60-0.70", 431, 0.0103, 0.4501),
        _row("strength=≥0.70", 340, 0.0169, 0.4853),
    ]
    EARLY_ROWS = [
        _row("ALL", 3597, 0.0251, 0.5402),
        _row("strength=<0.50", 1259, 0.0353, 0.5624),
        _row("strength=0.50-0.60", 847, 0.0378, 0.5915),
        _row("strength=0.60-0.70", 942, 0.0191, 0.5446),
        _row("strength=≥0.70", 549, -0.0075, 0.4026),
    ]

    @staticmethod
    def _trigger(c1_stat, c1_lit, c2_stat, c2_lit, armed=False):
        return {
            "anchor": "production_aligned/t10",
            "min_n": 30,
            "condition_1_strong_bucket_ci_above_zero": {
                "lit": c1_lit, "judged": True, "n": 340, "stat": c1_stat,
            },
            "condition_2_mid_bucket_expectancy_negative": {
                "lit": c2_lit, "judged": True, "n": 341, "stat": c2_stat,
            },
            "conjunction_armed": armed,
        }

    def _current_payload(self):
        return {
            "court_rows": 1950,
            "universes": {
                "production_aligned": {"horizons": {"t10": [dict(r) for r in self.CURRENT_ROWS]}}
            },
            "threshold_trigger": self._trigger(0.0007, True, 0.0014, False),
        }

    @staticmethod
    def _early_payload():
        return {
            "court_rows": 4161,
            "universes": {
                "production_aligned": {"horizons": {"t10": [
                    dict(r) for r in TestCrossWindowValidation.EARLY_ROWS
                ]}}
            },
            "threshold_trigger": TestCrossWindowValidation._trigger(
                -0.0168, False, 0.0378, False
            ),
        }

    @staticmethod
    def _write_early_report(tmp_path, payload, date="20260901"):
        early_dir = tmp_path / "early_window"
        early_dir.mkdir(exist_ok=True)
        (early_dir / f"winrate_payoff_decomposition_{date}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        return early_dir

    @staticmethod
    def _write_manifest(path, sha="a" * 64, window=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {"formula_fingerprint": {"btst_breakout_sha256": sha}}
        if window is not None:
            manifest["window"] = window
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def _attach(self, payload, tmp_path, *, early_dir=True, early_manifest=True,
                main_manifest=True, early_payload=None):
        from scripts.winrate_payoff_decomposition import (
            attach_cross_window_validation,
        )
        kw = {}
        if early_dir:
            kw["early_report_dir"] = self._write_early_report(
                tmp_path, early_payload if early_payload is not None else self._early_payload()
            )
        else:
            kw["early_report_dir"] = tmp_path / "absent_early_window"
        kw["early_manifest_path"] = (
            self._write_manifest(
                tmp_path / "early_manifest" / "manifest_v1.json",
                window={"start": "20220104", "end": "20241231", "sessions": 726},
            )
            if early_manifest
            else tmp_path / "absent_early_manifest.json"
        )
        kw["main_manifest_path"] = (
            self._write_manifest(tmp_path / "main_manifest" / "manifest_v1.json")
            if main_manifest
            else tmp_path / "absent_main_manifest.json"
        )
        return attach_cross_window_validation(payload, **kw)

    def test_attach_builds_structured_key(self, tmp_path):
        cw = self._attach(self._current_payload(), tmp_path)["cross_window_validation"]
        assert cw["available"] is True
        assert cw["early_report_date"] == "20260901"
        assert cw["early_court_rows"] == 4161
        assert cw["early_window"] == {
            "start": "20220104", "end": "20241231", "sessions": 726,
        }
        assert cw["formula_fingerprint_match"] is True
        buckets = {b["bucket"]: b for b in cw["buckets"]}
        assert set(buckets) == {
            "ALL", "strength=<0.50", "strength=0.50-0.60",
            "strength=0.60-0.70", "strength=≥0.70",
        }
        # 方向相反实锤: ≥0.70 当前 +0.0169 vs 早期 -0.0075 → 相反
        strong = buckets["strength=≥0.70"]
        assert strong["current"]["e"] == 0.0169 and strong["early"]["e"] == -0.0075
        assert strong["sign_agree"] is False
        # <0.50 亦相反 (当前负 / 早期正)
        assert buckets["strength=<0.50"]["sign_agree"] is False
        assert buckets["ALL"]["sign_agree"] is True
        assert buckets["strength=0.50-0.60"]["sign_agree"] is True
        # 触发器双窗: 当前 ①亮 ②未亮 / 早期 ①②均未亮
        assert cw["trigger"]["condition_1"]["current"] == {
            "lit": True, "stat": 0.0007, "n": 340,
        }
        assert cw["trigger"]["condition_1"]["early"]["lit"] is False
        assert cw["trigger"]["condition_2"]["early"]["stat"] == 0.0378
        assert cw["trigger"]["conjunction_armed"] == {
            "current": False, "early": False,
        }
        assert len(cw["caveats"]) == 3

    def test_render_md_full_section(self, tmp_path):
        from scripts.winrate_payoff_decomposition import render_md
        payload = self._attach(self._current_payload(), tmp_path)
        md = render_md(payload, "20260906")
        assert "### 跨窗口外部验证 (方向性, 只披露不判定)" in md
        assert "20220104..20241231" in md
        assert "公式指纹: 一致" in md
        assert "| strength=≥0.70 | +1.69% | 340 | -0.75% | 549 | **相反** |" in md
        assert "当前 点亮 (+0.07%) · 早期 未点亮 (-1.68%)" in md
        assert "当前 未点亮 (+0.14%) · 早期 未点亮 (+3.78%)" in md
        assert "合取 (①∧②): 当前 未点亮 · 早期 未点亮" in md
        assert "幸存者偏差不可消除" in md
        assert "只披露不判定" in md

    def test_fingerprint_mismatch_disclosed(self, tmp_path):
        from scripts.winrate_payoff_decomposition import render_md
        payload = self._current_payload()
        early_dir = self._write_early_report(tmp_path, self._early_payload())
        from scripts.winrate_payoff_decomposition import (
            attach_cross_window_validation,
        )
        attach_cross_window_validation(
            payload,
            early_report_dir=early_dir,
            early_manifest_path=self._write_manifest(
                tmp_path / "em" / "m.json", sha="b" * 64
            ),
            main_manifest_path=self._write_manifest(
                tmp_path / "mm" / "m.json", sha="a" * 64
            ),
        )
        cw = payload["cross_window_validation"]
        assert cw["formula_fingerprint_match"] is False
        md = render_md(payload, "20260906")
        assert "公式指纹: **不一致**" in md

    def test_manifest_missing_fingerprint_none(self, tmp_path):
        from scripts.winrate_payoff_decomposition import render_md
        payload = self._attach(
            self._current_payload(), tmp_path,
            early_manifest=False, main_manifest=False,
        )
        assert payload["cross_window_validation"]["formula_fingerprint_match"] is None
        md = render_md(payload, "20260906")
        assert "公式指纹: 不可得" in md

    def test_missing_early_dir_zero_delta(self, tmp_path):
        """未构建形态: 键缺席 + 渲染逐字节不变 (fail-open 零噪声)。"""
        from scripts.winrate_payoff_decomposition import render_md
        payload = self._current_payload()
        md_before = render_md(payload, "20260906")
        out = self._attach(payload, tmp_path, early_dir=False)
        assert "cross_window_validation" not in out
        assert render_md(out, "20260906") == md_before
        assert "跨窗口外部验证" not in md_before

    def test_empty_dir_no_key(self, tmp_path):
        from scripts.winrate_payoff_decomposition import (
            attach_cross_window_validation,
        )
        payload = self._current_payload()
        empty = tmp_path / "empty_early"
        empty.mkdir()
        attach_cross_window_validation(payload, early_report_dir=empty)
        assert "cross_window_validation" not in payload

    def test_corrupt_report_named_absence(self, tmp_path):
        """报告在场但损坏 JSON → available=False 显式不可用 (不静默消失)。"""
        from scripts.winrate_payoff_decomposition import render_md
        early_dir = tmp_path / "early_window"
        early_dir.mkdir()
        (early_dir / "winrate_payoff_decomposition_20260901.json").write_text(
            "{not json", encoding="utf-8"
        )
        payload = self._current_payload()
        from scripts.winrate_payoff_decomposition import (
            attach_cross_window_validation,
        )
        attach_cross_window_validation(
            payload, early_report_dir=early_dir,
            early_manifest_path=tmp_path / "x.json",
            main_manifest_path=tmp_path / "y.json",
        )
        cw = payload["cross_window_validation"]
        assert cw == {"available": False, "reason": "early_report_unreadable"}
        md = render_md(payload, "20260906")
        assert "跨窗口外部验证不可用 (early_report_unreadable)" in md

    def test_malformed_early_payload_named(self, tmp_path):
        """合法 JSON 但缺 production_aligned 宇宙 → 显式 malformed。"""
        from scripts.winrate_payoff_decomposition import render_md
        payload = self._attach(
            self._current_payload(), tmp_path, early_payload={"court_rows": 1}
        )
        cw = payload["cross_window_validation"]
        assert cw == {"available": False, "reason": "early_report_malformed"}
        assert "跨窗口外部验证不可用 (early_report_malformed)" in render_md(
            payload, "20260906"
        )

    def test_current_universe_missing_named(self, tmp_path):
        payload = {"threshold_trigger": self._trigger(0.0, False, 0.0, False)}
        cw = self._attach(payload, tmp_path)["cross_window_validation"]
        assert cw == {"available": False, "reason": "current_universe_missing"}

    def test_missing_bucket_group_honest_dash(self, tmp_path):
        """早期报告缺某桶分组 → 该侧 '—' 且 sign_agree None (不假装一致)。"""
        from scripts.winrate_payoff_decomposition import render_md
        early = self._early_payload()
        early["universes"]["production_aligned"]["horizons"]["t10"] = [
            r for r in early["universes"]["production_aligned"]["horizons"]["t10"]
            if r["group"] != "strength=≥0.70"
        ]
        payload = self._attach(self._current_payload(), tmp_path, early_payload=early)
        buckets = {b["bucket"]: b for b in payload["cross_window_validation"]["buckets"]}
        strong = buckets["strength=≥0.70"]
        assert strong["early"] == {"e": None, "n": None}
        assert strong["sign_agree"] is None
        md = render_md(payload, "20260906")
        assert "| strength=≥0.70 | +1.69% | 340 | — | — | — |" in md

    def test_poisoned_cells_not_fake_values(self, tmp_path):
        """NaN/字符串期望/bool n/字符串 n → 全 None (R119 P1 家族纪律)。"""
        early = self._early_payload()
        rows = early["universes"]["production_aligned"]["horizons"]["t10"]
        for row in rows:
            if row["group"] == "strength=≥0.70":
                row["expectancy"] = float("nan")
                row["n"] = True
            if row["group"] == "ALL":
                row["expectancy"] = "banana"
                row["n"] = "3597"
        payload = self._attach(self._current_payload(), tmp_path, early_payload=early)
        buckets = {b["bucket"]: b for b in payload["cross_window_validation"]["buckets"]}
        assert buckets["strength=≥0.70"]["early"] == {"e": None, "n": None}
        assert buckets["strength=≥0.70"]["sign_agree"] is None
        assert buckets["ALL"]["early"] == {"e": None, "n": None}

    def test_zero_expectancy_sign_agree_none(self, tmp_path):
        early = self._early_payload()
        for row in early["universes"]["production_aligned"]["horizons"]["t10"]:
            if row["group"] == "strength=0.60-0.70":
                row["expectancy"] = 0.0
        payload = self._attach(self._current_payload(), tmp_path, early_payload=early)
        buckets = {b["bucket"]: b for b in payload["cross_window_validation"]["buckets"]}
        assert buckets["strength=0.60-0.70"]["sign_agree"] is None

    def test_non_dict_rows_and_buckets_skipped(self, tmp_path):
        """畸形行/畸形桶静默跳过, 不炸不假装 (形状畸形由缺组形态披露)。"""
        early = self._early_payload()
        rows = early["universes"]["production_aligned"]["horizons"]["t10"]
        rows[0] = "not-a-dict"
        payload = self._attach(self._current_payload(), tmp_path, early_payload=early)
        buckets = payload["cross_window_validation"]["buckets"]
        assert buckets[0]["early"]["e"] is None  # ALL 行被跳过 → 缺席披露
        assert buckets[1]["sign_agree"] is False  # 其余桶正常对比


class TestCrossWindowTripwires:
    """R136 Op2 对抗审查 PoC 三连 RED→GREEN — Op1 读取-拼装面的三族同源
    缺陷 (R115b 未来日期 / R80 兄弟工件混入 / R135 重复不去重 的镜像),
    每条绊线 typed reason fail-closed 到 available=False, 证据真实性优先。
    """

    def _early_dir_with(self, tmp_path, files: dict):
        early_dir = tmp_path / "early_window"
        early_dir.mkdir(exist_ok=True)
        for name, payload in files.items():
            (early_dir / name).write_text(json.dumps(payload), encoding="utf-8")
        return early_dir

    def _manifests(
        self,
        tmp_path,
        *,
        early_rows=4161,
        early_rows_present=True,
        early_pinned=None,
    ):
        em = tmp_path / "em.json"
        mm = tmp_path / "mm.json"
        early = {
            "formula_fingerprint": {"btst_breakout_sha256": "a" * 64},
            "window": {"start": "20220104", "end": "20241231", "sessions": 726},
        }
        if early_rows_present:
            early["rows"] = early_rows
        if early_pinned is not None:
            early["pinned_report_digests"] = early_pinned
        em.write_text(json.dumps(early))
        mm.write_text(json.dumps({
            "formula_fingerprint": {"btst_breakout_sha256": "a" * 64},
            "window": {"start": "20250701", "end": "20260906", "sessions": 290},
        }))
        return em, mm

    def _attach(self, payload, early_dir, em, mm):
        from scripts.winrate_payoff_decomposition import (
            attach_cross_window_validation,
        )
        return attach_cross_window_validation(
            payload,
            early_report_dir=early_dir,
            early_manifest_path=em,
            main_manifest_path=mm,
        )

    def test_poc_a_future_dated_report_rejected(self, tmp_path):
        """RED 实锤: 字典序『最新』选择被 20990101 毒值报告劫持 (E=0.99 入
        对比表)。修复后 = available=False typed reason, 不以未来证据披露。"""
        from scripts.winrate_payoff_decomposition import render_md
        good = TestCrossWindowValidation._early_payload()
        poison = TestCrossWindowValidation._early_payload()
        poison["universes"]["production_aligned"]["horizons"]["t10"][0][
            "expectancy"
        ] = 0.99
        early_dir = self._early_dir_with(tmp_path, {
            "winrate_payoff_decomposition_20260901.json": good,
            "winrate_payoff_decomposition_20990101.json": poison,
        })
        em, mm = self._manifests(tmp_path)
        payload = TestCrossWindowValidation()._current_payload()
        self._attach(payload, early_dir, em, mm)
        cw = payload["cross_window_validation"]
        assert cw == {"available": False, "reason": "early_report_future_dated"}
        md = render_md(payload, "20260906")
        assert "跨窗口外部验证不可用 (early_report_future_dated)" in md

    def test_poc_a_future_precedes_malformed(self, tmp_path):
        """绊线顺序: 未来日期优先于畸形判定 (日期面在最外层)。"""
        poison = {"universes": "not-a-dict"}
        early_dir = self._early_dir_with(tmp_path, {
            "winrate_payoff_decomposition_20990101.json": poison,
        })
        em, mm = self._manifests(tmp_path)
        payload = TestCrossWindowValidation()._current_payload()
        self._attach(payload, early_dir, em, mm)
        assert payload["cross_window_validation"]["reason"] == (
            "early_report_future_dated"
        )

    def test_poc_b_foreign_window_tripwire(self, tmp_path):
        """RED 实锤: 当前窗口 payload 混入 early 目录 → 双窗自比全『一致』
        假安心。修复后 = manifest rows↔court_rows 不等即 typed 拒绝。"""
        from scripts.winrate_payoff_decomposition import render_md
        foreign = TestCrossWindowValidation()._current_payload()  # court_rows=1950
        early_dir = self._early_dir_with(tmp_path, {
            "winrate_payoff_decomposition_20260907.json": foreign,
        })
        em, mm = self._manifests(tmp_path, early_rows=4161)
        payload = TestCrossWindowValidation()._current_payload()
        self._attach(payload, early_dir, em, mm)
        cw = payload["cross_window_validation"]
        assert cw == {"available": False, "reason": "early_report_foreign_window"}
        assert "跨窗口外部验证不可用 (early_report_foreign_window)" in render_md(
            payload, "20260906"
        )

    def test_poc_b_rows_missing_unchecked(self, tmp_path):
        """manifest 缺 rows 键 = 绊线未校验 (fail-open), 对比照常披露。"""
        early_dir = self._early_dir_with(tmp_path, {
            "winrate_payoff_decomposition_20260901.json":
                TestCrossWindowValidation._early_payload(),
        })
        em, mm = self._manifests(tmp_path, early_rows_present=False)
        payload = TestCrossWindowValidation()._current_payload()
        self._attach(payload, early_dir, em, mm)
        assert payload["cross_window_validation"]["available"] is True

    def test_poc_c_duplicate_groups_rejected(self, tmp_path):
        """RED 实锤: 重复 ALL 行静默 last-wins 取毒值。修复后 = 选中组重复
        一律冲突 (R135 Op2 merkle 纪律镜像), typed reason。"""
        from scripts.winrate_payoff_decomposition import render_md
        dup = TestCrossWindowValidation._early_payload()
        dup["universes"]["production_aligned"]["horizons"]["t10"].append(
            TestCrossWindowValidation._row("ALL", 3597, 0.99, 0.5)
        )
        early_dir = self._early_dir_with(tmp_path, {
            "winrate_payoff_decomposition_20260901.json": dup,
        })
        em, mm = self._manifests(tmp_path)
        payload = TestCrossWindowValidation()._current_payload()
        self._attach(payload, early_dir, em, mm)
        cw = payload["cross_window_validation"]
        assert cw == {"available": False, "reason": "early_report_duplicate_groups"}
        assert "跨窗口外部验证不可用 (early_report_duplicate_groups)" in render_md(
            payload, "20260906"
        )

    def test_poc_c_non_selected_group_duplicates_tolerated(self, tmp_path):
        """选中组集合之外的重复组 (如 regime=normal) 不触发绊线 — 绊线只
        保护进入对比表的组, 不越权管制整表。"""
        dup = TestCrossWindowValidation._early_payload()
        rows = dup["universes"]["production_aligned"]["horizons"]["t10"]
        rows.append(TestCrossWindowValidation._row("regime=normal", 100, 0.01, 0.5))
        rows.append(TestCrossWindowValidation._row("regime=normal", 100, 0.02, 0.5))
        early_dir = self._early_dir_with(tmp_path, {
            "winrate_payoff_decomposition_20260901.json": dup,
        })
        em, mm = self._manifests(tmp_path)
        payload = TestCrossWindowValidation()._current_payload()
        self._attach(payload, early_dir, em, mm)
        assert payload["cross_window_validation"]["available"] is True

    def test_clean_early_report_still_passes_tripwires(self, tmp_path):
        """界内数据零回归: 合法早报告 (rows=4161=manifest) 三绊线全过。"""
        early_dir = self._early_dir_with(tmp_path, {
            "winrate_payoff_decomposition_20260901.json":
                TestCrossWindowValidation._early_payload(),
        })
        em, mm = self._manifests(tmp_path, early_rows=4161)
        payload = TestCrossWindowValidation()._current_payload()
        self._attach(payload, early_dir, em, mm)
        cw = payload["cross_window_validation"]
        assert cw["available"] is True
        assert cw["early_report_date"] == "20260901"

    def test_future_mixed_corrupt_dir_future_dated_reason(self, tmp_path):
        """R137 Op1 分诊: 未来日期文件在场 (哪怕本身损坏) → reason 指 name
        未来日期劫持, 不退 unreadable — 守卫下沉共享读取体后 selected 面已
        拒, 披露粒度由本分诊保住 (修复前: 损坏的未来文件被选中解析失败 →
        found=None → has_files → 误报 unreadable)。"""
        good = TestCrossWindowValidation._early_payload()
        early_dir = self._early_dir_with(tmp_path, {
            "winrate_payoff_decomposition_20260901.json": good,
            "winrate_payoff_decomposition_20990101.json": {"broken": True},
        })
        # 毒文件写坏 JSON 形态 (字符串非合法 JSON) 以覆盖解析失败形态
        (early_dir / "winrate_payoff_decomposition_20990101.json").write_text(
            "\x00 not json", encoding="utf-8"
        )
        em, mm = self._manifests(tmp_path)
        payload = TestCrossWindowValidation()._current_payload()
        self._attach(payload, early_dir, em, mm)
        assert payload["cross_window_validation"]["reason"] == (
            "early_report_future_dated"
        )

    def test_corrupt_newest_without_future_still_unreadable(self, tmp_path):
        """R137 Op1 回归锚: 纯损坏 (无未来日期文件) 分诊不变 — typed reason
        仍为 unreadable, 分诊不误伤既有异常命名。"""
        good = TestCrossWindowValidation._early_payload()
        early_dir = self._early_dir_with(tmp_path, {
            "winrate_payoff_decomposition_20260901.json": good,
        })
        (early_dir / "winrate_payoff_decomposition_20260906.json").write_text(
            "\x00 not json", encoding="utf-8"
        )
        em, mm = self._manifests(tmp_path)
        payload = TestCrossWindowValidation()._current_payload()
        self._attach(payload, early_dir, em, mm)
        assert payload["cross_window_validation"]["reason"] == (
            "early_report_unreadable"
        )


class TestEarlyReportContentDigestBinding:
    """R137 Op3 (R136 登记第二开放项收口): 早期报告 content_digest 身份绑定。

    行数绊线 (foreign_window) 是必要非充分身份 — 同形不保证同质, 字节级
    替换 (同行数毒化重写) 此前不可检测。manifest 可选 pinned_report_digests
    (文件名 → sha256) 使 owner 可一次性冻结报告身份, 此后任何字节级替换
    typed 拒绝; 未 pin → fail-open 如实披露 (与 rows 缺键同纪律)。
    """

    def _early_dir_with(self, tmp_path, files: dict):
        early_dir = tmp_path / "early_window"
        early_dir.mkdir(exist_ok=True)
        for name, payload in files.items():
            (early_dir / name).write_text(json.dumps(payload), encoding="utf-8")
        return early_dir

    def _manifests(self, tmp_path, *, early_pinned=None):
        em = tmp_path / "em.json"
        mm = tmp_path / "mm.json"
        early = {
            "formula_fingerprint": {"btst_breakout_sha256": "a" * 64},
            "window": {"start": "20220104", "end": "20241231", "sessions": 726},
            "rows": 4161,
        }
        if early_pinned is not None:
            early["pinned_report_digests"] = early_pinned
        em.write_text(json.dumps(early))
        mm.write_text(json.dumps({
            "formula_fingerprint": {"btst_breakout_sha256": "a" * 64},
            "window": {"start": "20250701", "end": "20260906", "sessions": 290},
        }))
        return em, mm

    def _attach(self, payload, early_dir, em, mm):
        from scripts.winrate_payoff_decomposition import (
            attach_cross_window_validation,
        )
        return attach_cross_window_validation(
            payload,
            early_report_dir=early_dir,
            early_manifest_path=em,
            main_manifest_path=mm,
        )

    @staticmethod
    def _digest(path) -> str:
        import hashlib
        return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def test_tampered_report_rejected_when_pinned(self, tmp_path):
        """篡改 PoC RED→GREEN: pin 后字节级替换 (同行数毒值 E=0.99) → typed
        拒绝。修复前 = 行数绊线通过, 对比表静默采用毒值。"""
        from scripts.winrate_payoff_decomposition import render_md
        good = TestCrossWindowValidation._early_payload()
        early_dir = self._early_dir_with(tmp_path, {
            "winrate_payoff_decomposition_20260901.json": good,
        })
        target = early_dir / "winrate_payoff_decomposition_20260901.json"
        real_digest = self._digest(target)
        em, mm = self._manifests(
            tmp_path,
            early_pinned={"winrate_payoff_decomposition_20260901.json": real_digest},
        )
        payload = TestCrossWindowValidation()._current_payload()
        self._attach(payload, early_dir, em, mm)
        assert payload["cross_window_validation"]["available"] is True

        # 字节级替换: 同文件名同行数, ALL 行 E 换毒值 (重写不改 JSON 行数)
        poisoned = TestCrossWindowValidation._early_payload()
        for row in poisoned["universes"]["production_aligned"]["horizons"]["t10"]:
            if row["group"] == "ALL":
                row["expectancy"] = 0.99
        target.write_text(json.dumps(poisoned), encoding="utf-8")
        payload2 = TestCrossWindowValidation()._current_payload()
        self._attach(payload2, early_dir, em, mm)
        cw = payload2["cross_window_validation"]
        assert cw == {"available": False, "reason": "early_report_digest_mismatch"}
        assert "跨窗口外部验证不可用 (early_report_digest_mismatch)" in render_md(
            payload2, "20260906"
        )

    def test_pinned_match_discloses_digest_and_state(self, tmp_path):
        """pin 匹配 → available=true + pinned_digest_match=true + digest 与
        文件字节 sha256 逐位一致 (sha256: 前缀, court_binding 同约定)。"""
        good = TestCrossWindowValidation._early_payload()
        early_dir = self._early_dir_with(tmp_path, {
            "winrate_payoff_decomposition_20260901.json": good,
        })
        real_digest = self._digest(early_dir / "winrate_payoff_decomposition_20260901.json")
        em, mm = self._manifests(
            tmp_path,
            early_pinned={"winrate_payoff_decomposition_20260901.json": real_digest},
        )
        payload = TestCrossWindowValidation()._current_payload()
        self._attach(payload, early_dir, em, mm)
        cw = payload["cross_window_validation"]
        assert cw["available"] is True
        assert cw["pinned_digest_match"] is True
        assert cw["early_report_content_digest"] == real_digest

    def test_unpinned_fail_open_disclosed(self, tmp_path):
        """未 pin → pinned_digest_match=None 对比照常披露 (fail-open), digest
        仍落 payload (可复现/供 owner 后续 pin)。"""
        good = TestCrossWindowValidation._early_payload()
        early_dir = self._early_dir_with(tmp_path, {
            "winrate_payoff_decomposition_20260901.json": good,
        })
        em, mm = self._manifests(tmp_path)
        payload = TestCrossWindowValidation()._current_payload()
        self._attach(payload, early_dir, em, mm)
        cw = payload["cross_window_validation"]
        assert cw["available"] is True
        assert cw["pinned_digest_match"] is None
        assert cw["early_report_content_digest"].startswith("sha256:")
        assert len(cw["early_report_content_digest"]) == len("sha256:") + 64

    def test_reread_failure_fail_closed(self, tmp_path):
        """选中报告二读失败 (race 形态) → early_report_unreadable, 不假装。"""
        import unittest.mock as mock
        good = TestCrossWindowValidation._early_payload()
        early_dir = self._early_dir_with(tmp_path, {
            "winrate_payoff_decomposition_20260901.json": good,
        })
        em, mm = self._manifests(tmp_path)
        payload = TestCrossWindowValidation()._current_payload()
        import scripts.winrate_payoff_decomposition as mod
        real_read = Path.read_bytes

        def flaky_read(self):
            if self.name == "winrate_payoff_decomposition_20260901.json" \
                    and self.parent.name == "early_window":
                raise OSError("race: file vanished")
            return real_read(self)

        with mock.patch.object(Path, "read_bytes", flaky_read):
            self._attach(payload, early_dir, em, mm)
        assert payload["cross_window_validation"] == {
            "available": False,
            "reason": "early_report_unreadable",
        }

    def test_malformed_pin_treated_as_unpinned(self, tmp_path):
        """非法 pin 形态 (非 str/空) → 视为未绑定 (fail-open 同 rows 缺键),
        对比照常, 不因 owner 手误砖死对比面。"""
        good = TestCrossWindowValidation._early_payload()
        early_dir = self._early_dir_with(tmp_path, {
            "winrate_payoff_decomposition_20260901.json": good,
        })
        em, mm = self._manifests(
            tmp_path,
            early_pinned={"winrate_payoff_decomposition_20260901.json": 12345},
        )
        payload = TestCrossWindowValidation()._current_payload()
        self._attach(payload, early_dir, em, mm)
        cw = payload["cross_window_validation"]
        assert cw["available"] is True
        assert cw["pinned_digest_match"] is None

    def test_render_identity_line(self, tmp_path):
        """MD 身份行: digest 前 12 hex + pin 状态 (匹配/未绑定两形态)。"""
        from scripts.winrate_payoff_decomposition import render_md
        good = TestCrossWindowValidation._early_payload()
        early_dir = self._early_dir_with(tmp_path, {
            "winrate_payoff_decomposition_20260901.json": good,
        })
        real_digest = self._digest(early_dir / "winrate_payoff_decomposition_20260901.json")
        em, mm = self._manifests(
            tmp_path,
            early_pinned={"winrate_payoff_decomposition_20260901.json": real_digest},
        )
        payload = TestCrossWindowValidation()._current_payload()
        self._attach(payload, early_dir, em, mm)
        md = render_md(payload, "20260906")
        assert real_digest.removeprefix("sha256:")[:12] in md
        assert "已 pin·匹配" in md

        em2, mm2 = self._manifests(tmp_path)
        payload2 = TestCrossWindowValidation()._current_payload()
        self._attach(payload2, early_dir, em2, mm2)
        md2 = render_md(payload2, "20260906")
        assert "未 pin (行数绊线 only)" in md2


class TestCourtWindowFromEvents:
    """R141 Op3: 证据窗口随报告声明 — 数据内容真相 (signal_date min/max)。"""

    def _ev(self, dates):
        import pandas as pd
        return pd.DataFrame({"signal_date": dates})

    def test_min_max_string_dates(self):
        window = court_window_from_events(self._ev(["20250901", "20250701", "20260904"]))
        assert window == {"start": "20250701", "end": "20260904"}

    def test_empty_table_both_none(self):
        window = court_window_from_events(self._ev([]))
        assert window == {"start": None, "end": None}

    def test_nan_rows_ignored(self):
        import pandas as pd
        ev = self._ev(["20250701", math.nan, "20260904"])
        window = court_window_from_events(ev)
        assert window == {"start": "20250701", "end": "20260904"}


class TestRecordTriggerStatusTypedFailures:
    """R143 Op3: 兄弟落账函数同族硬化 — Op2 门挡池守卫施加于强度族。

    PoC 三连 (修复前 RED): W1 不可序列化 stat → TypeError 裸逃逸炸穿
    夜刷诊断; W2 NaN stat → json.dumps 静默写出 NaN 行毒化 K 判读数据;
    W3 ledger parent 为文件 → mkdir FileExistsError (exist_ok 对文件
    形态仍抛) 裸逃逸。
    """

    def _trigger(self, stat):
        return {
            "anchor": "production_aligned/t10",
            "min_n": 30,
            "condition_1_strong_bucket_ci_above_zero": {
                "lit": True, "judged": True, "n": 30, "stat": stat,
            },
            "condition_2_mid_bucket_expectancy_negative": {
                "lit": False, "judged": True, "n": 30, "stat": -0.001,
            },
            "conjunction_armed": False,
        }

    def test_unserializable_stat_typed_fail_open(self, tmp_path):
        ledger = tmp_path / "threshold_trigger_ledger.jsonl"
        meta = record_trigger_status(
            {"threshold_trigger": self._trigger(object())},
            "20260907",
            ledger_path=ledger,
        )
        assert meta == {
            "recorded": False, "reason": "snapshot_not_serializable"
        }
        assert not ledger.exists()

    def test_nan_stat_typed_fail_open(self, tmp_path):
        ledger = tmp_path / "threshold_trigger_ledger.jsonl"
        meta = record_trigger_status(
            {"threshold_trigger": self._trigger(float("nan"))},
            "20260907",
            ledger_path=ledger,
        )
        assert meta == {
            "recorded": False, "reason": "snapshot_not_serializable"
        }
        assert not ledger.exists()

    def test_file_parent_write_failed_not_raise(self, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_text("file", encoding="utf-8")
        meta = record_trigger_status(
            {"threshold_trigger": self._trigger(0.001)},
            "20260907",
            ledger_path=blocker / "threshold_trigger_ledger.jsonl",
        )
        assert meta == {"recorded": False, "reason": "write_failed"}
        assert blocker.read_text(encoding="utf-8") == "file"


class TestRegimeCompositionCheck:
    """R144 Op1: 跨窗 regime 构成核查 — 数字钉死 + fail-open 家族 + 渲染字节稳定。

    动机: R136 跨窗 caveat 把『regime 构成不同』列为 ≥0.70 桶跨窗符号反转的
    可能解释 — 该 hand-wave 在 production_aligned 锚口径下机械可检验。
    """

    COLS = [
        "regime", "gate_blocked", "fillable", "price_ge_3",
        "degraded", "st_name", "industry_missing", "excluded_ticker",
        "gross_ret_t10",
    ]

    @staticmethod
    def _row(regime, *, blocked=False, fillable=True, ret=0.05):
        return {
            "regime": regime, "gate_blocked": blocked, "fillable": fillable,
            "price_ge_3": True, "degraded": False, "st_name": False,
            "industry_missing": False, "excluded_ticker": False,
            "gross_ret_t10": ret,
        }

    def _write_csv(self, path, rows):
        import pandas as pd

        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows, columns=self.COLS).to_csv(path, index=False)
        return path

    def _early_rows(self):
        # 2 normal (gate 放行) + 2 crisis (全拦) + 1 risk_off (全拦)
        return [
            self._row("normal"), self._row("normal"),
            self._row("crisis", blocked=True), self._row("crisis", blocked=True),
            self._row("risk_off", blocked=True),
        ]

    def test_counts_pinned_and_gate_mechanism(self, tmp_path):
        """A1: 构成计数 + gate 拦截机制数字钉死; 双对齐宇宙纯 normal 判定。"""
        from scripts.winrate_payoff_decomposition import regime_composition_check

        early = self._write_csv(tmp_path / "early" / "t.csv", self._early_rows())
        current = self._write_csv(
            tmp_path / "current" / "t.csv",
            [self._row("normal"), self._row("normal"), self._row("normal")],
        )
        out = regime_composition_check(early, current)
        assert out["available"] is True
        assert out["early"]["aligned_counts"] == {"normal": 2}
        assert out["early"]["aligned_total"] == 2
        assert out["early"]["gate_blocked_by_regime"] == {
            "normal": {"blocked": 0, "total": 2},
            "crisis": {"blocked": 2, "total": 2},
            "risk_off": {"blocked": 1, "total": 1},
        }
        assert out["current"]["aligned_counts"] == {"normal": 3}
        assert out["current"]["aligned_total"] == 3
        assert out["both_aligned_pure_normal"] is True

    def test_mixed_aligned_universe_not_pure_normal(self, tmp_path):
        """对齐宇宙出现非 normal 行 (gate 放行的 crisis) → 纯 normal 判定 False。"""
        from scripts.winrate_payoff_decomposition import regime_composition_check

        early = self._write_csv(tmp_path / "early" / "t.csv", self._early_rows())
        current = self._write_csv(
            tmp_path / "current" / "t.csv",
            [self._row("normal"), self._row("crisis")],  # crisis 未被拦
        )
        out = regime_composition_check(early, current)
        assert out["available"] is True
        assert out["current"]["aligned_counts"] == {"normal": 1, "crisis": 1}
        assert out["both_aligned_pure_normal"] is False

    def test_missing_table_typed_unavailable(self, tmp_path):
        from scripts.winrate_payoff_decomposition import regime_composition_check

        current = self._write_csv(tmp_path / "c" / "t.csv", [self._row("normal")])
        out = regime_composition_check(tmp_path / "absent" / "t.csv", current)
        assert out == {"available": False, "reason": "early_table_unavailable"}

    def test_missing_columns_typed(self, tmp_path):
        import pandas as pd

        from scripts.winrate_payoff_decomposition import regime_composition_check

        path = tmp_path / "early" / "t.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([{"fillable": True, "gate_blocked": False}]).to_csv(
            path, index=False
        )
        current = self._write_csv(tmp_path / "c" / "t.csv", [self._row("normal")])
        out = regime_composition_check(path, current)
        assert out["available"] is False
        assert out["reason"] == "early_table_missing_columns"
        assert "regime" in out["missing_columns"]

    def test_attach_carries_composition_and_precise_caveat(self, tmp_path):
        """接线: 成功路径挂 regime_composition 键; 纯 normal → caveat 三精确化。"""
        from scripts.winrate_payoff_decomposition import (
            CROSS_WINDOW_CAVEATS,
            attach_cross_window_validation,
        )

        payload = TestCrossWindowValidation()._current_payload()
        early_dir = TestCrossWindowValidation._write_early_report(
            tmp_path, TestCrossWindowValidation._early_payload()
        )
        early_table = self._write_csv(
            tmp_path / "tables" / "early.csv", self._early_rows()
        )
        current_table = self._write_csv(
            tmp_path / "tables" / "current.csv", [self._row("normal")]
        )
        attach_cross_window_validation(
            payload,
            early_report_dir=early_dir,
            early_manifest_path=TestCrossWindowValidation._write_manifest(
                tmp_path / "em" / "m.json",
                window={"start": "20220104", "end": "20241231", "sessions": 726},
            ),
            main_manifest_path=TestCrossWindowValidation._write_manifest(
                tmp_path / "mm" / "m.json"
            ),
            early_court_table=early_table,
            current_court_table=current_table,
        )
        cw = payload["cross_window_validation"]
        assert cw["regime_composition"]["available"] is True
        assert cw["regime_composition"]["both_aligned_pure_normal"] is True
        assert len(cw["caveats"]) == 3
        assert cw["caveats"][:2] == list(CROSS_WINDOW_CAVEATS)[:2]
        assert "核查排除" in cw["caveats"][2]
        assert cw["caveats"][2] != list(CROSS_WINDOW_CAVEATS)[2]

    def test_attach_unavailable_composition_keeps_legacy_caveat(self, tmp_path):
        """fail-open: 构成表缺席 → 无 regime_composition 数字, caveat 三原样。"""
        from scripts.winrate_payoff_decomposition import (
            CROSS_WINDOW_CAVEATS,
            attach_cross_window_validation,
        )

        payload = TestCrossWindowValidation()._current_payload()
        early_dir = TestCrossWindowValidation._write_early_report(
            tmp_path, TestCrossWindowValidation._early_payload()
        )
        attach_cross_window_validation(
            payload,
            early_report_dir=early_dir,
            early_manifest_path=TestCrossWindowValidation._write_manifest(
                tmp_path / "em" / "m.json",
                window={"start": "20220104", "end": "20241231", "sessions": 726},
            ),
            main_manifest_path=TestCrossWindowValidation._write_manifest(
                tmp_path / "mm" / "m.json"
            ),
            early_court_table=tmp_path / "absent.csv",
            current_court_table=tmp_path / "absent2.csv",
        )
        cw = payload["cross_window_validation"]
        assert cw["regime_composition"]["available"] is False
        assert cw["regime_composition"]["reason"] == "early_table_unavailable"
        assert cw["caveats"] == list(CROSS_WINDOW_CAVEATS)

    def test_render_composition_lines_and_legacy_byte_stability(self, tmp_path):
        """渲染: 构成行 + 拦截机制行; 旧 payload (缺键) 零新增字节。"""
        from scripts.winrate_payoff_decomposition import (
            CROSS_WINDOW_CAVEATS,
            attach_cross_window_validation,
            render_md,
        )

        payload = TestCrossWindowValidation()._current_payload()
        early_dir = TestCrossWindowValidation._write_early_report(
            tmp_path, TestCrossWindowValidation._early_payload()
        )
        early_table = self._write_csv(
            tmp_path / "tables" / "early.csv", self._early_rows()
        )
        current_table = self._write_csv(
            tmp_path / "tables" / "current.csv", [self._row("normal")]
        )
        attach_cross_window_validation(
            payload,
            early_report_dir=early_dir,
            early_manifest_path=TestCrossWindowValidation._write_manifest(
                tmp_path / "em" / "m.json",
                window={"start": "20220104", "end": "20241231", "sessions": 726},
            ),
            main_manifest_path=TestCrossWindowValidation._write_manifest(
                tmp_path / "mm" / "m.json"
            ),
            early_court_table=early_table,
            current_court_table=current_table,
        )
        md = render_md(payload, "20260906")
        assert "Regime 构成核查" in md
        assert "早期 n=2 (normal 2/crisis 0/risk_off 0)" in md
        assert "当前 n=1 (normal 1/crisis 0/risk_off 0)" in md
        assert "gate 拦截" in md and "crisis 2/2" in md and "risk_off 1/1" in md
        assert "核查排除" in md

        # 旧 payload 形态: 缺 regime_composition 键 + caveat 三原文 → 渲染零新增
        legacy = dict(payload)
        cw_legacy = dict(payload["cross_window_validation"])
        cw_legacy.pop("regime_composition")
        cw_legacy["caveats"] = list(CROSS_WINDOW_CAVEATS)
        legacy["cross_window_validation"] = cw_legacy
        md_legacy = render_md(legacy, "20260906")
        assert "Regime 构成核查" not in md_legacy
        assert "gate 拦截" not in md_legacy
        assert md_legacy.split("跨窗口外部验证")[0] == md.split("跨窗口外部验证")[0]


class TestRegimeCompositionAdversarialPins:
    """R144 Op2: Op1 构成核查面的对抗性审查边界钉死 (PoC 四连后的回归锁)。

    P1 空对齐宇宙 / P2 NaN regime / P3 畸形 caveats 三形态审查判读为行为正确
    (诚实披露不冒充) — 本类将其锁死防重构漂移; P4 (字符串化布尔 gate_blocked
    被 ==True 静默吞) 系 production_aligned 单一实现既有语义, 登记不修。
    """

    COLS = TestRegimeCompositionCheck.COLS
    _row = staticmethod(TestRegimeCompositionCheck.__dict__["_row"])
    _write_csv = TestRegimeCompositionCheck.__dict__["_write_csv"]

    def test_p1_empty_aligned_universe_not_claimed_pure_normal(self, tmp_path):
        """空对齐宇宙 (全部行被排除): total=0 → 不冒充纯 normal, 无异常。"""
        from scripts.winrate_payoff_decomposition import regime_composition_check

        early = self._write_csv(
            tmp_path / "e" / "t.csv",
            [dict(self._row("normal"), price_ge_3=False)],
        )
        current = self._write_csv(tmp_path / "c" / "t.csv", [self._row("normal")])
        out = regime_composition_check(early, current)
        assert out["available"] is True
        assert out["early"]["aligned_counts"] == {}
        assert out["early"]["aligned_total"] == 0
        assert out["both_aligned_pure_normal"] is False

    def test_p2_nan_regime_missing_bucket_honest(self, tmp_path):
        """NaN regime 行: 『missing』桶诚实入 gate 机制行, 不入 aligned 计数。"""
        from scripts.winrate_payoff_decomposition import regime_composition_check

        early = self._write_csv(
            tmp_path / "e" / "t.csv",
            [self._row("normal"), dict(self._row("crisis", blocked=True), regime=None)],
        )
        current = self._write_csv(tmp_path / "c" / "t.csv", [self._row("normal")])
        out = regime_composition_check(early, current)
        assert out["available"] is True
        assert out["early"]["aligned_counts"] == {"normal": 1}
        assert "missing" in out["early"]["gate_blocked_by_regime"]
        assert out["early"]["gate_blocked_by_regime"]["missing"] == {
            "blocked": 1, "total": 1,
        }
        assert out["both_aligned_pure_normal"] is True

    def test_p3_malformed_caveats_guard(self, tmp_path):
        """畸形 caveats 守卫: available=False / 非 dict / 异常长度 → 常量原样。"""
        from scripts.winrate_payoff_decomposition import (
            CROSS_WINDOW_CAVEATS,
            _composition_caveats,
        )

        assert _composition_caveats({"available": False}) == list(CROSS_WINDOW_CAVEATS)
        assert _composition_caveats(None) == list(CROSS_WINDOW_CAVEATS)
        assert _composition_caveats("junk") == list(CROSS_WINDOW_CAVEATS)
        # available=True 但 both_aligned_pure_normal 非 bool → 中性精确化分支
        out = _composition_caveats({"available": True, "both_aligned_pure_normal": None})
        assert len(out) == 3 and out[2] != CROSS_WINDOW_CAVEATS[2]

    def test_p4_render_tolerates_corrupt_composition_payload(self, tmp_path):
        """渲染对畸形 composition 载荷零异常, 逐字段 '—' 退化。"""
        from scripts.winrate_payoff_decomposition import render_md

        payload = TestCrossWindowValidation()._current_payload()
        payload["cross_window_validation"] = {
            "available": True,
            "early_window": {"start": "20220104", "end": "20241231"},
            "buckets": [],
            "caveats": ["x"],
            "regime_composition": {
                "available": True,
                "both_aligned_pure_normal": True,
                "early": None,
                "current": {"aligned_counts": "junk", "aligned_total": "x"},
                "gate_blocked_by_regime": "junk",
            },
        }
        md = render_md(payload, "20260908")
        assert "Regime 构成核查" in md
        assert "早期 n=—" in md
        assert "当前 n=—" in md


class TestLedgerDateShapeGuard:
    """R144 Op3: 三族账本写入器 date_str 输入形状守卫 (登记项② 收口)。

    非 8 位 date_str 此前经 str() 强转静默入账成为账本行键, 污染同日
    替换幂等键与跨夜对齐语义。守卫先于 payload 守卫 (输入形状优先于
    内容语义), 非法 → invalid_date_str 零写入 (家族失败契约延伸)。
    """

    BAD_DATES = ["", "2026090", "202609081", "20260908T00", "2026-9-8", None, 20260908]

    def test_trigger_writer_rejects_malformed_dates_zero_write(self, tmp_path):
        from scripts.winrate_payoff_decomposition import record_trigger_status

        ledger = tmp_path / "threshold_trigger_ledger.jsonl"
        payload = {"threshold_trigger": TestRecordTriggerStatusTypedFailures()._trigger(0.001)}
        for bad in self.BAD_DATES:
            meta = record_trigger_status(payload, bad, ledger_path=ledger)
            assert meta == {"recorded": False, "reason": "invalid_date_str"}, bad
        assert not ledger.exists()

    def test_guard_precedes_payload_guard(self, tmp_path):
        """空 payload + 非法 date → invalid_date_str (非 no_threshold_trigger)。"""
        from scripts.winrate_payoff_decomposition import record_trigger_status

        meta = record_trigger_status({}, "2026-9-8", ledger_path=tmp_path / "l.jsonl")
        assert meta == {"recorded": False, "reason": "invalid_date_str"}


class TestTrailingWindow:
    """R149 Op1: 近期窗 (尾 N 信号日) 条件化判读面。

    Observe 实证 (真实 court 生产对齐 n=1627): 全窗 E≈0 完全由旧窗拖累,
    尾 20 信号日为全样本最强窗且强度梯度单调陡峭 — 全窗口径 (先验漂移
    行) 在新旧窗符号相反时方向性误导。fixture 非对称 (R13 教训)。
    净收益 = gross − 0.0065, fixture gross 反向加回, 断言直用净额。
    """

    def _frame(self, n_days: int = 5, flip: bool = False):
        import pandas as pd

        # 尾 3 日 (days_n=3 近期窗), 前 2 日应被切掉 (旧窗毒化行)
        # 尾窗逐日 E 非对称: 0311: −0.06 (0.30) / 0312: +0.04 (0.55),
        # 0313: +0.10 (0.90), +0.02 (0.75) → 桶梯度 <0.50 → 0.50-0.60 → ≥0.70 递增
        # flip=True 时尾窗改递减 (梯度布尔反向面)
        seq = [
            ("20260309", 0.90, -0.50),   # 旧窗 (应被切掉)
            ("20260310", 0.30, -0.60),   # 旧窗
            ("20260311", 0.30, -0.06),   # 尾窗 <0.50
            ("20260312", 0.55, 0.04),    # 尾窗 0.50-0.60
            ("20260313", 0.90, 0.10),    # 尾窗 ≥0.70
            ("20260313", 0.75, 0.02),    # 尾窗 ≥0.70 (第二行, 0.60-0.70 桶空)
        ]
        if flip:
            seq = [
                ("20260309", 0.90, -0.50),
                ("20260310", 0.30, -0.60),
                ("20260311", 0.30, 0.06),
                ("20260312", 0.55, -0.04),
                ("20260313", 0.90, -0.10),
                ("20260313", 0.75, -0.02),
            ]
        rows = [
            {"signal_date": sd, "trigger_strength": s, "gross_ret_t10": r + 0.0065}
            for sd, s, r in seq[:n_days + 1]
        ]
        return pd.DataFrame(rows).astype({"signal_date": str})

    def _tw(self, frame, **kw):
        from scripts.winrate_payoff_decomposition import trailing_window

        work = frame.copy()
        work["net_ret_t10"] = net_returns(work["gross_ret_t10"].tolist())
        from scripts.winrate_payoff_decomposition import strength_bucket

        work["strength_bucket"] = work["trigger_strength"].map(strength_bucket)
        return trailing_window(work, **kw)

    def test_tail_day_selection_exact(self):
        tw = self._tw(self._frame(), days_n=3)
        assert tw["available"] is True
        assert tw["observed_days"] == 3
        assert tw["first_day"] == "20260311"
        assert tw["last_day"] == "20260313"
        # 旧窗两行 (−0.50/−0.60) 被切掉: pooled n = 尾窗 4 行
        assert tw["pooled"]["n"] == 4
        # 逐位手算: (−0.06 + 0.04 + 0.10 + 0.02) / 4 = +0.025
        assert tw["pooled"]["expectancy"] == pytest.approx(0.025, abs=1e-12)
        # 胜率 3/4
        assert tw["pooled"]["winrate"] == pytest.approx(0.75, abs=1e-12)
        # 全窗对照: 全体 6 行 (−0.50−0.60−0.06+0.04+0.10+0.02)/6 = −0.166...
        assert tw["full_window_expectancy"] == pytest.approx(-1.0 / 6, abs=1e-12)
        # delta = 0.025 − (−1/6) = 0.191666...
        assert tw["delta_vs_full"] == pytest.approx(0.025 + 1.0 / 6, abs=1e-12)

    def test_strength_bucket_gradient_and_subthreshold_pool(self):
        tw = self._tw(self._frame(), days_n=3)
        buckets = {b["bucket"]: b for b in tw["strength_buckets"]}
        # '<0.50' 桶 = 0.50 门槛外毒池读数 (n=1, E=−0.06)
        assert buckets["<0.50"]["n"] == 1
        assert buckets["<0.50"]["expectancy"] == pytest.approx(-0.06, abs=1e-12)
        # '0.60-0.70' 桶空 (fixture 无该桶行) → n=0, 期望 None
        assert buckets["0.60-0.70"]["n"] == 0
        assert buckets["0.60-0.70"]["expectancy"] is None
        # 空桶不虚构反证: 观测桶非降 (<0.50 −0.06 ≤ 0.50-0.60 +0.04 ≤ ≥0.70 +0.10) → True
        assert tw["gradient_monotone_up"] is True

    def test_gradient_none_when_single_observed_bucket(self):
        # 观测数值桶 <2 → None (单点不冒充梯度)
        import pandas as pd

        from scripts.winrate_payoff_decomposition import (
            net_returns as nr,
            strength_bucket,
            trailing_window,
        )

        rows = [
            {"signal_date": "20260311", "trigger_strength": 0.30,
             "gross_ret_t10": -0.06 + 0.0065},
            {"signal_date": "20260312", "trigger_strength": None,
             "gross_ret_t10": 0.01 + 0.0065},
        ]
        w = pd.DataFrame(rows).astype({"signal_date": str})
        w["net_ret_t10"] = nr(w["gross_ret_t10"].tolist())
        w["strength_bucket"] = w["trigger_strength"].map(strength_bucket)
        tw = trailing_window(w, days_n=3)
        # 有序数值桶仅 <0.50 有行 (unknown 无序不入梯度) → None
        assert tw["gradient_monotone_up"] is None

    def test_gradient_monotone_true_and_false(self):
        # 全桶非空输入: 递增 → True
        import pandas as pd
        from scripts.winrate_payoff_decomposition import (
            net_returns as nr,
            strength_bucket,
            trailing_window,
        )

        def mk(pairs):
            rows = [
                {"signal_date": sd, "trigger_strength": s, "gross_ret_t10": r + 0.0065}
                for sd, s, r in pairs
            ]
            w = pd.DataFrame(rows).astype({"signal_date": str})
            w["net_ret_t10"] = nr(w["gross_ret_t10"].tolist())
            w["strength_bucket"] = w["trigger_strength"].map(strength_bucket)
            return w

        up = mk([
            ("20260311", 0.30, -0.06),
            ("20260312", 0.55, 0.04),
            ("20260312", 0.65, 0.05),
            ("20260313", 0.90, 0.10),
        ])
        tw_up = trailing_window(up, days_n=3)
        assert tw_up["gradient_monotone_up"] is True
        down = mk([
            ("20260311", 0.30, 0.06),
            ("20260312", 0.55, -0.04),
            ("20260312", 0.65, -0.05),
            ("20260313", 0.90, -0.10),
        ])
        tw_down = trailing_window(down, days_n=3)
        assert tw_down["gradient_monotone_up"] is False

    def test_split_half_sign_consistency_and_honest_none(self):
        tw = self._tw(self._frame(), days_n=3)
        halves = tw["split_half"]
        # 尾 3 日对分: early {0311} (E −0.06), late {0312,0313} (E +0.0533...)
        assert halves["early"]["expectancy"] == pytest.approx(-0.06, abs=1e-12)
        assert halves["late"]["expectancy"] == pytest.approx(0.08 / 1.5, abs=1e-12)
        assert halves["sign_consistent"] is False
        # 半窗无成熟行 → sign_consistent None (单日窗 early 空)
        tw1 = self._tw(self._frame(), days_n=1)
        assert tw1["split_half"]["early"]["n"] == 0
        assert tw1["split_half"]["early"]["expectancy"] is None
        assert tw1["split_half"]["sign_consistent"] is None

    def test_determinism_same_input_same_output(self):
        # CI per-call seeded (R13): 同输入两次调用整块逐位恒等
        a = self._tw(self._frame(), days_n=3)
        b = self._tw(self._frame(), days_n=3)
        assert a == b

    def test_no_mature_rows_available_false(self):
        import pandas as pd
        from scripts.winrate_payoff_decomposition import (
            net_returns as nr,
            strength_bucket,
            trailing_window,
        )

        empty = pd.DataFrame({
            "signal_date": ["20260311"],
            "trigger_strength": [0.9],
            "gross_ret_t10": [float("nan")],
        }).astype({"signal_date": str})
        empty["net_ret_t10"] = nr(empty["gross_ret_t10"].tolist())
        empty["strength_bucket"] = empty["trigger_strength"].map(strength_bucket)
        tw = trailing_window(empty, days_n=3)
        assert tw == {"available": False, "reason": "no_mature_rows"}

    def test_decompose_wiring_universe_discipline(self, tmp_path, monkeypatch):
        # A4 口径 pin: production_aligned 有 trailing_window, all_candidates 无
        import pandas as pd

        from scripts.winrate_payoff_decomposition import decompose

        rows = [
            {"signal_date": "20260311", "trigger_strength": 0.30,
             "gross_ret_t10": -0.06 + 0.0065, "gross_ret_t5": 0.0,
             "regime": "normal",
             "gate_blocked": False, "fillable": True, "price_ge_3": True},
            {"signal_date": "20260312", "trigger_strength": 0.90,
             "gross_ret_t10": 0.10 + 0.0065, "gross_ret_t5": 0.0,
             "regime": "normal",
             "gate_blocked": False, "fillable": True, "price_ge_3": True},
        ]
        df = pd.DataFrame(rows).astype({"signal_date": str})
        for col in ("degraded", "st_name", "industry_missing", "excluded_ticker"):
            df[col] = False
        payload = decompose(df)
        assert "trailing_window" in payload["universes"]["production_aligned"]
        assert "trailing_window" not in payload["universes"]["all_candidates"]
        assert (
            payload["universes"]["production_aligned"]["trailing_window"][
                "available"
            ]
            is True
        )

    def test_days_n_below_one_invalid_shape(self):
        # R149 Op2 F-c RED (修复前: days_n=0 经 all_days[-0:] 返回全窗)
        from scripts.winrate_payoff_decomposition import trailing_window

        w = self._tw(self._frame(), days_n=3)
        assert w["available"] is True  # 基线: 正常尾窗
        for bad in (0, -1):
            tw = self._tw(self._frame(), days_n=bad)
            assert tw == {"available": False, "reason": "invalid_days_n"}

    def _neg_delta_trailing_md(self):
        # R149 Op2 F-a/F-b 渲染输入: 尾窗差 (旧窗 +0.50 拉高全窗) → delta<0
        import pandas as pd

        from scripts.winrate_payoff_decomposition import (
            net_returns as nr,
            render_md,
            strength_bucket,
            trailing_window,
        )

        rows = [
            {"signal_date": sd, "trigger_strength": s,
             "gross_ret_t10": r + 0.0065}
            for sd, s, r in [
                ("20260311", 0.90, 0.50),
                ("20260312", 0.30, -0.06),
                ("20260313", 0.55, -0.04),
            ]
        ]
        w = pd.DataFrame(rows).astype({"signal_date": str})
        w["net_ret_t10"] = nr(w["gross_ret_t10"].tolist())
        w["strength_bucket"] = w["trigger_strength"].map(strength_bucket)
        tw_neg = trailing_window(w, days_n=2)
        assert tw_neg["delta_vs_full"] < 0
        payload = {
            "horizons": {},
            "universes": {
                "all_candidates": {"horizons": {}},
                "production_aligned": {"horizons": {}, "trailing_window": tw_neg},
            },
        }
        return render_md(payload, "20260908")

    def test_render_negative_delta_direction_neutral(self):
        # R149 Op2 F-a RED (修复前: delta<0 仍渲染『全窗聚合由旧窗主导』
        # 方向性虚假叙事): 负 delta 只描述差值, 方向描述与正 delta 对称。
        md = self._neg_delta_trailing_md()
        assert "由旧窗主导" not in md
        assert "近期更弱" in md  # 负 delta 方向描述对称

    def test_render_multi_view_conjunction_pin(self):
        # R149 Op2 F-b RED (修复前:『近期判读以本节为准』过度声称单一池化
        # 读数 — 真实形态半窗符号翻转 + CI 跨零): 改为多视图合取措辞。
        md = self._neg_delta_trailing_md()
        assert "多视图" in md
        assert "单一读数不冒充结论" in md
        assert "以本节为准" not in md

    def test_render_trailing_section_and_fail_open(self):
        from scripts.winrate_payoff_decomposition import (
            render_md,
            trailing_window,
        )

        base_payload = {
            "horizons": {},
            "universes": {
                "all_candidates": {"horizons": {}},
                "production_aligned": {"horizons": {}},
            },
        }
        # 缺键 → 零新增字节 (fail-open)
        md_without = render_md(dict(base_payload), "20260908")
        assert "近期窗判读" not in md_without
        # 有键 → 四要素齐 (池化/梯度/半窗/机制注)
        work = self._frame()
        tw = self._tw(work, days_n=3)
        payload = {
            "horizons": {},
            "universes": {
                "all_candidates": {"horizons": {}},
                "production_aligned": {
                    "horizons": {},
                    "trailing_window": tw,
                },
            },
        }
        md = render_md(payload, "20260908")
        assert "### 近期窗判读 (尾 N 信号日, R149)" in md
        assert "**池化**" in md and "20260311..20260313" in md
        assert "**强度梯度**" in md and "门槛外毒池" in md
        assert "**半窗**" in md and "符号一致: 否" in md
        assert "机制注" in md and "宪法 #2" in md
        # available=False → 零新增字节 (不冒充)
        payload_off = {
            "horizons": {},
            "universes": {
                "all_candidates": {"horizons": {}},
                "production_aligned": {
                    "horizons": {},
                    "trailing_window": {"available": False},
                },
            },
        }
        assert "近期窗判读" not in render_md(payload_off, "20260908")


class TestClusterBootDeltaCi:
    """R153 Op1: hi−lo 期望差的按日配对聚类 bootstrap 区间 — 纯函数面。"""

    def _two_cell_fixture(self, *, n_days=40, per_day=2):
        """非对称双桶: hi 桶全正收益 / lo 桶全负收益, 逐行互异, 各自跨多日。"""
        hi_rets, hi_days, lo_rets, lo_days = [], [], [], []
        for d in range(n_days):
            day = f"2026-02-{(d % 28) + 1:02d}-{d:03d}"
            for j in range(per_day):
                hi_rets.append(0.08 + 0.001 * (d + j))
                hi_days.append(day)
                lo_rets.append(-0.07 - 0.001 * (d + j))
                lo_days.append(day)
        return hi_rets, hi_days, lo_rets, lo_days

    def test_deterministic_byte_identical(self):
        from scripts.winrate_payoff_decomposition import cluster_boot_delta_ci

        hi_rets, hi_days, lo_rets, lo_days = self._two_cell_fixture()
        a = cluster_boot_delta_ci(
            hi_rets, hi_days, lo_rets, lo_days, n_boot=200
        )
        b = cluster_boot_delta_ci(
            hi_rets, hi_days, lo_rets, lo_days, n_boot=200
        )
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def test_separated_cells_interval_excludes_zero(self):
        """hi 全正 / lo 全负 → delta≈+15pp, 双侧区间整体在零右侧。"""
        from scripts.winrate_payoff_decomposition import cluster_boot_delta_ci

        hi_rets, hi_days, lo_rets, lo_days = self._two_cell_fixture()
        ci = cluster_boot_delta_ci(hi_rets, hi_days, lo_rets, lo_days, n_boot=400)
        assert set(ci) == {"ci_low", "ci_high"}
        assert ci["ci_low"] > 0.10
        assert ci["ci_low"] <= ci["ci_high"]

    def test_empty_cell_value_error(self):
        from scripts.winrate_payoff_decomposition import cluster_boot_delta_ci

        with pytest.raises(ValueError, match="empty_cell"):
            cluster_boot_delta_ci([], [], [-0.01], ["2026-02-01"], n_boot=50)
        with pytest.raises(ValueError, match="empty_cell"):
            cluster_boot_delta_ci([0.01], ["2026-02-01"], [], [], n_boot=50)

    def test_disjoint_days_still_resolves_via_rejection(self):
        """两桶日集完全不相交: 拒绝采样仍收敛, 结果确定且区间有限。"""
        import math

        from scripts.winrate_payoff_decomposition import cluster_boot_delta_ci

        ci = cluster_boot_delta_ci(
            [0.05, 0.06, 0.07],
            ["2026-02-01", "2026-02-02", "2026-02-03"],
            [-0.04, -0.05],
            ["2026-03-01", "2026-03-02"],
            n_boot=300,
        )
        assert math.isfinite(ci["ci_low"]) and math.isfinite(ci["ci_high"])
        assert ci["ci_low"] <= ci["ci_high"]

    def test_length_mismatch_typed_rejection(self):
        """rets/days 长度不齐 → ValueError (换位传参陷阱的 typed 封口)。"""
        from scripts.winrate_payoff_decomposition import cluster_boot_delta_ci

        with pytest.raises(ValueError, match="delta_ci_length_mismatch"):
            cluster_boot_delta_ci(
                [0.05, 0.06],                       # 2 rets
                ["2026-02-01", "2026-02-02", "2026-02-03"],  # 3 days — 不齐
                [-0.04, -0.05],
                ["2026-03-01", "2026-03-02"],
                n_boot=50,
            )
        with pytest.raises(ValueError, match="delta_ci_length_mismatch"):
            cluster_boot_delta_ci(
                [0.05, 0.06],
                ["2026-02-01", "2026-02-02"],
                [-0.04],
                ["2026-03-01", "2026-03-02"],       # lo 侧不齐
                n_boot=50,
            )


# ---------- R186 Op1: court_binding data_window (『覆盖至』写面数据真相) ----------

class TestCourtBindingDataWindowR186:
    """R186 Op1: court_binding 增 data_window (signal_date min/max) —
    R141 Op3『同屏矛盾』陷阱 (请求窗领先 signal_date max 数日, 同屏
    『覆盖至』两说) 的写面收口; 请求态 window 保留供窗口审计 (R130 双轨)."""

    def _table(self, tmp_path, dates):
        import pandas as pd
        table = tmp_path / "court.csv.gz"
        pd.DataFrame({"signal_date": dates, "x": range(len(dates))}).to_csv(
            table, index=False, compression="gzip")
        return table

    def test_data_window_equals_signal_date_minmax(self, tmp_path):
        from scripts.winrate_payoff_decomposition import court_binding
        table = self._table(tmp_path, ["20250702", "20250702", "20260827", "20260909"])
        b = court_binding(table, rows=4)
        assert b["data_window"] == {"start": "20250702", "end": "20260909"}

    def test_data_window_unreadable_table_degrades_none(self, tmp_path):
        from scripts.winrate_payoff_decomposition import court_binding
        table = tmp_path / "court.csv.gz"
        table.write_bytes(b"x")
        b = court_binding(table, rows=1)
        assert b["data_window"] == {"start": None, "end": None}
        assert b["content_digest"] is None

    def test_data_window_missing_column_degrades_none(self, tmp_path):
        """signal_date 列缺失 (最小列 fixture / schema drift) → None 不冒充."""
        import pandas as pd
        from scripts.winrate_payoff_decomposition import court_binding
        table = tmp_path / "court.csv.gz"
        pd.DataFrame({"a": [1, 2]}).to_csv(table, index=False, compression="gzip")
        b = court_binding(table, rows=2)
        assert b["data_window"] == {"start": None, "end": None}

    def test_data_window_non_date8_shapes_rejected(self, tmp_path):
        """ISO 短横/浮点形态 → 8 位数字串守卫拒绝, None 不带毒上穿."""
        from scripts.winrate_payoff_decomposition import court_binding
        table = self._table(tmp_path, ["2026-01-02", "20260909.0"])
        b = court_binding(table, rows=2)
        assert b["data_window"] == {"start": None, "end": None}

    def test_data_window_not_part_of_data_state_identity(self):
        """前进门身份只认 content_digest (R130 Op1) — data_window/请求窗
        差异不构成数据前进, 折叠语义零变化 (A2 钉子)."""
        from scripts.winrate_payoff_decomposition import court_data_state_equal
        base = {"content_digest": "sha256:" + "ab" * 32}
        left = {**base, "window_end": "20260911",
                "data_window": {"start": "20250702", "end": "20260909"}}
        right = {**base, "window_end": "20260912",
                 "data_window": {"start": None, "end": None}}
        assert court_data_state_equal(left, right) is True
