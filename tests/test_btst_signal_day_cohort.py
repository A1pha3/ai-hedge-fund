"""btst_signal_day_cohort — 信号日 cohort 分解纯函数 (第一百二十三轮 Op1).

钉死的正确性面:
- 方差分解恒等式: between + within == total (独立重算, 无残差);
- cohort 规模分桶边界恰落界 / 小样本 CI 纪律 (n<MIN_CELL_N → CI=None);
- split-half 判据: 可判桶 <2 证据不足 / 符号翻转指名桶 / 全合取具备资格;
- (net, day, strong) 逐位对齐 (NaN gross 跳过, 不按位置猜);
- 确定性: 同输入两次调用逐字节同输出 (per-call seeded 聚类 CI);
- fixture 全部非对称 (R13 教训: 对称 fixture 的数值断言无牙)。
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.btst_signal_day_cohort import (
    COHORT_BUCKET_LABELS,
    cohort_bucket_table,
    cohort_size_bucket,
    decompose_cohort,
    render_md,
    split_half_stability,
    strength_cohort_cross_table,
    strong_share_correlation,
    variance_decomposition,
    worst_days,
)
from src.screening.offensive.threshold_trigger import ALL_STRENGTH_BUCKETS
from scripts.winrate_payoff_decomposition import MIN_CELL_N


# ---------------------------------------------------------------------------
# fixture 工厂 (非对称: 逐日规模/收益/强度全部不同)
# ---------------------------------------------------------------------------

def _frame(rows: list[tuple[str, int, float, float]]) -> pd.DataFrame:
    """(ts_code, signal_date, gross_ret_t10, trigger_strength) → court 事件表."""
    return pd.DataFrame(
        {
            "ts_code": [r[0] + ".SZ" for r in rows],
            "signal_date": [r[1] for r in rows],
            "gross_ret_t10": [r[2] for r in rows],
            "trigger_strength": [r[3] for r in rows],
            "fillable": True,
            "gate_blocked": False,
            "price_ge_3": True,
            "degraded": False,
            "st_name": "",
            "industry_missing": False,
            "excluded_ticker": False,
        }
    )


def _aligned(rows: list[tuple[str, int, float, float]]):
    """fixture → (net, days, strong) — 经 decompose 同一条对齐路径."""
    from scripts.winrate_payoff_decomposition import net_returns
    from src.screening.offensive.threshold_trigger import strength_bucket

    pairs = [
        (v, str(d), strength_bucket(float(s)) == "≥0.70")
        for v, d, s in zip(
            net_returns([r[2] for r in rows]),
            [r[1] for r in rows],
            [r[3] for r in rows],
        )
        if v is not None
    ]
    return [p[0] for p in pairs], [p[1] for p in pairs], [p[2] for p in pairs]


class TestCohortSizeBucket:
    def test_edges_inclusive(self):
        assert cohort_size_bucket(1) == "1"
        assert cohort_size_bucket(2) == "2-3"
        assert cohort_size_bucket(3) == "2-3"
        assert cohort_size_bucket(4) == "4-9"
        assert cohort_size_bucket(9) == "4-9"
        assert cohort_size_bucket(10) == "10-19"
        assert cohort_size_bucket(19) == "10-19"
        assert cohort_size_bucket(20) == "20+"
        assert cohort_size_bucket(60) == "20+"

    def test_fail_closed_non_positive_and_non_int(self):
        with pytest.raises(ValueError):
            cohort_size_bucket(0)
        with pytest.raises(ValueError):
            cohort_size_bucket(-3)
        with pytest.raises(TypeError):
            cohort_size_bucket(True)  # bool 是 int 子类 — 显式拒
        with pytest.raises(TypeError):
            cohort_size_bucket(2.0)


class TestVarianceDecomposition:
    def test_identity_asymmetric_with_independent_oracle(self):
        days = ["20260701", "20260701", "20260702", "20260703", "20260703", "20260703"]
        net = [0.05, -0.03, 0.10, -0.02, 0.01, 0.04]
        out = variance_decomposition(net, days)
        # 独立 oracle: numpy 总体方差 + 手工 between
        arr = np.asarray(net)
        total = float(arr.var(ddof=0))
        grand = float(arr.mean())
        between = 0.0
        for d in ("20260701", "20260702", "20260703"):
            m = np.asarray([v for v, dd in zip(net, days) if dd == d])
            between += len(m) * (float(m.mean()) - grand) ** 2 / len(net)
        assert out["total"] == pytest.approx(total, abs=1e-15)
        assert out["between"] == pytest.approx(between, abs=1e-15)
        assert out["between"] + out["within"] == pytest.approx(out["total"], abs=1e-12)
        assert out["residual"] == pytest.approx(0.0, abs=1e-12)
        assert out["between_share"] == pytest.approx(out["between"] / out["total"])
        assert out["n_days"] == 3 and out["n_events"] == 6

    def test_single_day_share_zero_not_none(self):
        # 单日非零方差: between=0/total>0 → share 是真值 0.0 (None 只留给 total=0)
        out = variance_decomposition([0.01, -0.01], ["20260701", "20260701"])
        assert out["total"] == pytest.approx(0.0001)
        assert out["between_share"] == 0.0
        assert out["within_share"] == pytest.approx(1.0)

    def test_true_zero_total_shares_none(self):
        out = variance_decomposition([0.01, 0.01], ["20260701", "20260701"])
        assert out["total"] == 0.0
        assert out["between_share"] is None
        assert out["within_share"] is None

    def test_length_mismatch_fails(self):
        with pytest.raises(ValueError):
            variance_decomposition([0.1, 0.2], ["20260701"])


class TestCohortBuckets:
    def test_small_bucket_ci_none_large_bucket_ci_float(self):
        # 2-3 桶: 3 事件 (n<30) → CI=None; 20+ 桶: 2 日 ×16 事件 (n=32≥30,
        # 2 个信号日) → CI 产出 — 小样本纪律与聚类 CI 同表对照
        rows = [
            ("000001", 20260701, 0.02, 0.9),
            ("000002", 20260701, -0.01, 0.4),
            ("000003", 20260701, 0.03, 0.75),
            *[
                (f"1000{i:02d}", 20260710, 0.01 + i * 0.001, 0.8)
                for i in range(20)
            ],
            *[
                (f"2000{i:02d}", 20260711, -0.02 - i * 0.001, 0.3)
                for i in range(20)
            ],
        ]
        net, days, strong = _aligned(rows)
        buckets = cohort_bucket_table(net, days, strong)
        assert [b["bucket"] for b in buckets] == ["2-3", "20+"]
        by_label = {b["bucket"]: b for b in buckets}
        assert by_label["2-3"]["event_stats"]["cluster_ci_low_90"] is None
        assert by_label["2-3"]["event_stats"]["n"] == 3
        big = by_label["20+"]
        assert big["event_stats"]["n"] == 40
        assert isinstance(big["event_stats"]["cluster_ci_low_90"], float)
        # 日E中位非对称校验: 20260710 日均值 >0, 20260711 <0
        assert big["day_e_median"] is not None

    def test_bucket_ordering_follows_labels(self):
        rows = (
            [("000001", 20260701, 0.02, 0.9)]                       # 1
            + [("00000%d" % i, 20260702, 0.01, 0.5) for i in range(2, 4)]  # 2-3
            + [("00001%d" % i, 20260703, -0.01, 0.6) for i in range(4)]    # 4-9
        )
        net, days, strong = _aligned(rows)
        buckets = cohort_bucket_table(net, days, strong)
        assert [b["bucket"] for b in buckets] == ["1", "2-3", "4-9"]


class TestSplitHalf:
    def _rows_flip(self, sign_first: float, sign_second: float):
        # 可判桶 "20+": 前半 1 日 ×30 事件, 后半 1 日 ×30 事件 (各 ≥30)
        rows = [
            (f"1{i:03d}", 20260701, sign_first * (0.01 + i * 0.0001), 0.8)
            for i in range(30)
        ] + [
            (f"2{i:03d}", 20260801, sign_second * (0.01 + i * 0.0001), 0.8)
            for i in range(30)
        ]
        return rows

    def test_single_flipping_bucket_discloses_not_verdict(self):
        # 单可判桶: 行级 sign_consistent=False 如实披露, 但判定面证据不足
        # (R15 判据需排序面 — 判定权不让渡给单桶符号)
        rows = self._rows_flip(+1.0, -1.0)
        net, days, strong = _aligned(rows)
        buckets = cohort_bucket_table(net, days, strong)
        sh = split_half_stability(net, days, buckets)
        row = sh["per_bucket"][0]
        assert row["judged"] is True
        assert row["sign_consistent"] is False
        assert "证据不足" in sh["verdict"]

    def test_flip_with_second_stable_bucket_names_flipped(self):
        # 20+ 桶翻转 + 10-19 桶稳定 → 不具备资格且指名翻转桶
        rows = self._rows_flip(+1.0, -1.0)
        # 10-19 桶: 两半各 2 日 ×9 事件 (各 18 <30 → 不可判)…改 4 日 ≥30:
        # 前半 2 日 ×9=18, 后半 2 日 ×9=18 — 仍 <30。用 16×2=32? 16/日
        # 落 10-19 桶: 两半各 2 日 ×16=32 ≥30 可判
        for d, sign in ((20260702, +1.0), (20260703, +1.0)):
            rows += [
                (f"3{d}{i:02d}", d, sign * (0.005 + i * 0.0001), 0.8)
                for i in range(16)
            ]
        for d, sign in ((20260802, +1.0), (20260803, +1.0)):
            rows += [
                (f"4{d}{i:02d}", d, sign * (0.004 + i * 0.0001), 0.8)
                for i in range(16)
            ]
        net, days, strong = _aligned(rows)
        buckets = cohort_bucket_table(net, days, strong)
        by_label = {b["bucket"]: b for b in buckets}
        assert by_label["10-19"]["event_stats"]["n"] == 64
        sh = split_half_stability(net, days, buckets)
        assert sh["spearman"] is not None
        assert "不具备资格" in sh["verdict"]
        assert "20+" in sh["verdict"]

    def test_consistent_two_buckets_qualified(self):
        # 两可判桶符号跨半一致 + 桶序两半相同 → 具备资格
        rows: list[tuple[str, int, float, float]] = []
        # 20+ 桶: 两半各 1 日 ×30 事件, 两半皆正
        rows += [
            (f"1{i:03d}", 20260701, 0.01 + i * 0.0001, 0.8) for i in range(30)
        ]
        rows += [
            (f"2{i:03d}", 20260801, 0.02 + i * 0.0001, 0.8) for i in range(30)
        ]
        # 10-19 桶: 两半各 2 日 ×16 事件 (各 32 ≥30), 两半皆负
        for d, base in ((20260702, -0.01), (20260703, -0.005)):
            rows += [
                (f"3{d}{i:02d}", d, base - i * 0.0001, 0.8) for i in range(16)
            ]
        for d, base in ((20260802, -0.02), (20260803, -0.015)):
            rows += [
                (f"4{d}{i:02d}", d, base - i * 0.0001, 0.8) for i in range(16)
            ]
        net, days, strong = _aligned(rows)
        buckets = cohort_bucket_table(net, days, strong)
        sh = split_half_stability(net, days, buckets)
        assert sh["spearman"] is not None and sh["spearman"] >= 0.5
        assert "具备资格" in sh["verdict"]

    def test_single_judged_bucket_insufficient(self):
        rows = self._rows_flip(+1.0, +1.0)  # 只有 20+ 一个桶, 两半同号
        net, days, strong = _aligned(rows)
        buckets = cohort_bucket_table(net, days, strong)
        sh = split_half_stability(net, days, buckets)
        assert sh["spearman"] is None
        assert "证据不足" in sh["verdict"]
        assert "不足 2" in sh["verdict"]

    def test_undersized_half_disclosed_not_judged(self):
        # 后半仅 5 事件 (<30) → judged=False, sign 一致也不判定
        rows = [
            (f"1{i:03d}", 20260701, 0.01 + i * 0.0001, 0.8) for i in range(30)
        ] + [
            (f"2{i:03d}", 20260801, 0.02 + i * 0.0001, 0.8) for i in range(5)
        ]
        net, days, strong = _aligned(rows)
        buckets = cohort_bucket_table(net, days, strong)
        sh = split_half_stability(net, days, buckets)
        assert sh["per_bucket"][0]["judged"] is False
        assert sh["per_bucket"][0]["sign_consistent"] is None


class TestDecomposeCohort:
    def test_end_to_end_alignment_and_worst_day(self):
        # 非对称四日: 规模 1 / 3 / 4 / 20+; 最差日已知且唯一 (20260704)
        rows: list[tuple[str, int, float, float]] = [
            ("900001", 20260701, 0.08, 0.75),                    # 1 桶, strong
            ("900002", 20260702, 0.01, 0.40),                    # 1 桶, 非strong
            *[
                (f"90010{i}", 20260703, 0.02 + i * 0.001, 0.55)
                for i in range(3)
            ],                                                    # 2-3 桶
            *[
                (f"90020{i}", 20260705, -0.01 - i * 0.001, 0.62)
                for i in range(4)
            ],                                                    # 4-9 桶
            # 20+ 桶 ×2 日: 0704 全深负 (最差日), 0710 温和正
            *[
                (f"90030{i:02d}", 20260704, -0.05 - i * 0.001, 0.72)
                for i in range(20)
            ],
            *[
                (f"90040{i:02d}", 20260710, 0.005 + i * 0.0005, 0.30)
                for i in range(20)
            ],
        ]
        ev = _frame(rows)
        payload = decompose_cohort(ev)
        assert payload["n_events"] == len(rows)
        assert payload["n_days"] == 6
        var = payload["variance"]
        assert var["between"] + var["within"] == pytest.approx(var["total"], abs=1e-12)
        assert var["residual"] == pytest.approx(0.0, abs=1e-12)
        # NaN gross 行跳过且不错位: 追加一行 NaN gross 后 n 不变
        ev2 = _frame(rows + [("888888", 20260710, float("nan"), 0.9)])
        payload2 = decompose_cohort(ev2)
        assert payload2["n_events"] == len(rows)
        assert payload2["n_days"] == payload["n_days"]
        # worst 日是指定的 20260704 (非对称: 其它日不可能更差)
        worst = payload["worst_days"]
        assert worst[0]["signal_date"] == "20260704"
        assert worst[0]["day_e"] < worst[-1]["day_e"]
        assert worst[0]["strong_share"] == pytest.approx(1.0)
        # strong 逐位: 0.75 strong / 0.40 非 / 0.62 非 (0.60-0.70) / 0.72 strong
        assert payload["strong_share_corr"]["n_days"] == 6
        # 分桶覆盖 1 / 2-3 / 4-9 / 20+ (10-19 无事件 → 缺席)
        labels = [b["bucket"] for b in payload["cohort_buckets"]]
        assert labels == ["1", "2-3", "4-9", "20+"]

    def test_json_roundtrip_bytes(self):
        rows: list[tuple[str, int, float, float]] = [
            ("900001", 20260701, 0.08, 0.75),
            *[
                (f"90030{i:02d}", 20260704, -0.05 - i * 0.001, 0.72)
                for i in range(20)
            ],
            *[
                (f"90040{i:02d}", 20260710, 0.005 + i * 0.0005, 0.30)
                for i in range(20)
            ],
        ]
        ev = _frame(rows)
        p1 = json.dumps(decompose_cohort(ev), sort_keys=True)
        p2 = json.dumps(decompose_cohort(ev), sort_keys=True)
        assert p1 == p2  # per-call seeded CI — 同进程两次调用逐字节同输出

    def test_all_nan_gross_fails_closed(self):
        rows = [("900001", 20260701, float("nan"), 0.75)]
        with pytest.raises(SystemExit, match="净收益为空"):
            decompose_cohort(_frame(rows))

    def test_single_signal_day_fails_closed(self):
        rows = [
            (f"90030{i:02d}", 20260704, 0.01 + i * 0.001, 0.72)
            for i in range(5)
        ]
        with pytest.raises(SystemExit, match="单一信号日"):
            decompose_cohort(_frame(rows))


class TestRender:
    def _payload(self):
        rows: list[tuple[str, int, float, float]] = [
            ("900001", 20260701, 0.08, 0.75),
            *[
                (f"90030{i:02d}", 20260704, -0.05 - i * 0.001, 0.72)
                for i in range(20)
            ],
            *[
                (f"90040{i:02d}", 20260710, 0.005 + i * 0.0005, 0.30)
                for i in range(16)
            ],
        ]
        return decompose_cohort(_frame(rows))

    def test_md_sections_and_disclosure(self):
        md = render_md(self._payload(), "20260905")
        assert "纯诊断 (宪法 #2)" in md
        assert "恒等式无残差" in md
        # 20+ 桶 n=36≥30 CI 在表; 1 桶 n=1 → 披露尾注
        assert f"事件 n < {MIN_CELL_N}" in md
        assert "split-half" in md
        assert "worst-5" in md or "worst" in md
        assert "20260704" in md  # 最差日显形
        assert "owner 决策" in md

    def test_md_no_ci_cell_for_small_bucket(self):
        payload = self._payload()
        md = render_md(payload, "20260905")
        small_rows = [
            r for r in payload["cohort_buckets"]
            if r["event_stats"]["n"] < MIN_CELL_N
        ]
        assert small_rows, "fixture 必须含小样本桶"
        for r in small_rows:
            assert r["event_stats"]["cluster_ci_low_90"] is None


class TestStrongShareCorrelation:
    def test_known_sign_and_single_day_none(self):
        net = [0.10, 0.02, -0.05, -0.01]
        days = ["20260701", "20260701", "20260702", "20260702"]
        strong = [True, False, False, False]
        out = strong_share_correlation(net, days, strong)
        # day1: share 0.5, E +0.06; day2: share 0.0, E −0.03 → 正相关
        assert out["pearson"] is not None and out["pearson"] > 0.9
        assert out["n_days"] == 2
        single = strong_share_correlation([0.01, 0.02], ["20260701", "20260701"], [True, False])
        assert single["pearson"] is None and single["n_days"] == 1

    def test_zero_variance_returns_none(self):
        out = strong_share_correlation([0.01, 0.01], ["20260701", "20260702"], [True, True])
        assert out["pearson"] is None


class TestStrengthCohortCrossTable:
    """R131 Op1: 强度桶 × cohort 规模桶 交叉表 — 格放置/对齐/披露纪律."""

    # 非对称 fixture (R13 教训): 三个信号日规模与强度构成都不同, 每格
    # 的期望计数手工可算 — day A 1 事件 (0.75); day B 4 事件 (0.72/0.62/
    # 0.40/0.55); day C 2 事件 (0.30/0.80)。
    def _rows(self):
        return [
            ("900001", 20260701, 0.08, 0.75),
            ("900101", 20260704, 0.05, 0.72),
            ("900102", 20260704, 0.03, 0.62),
            ("900103", 20260704, -0.04, 0.40),
            ("900104", 20260704, 0.01, 0.55),
            ("900201", 20260710, 0.02, 0.30),
            ("900202", 20260710, 0.06, 0.80),
        ]

    def _table(self):
        net, days, strong = _aligned(self._rows())
        from src.screening.offensive.threshold_trigger import strength_bucket
        labels = [strength_bucket(0.75), strength_bucket(0.72), strength_bucket(0.62),
                  strength_bucket(0.40), strength_bucket(0.55), strength_bucket(0.30),
                  strength_bucket(0.80)]
        return strength_cohort_cross_table(net, days, labels)

    def _cell(self, table, cohort, strength):
        row = next(r for r in table if r["cohort_bucket"] == cohort)
        return next(c for c in row["cells"] if c["strength_bucket"] == strength)

    def test_cell_placement_asymmetric_with_manual_counts(self):
        table = self._table()
        # 行 = 全部 cohort 桶 (含空桶), 列 = 全部强度桶 (含 unknown)
        assert [r["cohort_bucket"] for r in table] == list(COHORT_BUCKET_LABELS)
        assert [c["strength_bucket"] for c in table[0]["cells"]] == list(
            ALL_STRENGTH_BUCKETS
        )
        # 手工计数 oracle: 逐格 n 与 days
        assert self._cell(table, "1", "≥0.70")["n"] == 1
        assert self._cell(table, "1", "≥0.70")["days"] == 1
        assert self._cell(table, "4-9", "≥0.70")["n"] == 1
        assert self._cell(table, "4-9", "0.60-0.70")["n"] == 1
        assert self._cell(table, "4-9", "0.50-0.60")["n"] == 1
        assert self._cell(table, "4-9", "<0.50")["n"] == 1
        assert self._cell(table, "2-3", "<0.50")["n"] == 1
        assert self._cell(table, "2-3", "≥0.70")["n"] == 1
        # 同一格内多日会聚合 days — 此 fixture 无此形态, 单独测
        # 全体事件 n 恒等 (分格不丢事件)
        assert sum(
            c["n"] for r in table for c in r["cells"]
        ) == len(self._rows())

    def test_expectancy_identity_per_cell(self):
        # 格 E = 格内成员均值 (win_loss_stats 恒等) — 手工重算一格
        table = self._table()
        # 4-9 桶 0.62 事件 gross 0.03 → net = 0.03 - 0.0065
        assert self._cell(table, "4-9", "0.60-0.70")["expectancy"] == pytest.approx(0.03 - 0.0065)

    def test_empty_cell_all_none_and_days_zero(self):
        table = self._table()
        cell = self._cell(table, "1", "<0.50")  # 单票日无弱强度事件
        assert cell["n"] == 0 and cell["days"] == 0
        assert cell["expectancy"] is None and cell["winrate"] is None
        assert cell["payoff"] is None and cell["cluster_ci_low_90"] is None

    def test_small_cell_ci_none_large_cell_ci_float(self):
        net, days, strong = _aligned(
            [
                ("900001", 20260701, 0.08, 0.75),
                ("900002", 20260701, 0.02, 0.30),
                *[
                    (f"90030{i:02d}", 20260704 + (i % 2), -0.01 - i * 0.0005, 0.55)
                    for i in range(30)
                ],
            ]
        )
        from src.screening.offensive.threshold_trigger import strength_bucket
        labels = [strength_bucket(0.75), strength_bucket(0.30)] + [
            strength_bucket(0.55)
        ] * 30
        table = strength_cohort_cross_table(net, days, labels)
        # 4-9 桶 (20260701 两事件落 2-3 桶? 1 日 2 事件 → 2-3; 0.75+0.30) —
        # 30 事件分两天各 15 → cohort 10-19 桶 0.50-0.60 格 n=30≥30 且 2 日
        big = self._cell(table, "10-19", "0.50-0.60")
        assert big["n"] == 30 and big["days"] == 2
        assert isinstance(big["cluster_ci_low_90"], float)
        small = self._cell(table, "2-3", "≥0.70")
        assert small["n"] == 1
        assert small["cluster_ci_low_90"] is None

    def test_length_mismatch_fails(self):
        with pytest.raises(ValueError, match="length mismatch"):
            strength_cohort_cross_table([0.1, 0.2], ["20260701"], ["≥0.70", "<0.50"])

    def test_deterministic_bytes(self):
        net, days, strong = _aligned(self._rows())
        from src.screening.offensive.threshold_trigger import strength_bucket
        labels = [strength_bucket(r[3]) for r in self._rows()]
        t1 = json.dumps(strength_cohort_cross_table(net, days, labels), sort_keys=True)
        t2 = json.dumps(strength_cohort_cross_table(net, days, labels), sort_keys=True)
        assert t1 == t2

    def test_payload_includes_cross_and_nan_alignment(self):
        rows = self._rows() + [("888888", 20260710, float("nan"), 0.9)]
        payload = decompose_cohort(_frame(rows))
        cross = payload["strength_cohort_cross"]
        # NaN gross 行跳过且不错位: 事件总数 = 7 (非 8)
        assert sum(c["n"] for r in cross for c in r["cells"]) == 7
        # 0.9 行 (NaN gross) 被跳过 — 若错位会污染 ≥0.70 计数
        assert self._cell(cross, "2-3", "≥0.70")["n"] == 1


class TestCrossRenderR131:
    """R131 Op1: MD 交叉段 — 探索性标注 + 纪律句 + 小样本尾注."""

    def _payload(self):
        rows: list[tuple[str, int, float, float]] = [
            ("900001", 20260701, 0.08, 0.75),
            *[
                (f"90030{i:02d}", 20260704, -0.05 - i * 0.001, 0.72)
                for i in range(20)
            ],
            *[
                (f"90040{i:02d}", 20260710, 0.005 + i * 0.0005, 0.30)
                for i in range(16)
            ],
        ]
        return decompose_cohort(_frame(rows))

    def test_md_section_discipline_and_note(self):
        md = render_md(self._payload(), "20260906")
        assert "强度 × cohort 规模交叉" in md
        assert "探索性 in-sample" in md
        assert "交叉格判定未预注册" in md
        assert "不进触发器账本" in md
        assert "新证据世代 owner 决策" in md
        # 0.75×1 = 1 事件格 + 0.30×16 落 10-19? (16 只 → 10-19 桶) — 小格尾注
        assert f"事件 n < {MIN_CELL_N}" in md
        assert "strength_cohort_cross" in md  # JSON 指针句

    def test_md_matrix_has_strength_rows_and_cohort_columns(self):
        payload = self._payload()
        md = render_md(payload, "20260906")
        for s in ALL_STRENGTH_BUCKETS:
            assert f"| {s} " in md or md.count(f"| {s} |") >= 1
        cross = payload["strength_cohort_cross"]
        for row in cross:
            if any(c["n"] for c in row["cells"]):
                assert f"| {row['cohort_bucket']} |" in md or f"| {row['cohort_bucket']} " in md


class TestAdversarialReworkR124:
    """Op2 对抗审查 PoC 回归 — 三裸逃逸形态 typed 化 + 真中位."""

    def _base(self, **overrides):
        cols = {
            "ts_code": ["1.SZ", "2.SZ"],
            "signal_date": [20260701, 20260702],
            "gross_ret_t10": [0.01, 0.02],
            "trigger_strength": [0.7, 0.4],
            "fillable": True,
            "gate_blocked": False,
            "price_ge_3": True,
            "degraded": False,
            "st_name": "",
            "industry_missing": False,
            "excluded_ticker": False,
        }
        cols.update(overrides)
        return pd.DataFrame(cols)

    def test_missing_trigger_strength_typed(self):
        # PoC-A 复现: 缺列曾是裸 KeyError 'trigger_strength'
        ev = self._base().drop(columns=["trigger_strength"])
        with pytest.raises(SystemExit, match="trigger_strength"):
            decompose_cohort(ev)

    def test_missing_signal_date_typed(self):
        ev = self._base().drop(columns=["signal_date"])
        with pytest.raises(SystemExit, match="signal_date"):
            decompose_cohort(ev)

    def test_nan_date_typed_and_counted(self):
        # PoC-B 复现: 单 NaN 曾使整列上转型 → 合法行报 '20260701.0' ValueError。
        # 现契约: 预检类型化拒绝 + 畸形计数, 消息不再误导到合法值。
        ev = self._base()
        ev.loc[1, "signal_date"] = float("nan")
        with pytest.raises(SystemExit, match="signal_date 畸形 1 行"):
            decompose_cohort(ev)

    def test_whole_float_dates_accepted(self):
        # dtype 上转型的合法表 (全整值 float64 日期) 必须照常工作
        ev = self._base()
        ev["signal_date"] = ev["signal_date"].astype("float64")
        payload = decompose_cohort(ev)
        assert payload["n_events"] == 2
        assert payload["n_days"] == 2

    def test_non_numeric_strength_typed(self):
        ev = self._base()
        # float64 列塞不进字符串 (pandas LossySetitemError) — object 列构造垃圾输入
        ev["trigger_strength"] = pd.Series(["abc", 0.4], dtype=object)
        with pytest.raises(SystemExit, match="trigger_strength 非数值 1 行"):
            decompose_cohort(ev)

    def test_even_day_count_true_median(self):
        # PoC-C 复现: 日均值 [1,2,3,4]% 曾返回上元素 0.03 → 真中位 0.025
        net = [0.01, 0.02, 0.03, 0.04]
        days = ["d1", "d2", "d3", "d4"]
        strong = [False] * 4
        rows = cohort_bucket_table(net, days, strong)
        assert rows[0]["bucket"] == "1"
        assert rows[0]["day_e_median"] == pytest.approx(0.025)
        # 奇数日数语义不变
        rows_odd = cohort_bucket_table(net[:3], days[:3], strong[:3])
        assert rows_odd[0]["day_e_median"] == pytest.approx(0.02)


def test_cohort_size_bucket_single_implementation_identity():
    """R125 Op3: bucket 函数上移 src — 脚本名字必须是同一对象 (零漂移构造保证)."""
    from src.screening.offensive.gap_disclosure import (
        cohort_size_bucket as src_cohort_size_bucket,
    )
    from scripts import btst_signal_day_cohort as mod

    assert mod.cohort_size_bucket is src_cohort_size_bucket
    assert mod.COHORT_BUCKET_LABELS == ("1", "2-3", "4-9", "10-19", "20+")


# ---------------------------------------------------------------------------
# 日层 cohort 触发器 (R126 Op1): 机械判定 + 数据前进门落账 + MD 披露
# ---------------------------------------------------------------------------

from scripts.btst_signal_day_cohort import (  # noqa: E402
    COHORT_TRIGGER_ANCHOR,
    cohort_trigger_status,
    record_cohort_trigger_status,
)


def _bucket_row(label: str, n: int, expectancy: float, ci: float | None) -> dict:
    """_bucket_stats 输出形状的桶行夹具 (event_stats 经 win_loss_stats 同形)。"""
    return {
        "bucket": label,
        "days": max(1, n // 8),
        "n": n,
        "day_e_median": expectancy / 2,
        "event_stats": {
            "n": n,
            "winrate": 0.45,
            "expectancy": expectancy,
            "payoff": 1.2,
            "cluster_ci_low_90": ci,
        },
    }


def _rows(
    *,
    n_strong=340, e_strong=0.0169, ci_strong=0.0007,
    n_49=293, e_49=-0.0249,
    n_1019=408, e_1019=-0.0111,
    with_strong=True, with_49=True, with_1019=True,
) -> list[dict]:
    """production_aligned 20260905 实测结构的桶行组 (C1 点亮 / C2 点亮)。"""
    rows: list[dict] = []
    if with_strong:
        rows.append(_bucket_row("20+", n_strong, e_strong, ci_strong))
    if with_49:
        rows.append(_bucket_row("4-9", n_49, e_49, None))
    if with_1019:
        rows.append(_bucket_row("10-19", n_1019, e_1019, None))
    return rows


class TestCohortTriggerStatus:
    def test_both_conditions_lit_arms_conjunction(self):
        t = cohort_trigger_status(_rows(), min_n=MIN_CELL_N)
        assert t["anchor"] == COHORT_TRIGGER_ANCHOR
        assert t["condition_strong_bucket_ci_above_zero"]["lit"] is True
        assert t["condition_strong_bucket_ci_above_zero"]["judged"] is True
        assert t["condition_mid_buckets_expectancy_negative"]["lit"] is True
        # stat = max(两桶期望): -0.0111 > -0.0249
        assert t["condition_mid_buckets_expectancy_negative"]["stat"] == pytest.approx(-0.0111)
        assert t["condition_mid_buckets_expectancy_negative"]["n"] == 293
        assert t["conjunction_armed"] is True
        assert "合取点亮" in t["verdict"]

    def test_c2_unlit_when_one_mid_bucket_positive(self):
        t = cohort_trigger_status(_rows(e_1019=0.005), min_n=MIN_CELL_N)
        c2 = t["condition_mid_buckets_expectancy_negative"]
        assert c2["lit"] is False and c2["judged"] is True
        assert c2["stat"] == pytest.approx(0.005)  # max 语义
        assert t["conjunction_armed"] is False
        assert "条件C1点亮" in t["verdict"] and "未点亮" in t["verdict"]

    def test_missing_mid_bucket_row_unjudged(self):
        t = cohort_trigger_status(_rows(with_1019=False), min_n=MIN_CELL_N)
        c2 = t["condition_mid_buckets_expectancy_negative"]
        assert c2["judged"] is False and c2["lit"] is False
        assert "桶行缺失" in c2["reason"]
        assert t["conjunction_armed"] is False

    def test_small_n_disclosed_not_judged(self):
        t = cohort_trigger_status(
            _rows(n_strong=20, with_49=False, with_1019=False), min_n=MIN_CELL_N
        )
        c1 = t["condition_strong_bucket_ci_above_zero"]
        assert c1["judged"] is False
        assert "只披露不判定" in c1["reason"]
        assert t["conjunction_armed"] is False
        assert "两条件均未点亮" in t["verdict"]

    def test_ci_none_unjudged_not_crash(self):
        t = cohort_trigger_status(_rows(ci_strong=None), min_n=MIN_CELL_N)
        c1 = t["condition_strong_bucket_ci_above_zero"]
        assert c1["judged"] is False
        assert "缺失" in c1["reason"]

    def test_c2_only_lit_verdict(self):
        t = cohort_trigger_status(_rows(ci_strong=-0.01), min_n=MIN_CELL_N)
        assert t["condition_mid_buckets_expectancy_negative"]["lit"] is True
        assert t["condition_strong_bucket_ci_above_zero"]["lit"] is False
        assert t["conjunction_armed"] is False
        assert "条件C2点亮" in t["verdict"]

    def test_bool_stat_poisoning_unjudged(self):
        """bool 是 int 子类 — True 当 stat 是形状欺骗, 未判定不点亮 (R113 同款)。"""
        rows = _rows()
        rows[0]["event_stats"]["cluster_ci_low_90"] = True
        t = cohort_trigger_status(rows, min_n=MIN_CELL_N)
        assert t["condition_strong_bucket_ci_above_zero"]["judged"] is False

    def test_float_n_poisoning_unjudged(self):
        rows = _rows(n_49=293.0)  # type: ignore[arg-type]
        t = cohort_trigger_status(rows, min_n=MIN_CELL_N)
        c2 = t["condition_mid_buckets_expectancy_negative"]
        assert c2["judged"] is False
        assert "只披露不判定" in c2["reason"]


class TestRecordCohortTrigger:
    @staticmethod
    def _payload(**kw) -> dict:
        return {"cohort_trigger": cohort_trigger_status(_rows(**kw), min_n=MIN_CELL_N)}

    def test_missing_trigger_noop(self, tmp_path):
        ledger = tmp_path / "ledger.jsonl"
        meta = record_cohort_trigger_status({}, "20260905", ledger_path=ledger)
        assert meta == {"recorded": False, "reason": "no_cohort_trigger"}
        assert not ledger.exists()

    def test_snapshot_shape_and_court_binding(self, tmp_path):
        ledger = tmp_path / "ledger.jsonl"
        binding = {"window_end": "20260904", "rows": 1884}
        meta = record_cohort_trigger_status(
            self._payload(), "20260905", ledger_path=ledger, court_binding=binding
        )
        assert meta["recorded"] is True and meta["records"] == 1
        rec = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
        assert rec["date"] == "20260905"
        assert rec["anchor"] == COHORT_TRIGGER_ANCHOR
        assert rec["strong_bucket"]["lit"] is True
        assert rec["mid_buckets"]["lit"] is True
        assert rec["conjunction_armed"] is True
        assert rec["court"] == binding

    def test_same_date_refresh_replaces(self, tmp_path):
        ledger = tmp_path / "ledger.jsonl"
        record_cohort_trigger_status(self._payload(), "20260905", ledger_path=ledger)
        record_cohort_trigger_status(
            self._payload(e_1019=0.005), "20260905", ledger_path=ledger
        )
        from src.screening.offensive.cohort_trigger import (
            load_cohort_trigger_ledger,
        )

        records = load_cohort_trigger_ledger(ledger)
        assert len(records) == 1
        assert records[0]["mid_buckets"]["lit"] is False

    def test_require_advance_gate_skips_same_data(self, tmp_path):
        """数据前进门: 绑定与任一历史记录相同 → skip 不追加 (R84 Op2-B 同款)。"""
        from src.screening.offensive.cohort_trigger import (
            load_cohort_trigger_ledger,
        )

        ledger = tmp_path / "ledger.jsonl"
        binding = {"window_end": "20260904", "rows": 1884, "content_digest": "sha256:x"}
        record_cohort_trigger_status(
            self._payload(), "20260905", ledger_path=ledger, court_binding=binding
        )
        meta = record_cohort_trigger_status(
            self._payload(), "20260906", ledger_path=ledger,
            court_binding=dict(binding), require_advance=True,
        )
        assert meta == {"recorded": False, "reason": "court_not_advanced", "records": 1}
        assert len(load_cohort_trigger_ledger(ledger)) == 1

    def test_require_advance_new_data_appends(self, tmp_path):
        from src.screening.offensive.cohort_trigger import (
            load_cohort_trigger_ledger,
        )

        ledger = tmp_path / "ledger.jsonl"
        old = {"window_end": "20260903", "rows": 1800, "content_digest": "sha256:old"}
        new = {"window_end": "20260904", "rows": 1884, "content_digest": "sha256:new"}
        record_cohort_trigger_status(
            self._payload(), "20260904", ledger_path=ledger, court_binding=old
        )
        meta = record_cohort_trigger_status(
            self._payload(), "20260905", ledger_path=ledger,
            court_binding=new, require_advance=True,
        )
        assert meta["recorded"] is True
        records = load_cohort_trigger_ledger(ledger)
        assert [r["date"] for r in records] == ["20260904", "20260905"]

    def test_gate_passes_legacy_record_without_court(self, tmp_path):
        """旧形态记录无 court 字段 → 门放行 (不追溯拒绝, 绑定自本轮起积累)。"""
        ledger = tmp_path / "ledger.jsonl"
        record_cohort_trigger_status(self._payload(), "20260904", ledger_path=ledger)
        meta = record_cohort_trigger_status(
            self._payload(), "20260905", ledger_path=ledger,
            court_binding={"rows": 1}, require_advance=True,
        )
        assert meta["recorded"] is True

    def test_data_regression_across_history_rejected(self, tmp_path):
        """A→B→A 回退: A 绑定在历史深处也命中前进门 (单点比对会被绕过)。"""
        ledger = tmp_path / "ledger.jsonl"
        a = {"content_digest": "sha256:a"}
        b = {"content_digest": "sha256:b"}
        record_cohort_trigger_status(
            self._payload(), "20260903", ledger_path=ledger, court_binding=a
        )
        record_cohort_trigger_status(
            self._payload(), "20260904", ledger_path=ledger, court_binding=b
        )
        meta = record_cohort_trigger_status(
            self._payload(), "20260905", ledger_path=ledger,
            court_binding=dict(a), require_advance=True,
        )
        assert meta["reason"] == "court_not_advanced"

    def test_write_failure_fail_open(self, tmp_path, capsys):
        ledger = tmp_path / "as_dir"  # 目录当账本 → os.replace 失败
        ledger.mkdir()
        meta = record_cohort_trigger_status(self._payload(), "20260905", ledger_path=ledger)
        assert meta == {"recorded": False, "reason": "write_failed"}
        assert "fail-open" in capsys.readouterr().out


class TestCohortTriggerRenderAndMain:
    def _payload_with_trigger(self) -> dict:
        from src.screening.offensive.cohort_trigger import cohort_trigger_stability

        payload = decompose_cohort(_frame([
            ("600001", 20260701, 0.05, 0.75), ("600002", 20260701, -0.03, 0.55),
            ("600003", 20260702, 0.02, 0.52), ("600004", 20260702, 0.04, 0.80),
            ("600005", 20260703, -0.01, 0.63), ("600006", 20260703, 0.03, 0.71),
        ]))
        payload["cohort_trigger"] = cohort_trigger_status(
            payload["cohort_buckets"], min_n=MIN_CELL_N
        )
        payload["cohort_trigger_stability"] = cohort_trigger_stability([
            {"date": "20260904", "conjunction_armed": True,
             "strong_bucket": {"lit": True}, "mid_buckets": {"lit": True}},
            {"date": "20260905", "conjunction_armed": False,
             "strong_bucket": {"lit": True}, "mid_buckets": {"lit": False}},
        ])
        return payload

    def test_md_trigger_section(self):
        md = render_md(self._payload_with_trigger(), "20260905")
        assert "## 日层 cohort 触发器状态" in md
        assert "条件C1" in md and "条件C2" in md
        assert "**合取: 未点亮**" in md
        assert "稳定计数" in md
        assert "历史最多合取连亮 1" in md
        assert "稳定阈值 K 未预注册" in md

    def test_md_without_trigger_unchanged(self):
        rows = [
            ("600001", 20260701, 0.05, 0.75), ("600002", 20260701, -0.03, 0.55),
            ("600003", 20260702, 0.02, 0.52), ("600004", 20260702, 0.04, 0.80),
            ("600005", 20260703, -0.01, 0.63), ("600006", 20260703, 0.03, 0.71),
        ]
        plain = render_md(decompose_cohort(_frame(rows)), "20260905")
        assert "日层 cohort 触发器状态" not in plain

    def _write_table(self, tmp_path) -> Path:
        table = tmp_path / "event_table_v1.csv.gz"
        _frame([
            ("600001", 20260701, 0.05, 0.75), ("600002", 20260701, -0.03, 0.55),
            ("600003", 20260702, 0.02, 0.52), ("600004", 20260702, 0.04, 0.80),
            ("600005", 20260703, -0.01, 0.63), ("600006", 20260703, 0.03, 0.71),
        ]).to_csv(table, index=False)
        return table

    def test_main_records_and_second_run_gated(self, tmp_path, capsys):
        """端到端: main 落账首条判定; 同表二次刷新被前进门 skip (R84 语义)。"""
        from scripts.btst_signal_day_cohort import main as cohort_main
        from src.screening.offensive.cohort_trigger import (
            load_cohort_trigger_ledger,
        )

        table = self._write_table(tmp_path)
        ledger = tmp_path / "cohort_ledger.jsonl"
        reports = tmp_path / "reports"
        argv = [
            "--court-table", str(table),
            "--report-dir", str(reports),
            "--cohort-trigger-ledger", str(ledger),
        ]
        rc = cohort_main(argv)
        assert rc == 0
        first = json.loads(capsys.readouterr().out.strip().splitlines()[0])
        assert first["cohort_trigger_record"]["recorded"] is True
        records = load_cohort_trigger_ledger(ledger)
        assert len(records) == 1
        assert records[0]["court"]["content_digest"] is not None

        rc2 = cohort_main(argv)
        assert rc2 == 0
        second = json.loads(capsys.readouterr().out.strip().splitlines()[0])
        assert second["cohort_trigger_record"]["reason"] == "court_not_advanced"
        assert len(load_cohort_trigger_ledger(ledger)) == 1

    def test_main_missing_table_fails_closed(self, tmp_path):
        from scripts.btst_signal_day_cohort import main as cohort_main

        with pytest.raises(SystemExit, match="court 事件表缺失"):
            cohort_main([
                "--court-table", str(tmp_path / "missing.csv"),
                "--report-dir", str(tmp_path / "r"),
                "--cohort-trigger-ledger", str(tmp_path / "l.jsonl"),
            ])


class TestCohortKBuildWiring:
    """R129 Op1: build 侧 K 预注册消费面 (镜像强度族 R112-R115 接线)。

    先观测后披露; 观测失败 advisory 不阻断; payload["cohort_threshold_k"]
    是渲染与 MD 共用的单一事实源快照。"""

    @staticmethod
    def _argv(tmp_path, extra=()):
        table = tmp_path / "event_table_v1.csv.gz"
        _frame([
            ("600001", 20260701, 0.05, 0.75), ("600002", 20260701, -0.03, 0.55),
            ("600003", 20260702, 0.02, 0.52), ("600004", 20260702, 0.04, 0.80),
            ("600005", 20260703, -0.01, 0.63), ("600006", 20260703, 0.03, 0.71),
        ]).to_csv(table, index=False)
        return [
            "--court-table", str(table),
            "--report-dir", str(tmp_path / "reports"),
            "--cohort-trigger-ledger", str(tmp_path / "cohort_ledger.jsonl"),
            "--cohort-k-registration", str(tmp_path / "cohort_k.json"),
            "--cohort-k-observation-log", str(tmp_path / "cohort_k_obs.jsonl"),
            *extra,
        ]

    @staticmethod
    def _write_reg(tmp_path, payload):
        import json as _json

        path = tmp_path / "cohort_k.json"
        path.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    @staticmethod
    def _payload_with_trigger() -> dict:
        from src.screening.offensive.cohort_trigger import (
            cohort_trigger_stability,
        )

        payload = decompose_cohort(_frame([
            ("600001", 20260701, 0.05, 0.75), ("600002", 20260701, -0.03, 0.55),
            ("600003", 20260702, 0.02, 0.52), ("600004", 20260702, 0.04, 0.80),
            ("600005", 20260703, -0.01, 0.63), ("600006", 20260703, 0.03, 0.71),
        ]))
        payload["cohort_trigger"] = cohort_trigger_status(
            payload["cohort_buckets"], min_n=MIN_CELL_N
        )
        payload["cohort_trigger_stability"] = cohort_trigger_stability([
            {"date": "20260904", "conjunction_armed": True,
             "strong_bucket": {"lit": True}, "mid_buckets": {"lit": True}},
            {"date": "20260905", "conjunction_armed": False,
             "strong_bucket": {"lit": True}, "mid_buckets": {"lit": False}},
        ])
        return payload

    def test_main_unregistered_state_disclosed(self, tmp_path, capsys):
        from scripts.btst_signal_day_cohort import main as cohort_main

        rc = cohort_main(self._argv(tmp_path))
        assert rc == 0
        reports = tmp_path / "reports"
        json_path = next(reports.glob("signal_day_cohort_*.json"))
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload["cohort_threshold_k"]["state"] == "unregistered"
        assert payload["cohort_threshold_k"]["line"] == (
            "稳定阈值 K 属 owner 预注册；披露不是行为改变"
        )
        assert not (tmp_path / "cohort_k_obs.jsonl").exists()

    def test_main_registered_observes_then_discloses(self, tmp_path):
        from scripts.btst_signal_day_cohort import main as cohort_main
        from src.screening.offensive.cohort_trigger import (
            cohort_trigger_stability,
            load_cohort_trigger_ledger,
        )

        self._write_reg(tmp_path, {
            "anchor": "production_aligned/t10/cohort_size",
            "registered_date": "20260901",
            "k": 5,
        })
        rc = cohort_main(self._argv(tmp_path))
        assert rc == 0
        reports = tmp_path / "reports"
        json_path = next(reports.glob("signal_day_cohort_*.json"))
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        k = payload["cohort_threshold_k"]
        assert k["state"] == "registered"
        assert "预注册 K=5" in k["line"]
        assert k["qualified"] is False
        # 反回溯观测已落 append-only 日志
        obs = tmp_path / "cohort_k_obs.jsonl"
        assert obs.exists()
        rec = json.loads(obs.read_text(encoding="utf-8").strip().splitlines()[0])
        assert rec["observed_date"] == date.today().strftime("%Y%m%d")
        assert rec["anchor"] == "production_aligned/t10/cohort_size"
        # MD 尾行取单一事实源 (注册态)
        md_path = next(reports.glob("signal_day_cohort_*.md"))
        assert "预注册 K=5" in md_path.read_text(encoding="utf-8")

    def test_main_registered_stability_reads_ledger_true_state(self, tmp_path):
        """资格连亮读账本现状真话 — 未武装账本 + K=1 也不给资格达标。"""
        from scripts.btst_signal_day_cohort import main as cohort_main

        self._write_reg(tmp_path, {
            "anchor": "production_aligned/t10/cohort_size",
            "registered_date": "20260901",
            "k": 1,
        })
        assert cohort_main(self._argv(tmp_path)) == 0
        reports = tmp_path / "reports"
        json_path = next(reports.glob("signal_day_cohort_*.json"))
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        k = payload["cohort_threshold_k"]
        # 首次 build 的账本行 conjunction_armed 由数据决定; 本表 6 行小样本
        # 触发器格判 unjudged → 合取未武装 → q=0 未达标
        assert k["qualified"] is False
        assert k["line"].startswith("预注册 K=1")

    def test_main_malformed_registration_disclosed_not_crash(self, tmp_path):
        from scripts.btst_signal_day_cohort import main as cohort_main

        path = tmp_path / "cohort_k.json"
        path.write_text("{corrupted", encoding="utf-8")
        assert cohort_main(self._argv(tmp_path)) == 0
        reports = tmp_path / "reports"
        json_path = next(reports.glob("signal_day_cohort_*.json"))
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        k = payload["cohort_threshold_k"]
        assert k["state"] == "malformed"
        assert "损坏" in k["line"]

    def test_md_registered_line_replaces_default_sentence(self):
        from scripts.btst_signal_day_cohort import render_md

        payload = self._payload_with_trigger()
        payload["cohort_threshold_k"] = {
            "state": "registered",
            "line": "预注册 K=3（自 20260901 起计资格连亮 1/3）",
            "qualified": False,
            "effective_registered_date": "20260901",
            "backdated": False,
        }
        md = render_md(payload, "20260905")
        assert "- 预注册 K=3（自 20260901 起计资格连亮 1/3）" in md
        assert "稳定阈值 K 未预注册" not in md

    def test_md_unregistered_keeps_legacy_default_sentence(self):
        """未注册态 MD 行保持既有句子逐字节 (既有断言钉死, 不改写)。"""
        from scripts.btst_signal_day_cohort import render_md

        payload = self._payload_with_trigger()
        payload["cohort_threshold_k"] = {
            "state": "unregistered",
            "line": "稳定阈值 K 属 owner 预注册；披露不是行为改变",
            "qualified": False,
            "effective_registered_date": None,
            "backdated": False,
        }
        md = render_md(payload, "20260905")
        assert "稳定阈值 K 未预注册" in md


class TestRenderFoldDisclosure:
    """R130 Op2: 日层 MD 稳定计数措辞收敛 + 折叠披露 (有/无双态)。"""

    def _payload_with_stability(self, folded: int):
        rows: list[tuple[str, int, float, float]] = [
            ("900001", 20260701, 0.08, 0.75),
            *[
                (f"90030{i:02d}", 20260704, -0.05 - i * 0.001, 0.72)
                for i in range(20)
            ],
            *[
                (f"90040{i:02d}", 20260710, 0.005 + i * 0.0005, 0.30)
                for i in range(16)
            ],
        ]
        payload = dict(decompose_cohort(_frame(rows)))
        payload["cohort_trigger"] = {
            "anchor": "production_aligned/t10/cohort_size", "min_n": 30,
            "condition_strong_bucket_ci_above_zero": {
                "lit": True, "judged": True, "n": 864, "stat": -0.017},
            "condition_mid_buckets_expectancy_negative": {
                "lit": True, "judged": True, "n": 293, "stat": -0.011},
            "conjunction_armed": False, "verdict": "夹具",
        }
        payload["cohort_trigger_stability"] = {
            "records": 2, "first_date": "20260904", "last_date": "20260905",
            "strong_bucket_streak": 1, "mid_buckets_streak": 1,
            "conjunction_streak": 0, "max_conjunction_streak": 0,
            "folded_duplicates": folded,
        }
        return payload

    def test_md_fold_disclosed_when_present(self):
        md = render_md(self._payload_with_stability(1), "20260905")
        assert "连亮按不同数据状态计数" in md
        assert "折叠同数据重复观测 1 条" in md
        assert "跨刷新逐次记录" not in md

    def test_md_clean_ledger_no_fold_clause(self):
        md = render_md(self._payload_with_stability(0), "20260905")
        assert "折叠" not in md


class TestAdversarialPinningR131Op3:
    """Op3 对抗性审查钉死: 交叉表边际 == cohort_buckets 同桶 n (口径绑定)."""

    def test_cross_table_marginals_match_cohort_buckets(self):
        # 非对称 fixture: 每桶不同事件数; 两个视图的分组维度同源
        # (cohort_size_bucket 单一实现) 但此前无双视图一致性绑定 — 口径
        # 漂移 (如边界单侧改动) 会静默分叉, 本测试封死。
        rows: list[tuple[str, int, float, float]] = [
            ("900001", 20260701, 0.08, 0.75),  # 1×1
            *[
                (f"90020{i:02d}", 20260703, 0.01 + i * 0.001, 0.52)
                for i in range(2)
            ],  # 2-3 ×2
            *[
                (f"90030{i:02d}", 20260704, -0.05 - i * 0.001, 0.72)
                for i in range(20)
            ],  # 20+ ×20
            *[
                (f"90040{i:02d}", 20260710, 0.005 + i * 0.0005, 0.30)
                for i in range(16)
            ],  # 10-19 ×16
            *[
                (f"90050{i:02d}", 20260711, -0.02 - i * 0.001, 0.62)
                for i in range(7)
            ],  # 4-9 ×7
        ]
        payload = decompose_cohort(_frame(rows))
        cross = payload["strength_cohort_cross"]
        buckets = payload["cohort_buckets"]
        for b in buckets:
            marginal = sum(
                c["n"] for r in cross if r["cohort_bucket"] == b["bucket"]
                for c in r["cells"]
            )
            assert marginal == b["event_stats"]["n"], (
                f"交叉表 {b['bucket']} 桶边际 n={marginal} != "
                f"cohort_buckets n={b['event_stats']['n']} — 分组口径漂移"
            )
        # 全表事件合计恒等
        assert sum(c["n"] for r in cross for c in r["cells"]) == payload["n_events"]
