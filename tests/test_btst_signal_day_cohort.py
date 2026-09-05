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
    strong_share_correlation,
    variance_decomposition,
    worst_days,
)
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
