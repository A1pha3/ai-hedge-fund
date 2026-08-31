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
    THRESHOLD_TRIGGER_MIN_N,
    attribution,
    attach_threshold_trigger,
    net_returns,
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


class TestDeterministicAcrossCalls:
    """R13 对抗审查 PoC: RNG 全局状态曾使同进程第二次调用 CI 漂移。"""

    def test_repeated_calls_identical_ci(self):
        import numpy as np
        from scripts.winrate_payoff_decomposition import cluster_boot_ci_low
        rng_data = np.random.default_rng(42)
        days = [f"d{i%10}" for i in range(60)]
        rets = list(rng_data.normal(0.001, 0.02, 60))
        ci1 = cluster_boot_ci_low(rets, days)
        ci2 = cluster_boot_ci_low(rets, days)
        ci3 = cluster_boot_ci_low(rets, days)
        assert ci1 == ci2 == ci3  # 与进程内调用历史无关

    def test_decompose_repeated_byte_identical(self):
        from scripts.winrate_payoff_decomposition import decompose
        import numpy as np, pandas as pd
        rng = np.random.default_rng(7)
        ev = pd.DataFrame({
            "symbol": [f"s{i}" for i in range(80)],
            "signal_date": [f"2026-01-{(i%15)+1:02d}" for i in range(80)],
            "regime": ["normal" if i%4 else "crisis" for i in range(80)],
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
            "signal_date": [f"2026-01-{(i%15)+1:02d}" for i in range(80)],
            "regime": ["normal"] * 80,
            "trigger_strength": list(rng.uniform(0.45, 0.95, 80)),
            "gross_ret_t10": list(rng.normal(0.005, 0.1, 80)),
            "gross_ret_t5": list(rng.normal(0.002, 0.05, 80)),
        })
        clean = decompose(ev, universes=("all_candidates",))
        # 预消耗模块 RNG (若实现仍依赖全局态, 此后结果会漂移)
        junk_days = [f"j{i%5}" for i in range(50)]
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
