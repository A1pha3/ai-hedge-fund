"""NS-7 TDD — model_version comparison diagnostic (新模型效果监测).

§三·6 backlog (NS-7, P2): owner 改因子后 (commits ab96aae0..e5406887) 累积 T+5/T+10
后, 按 NS-2 model_version (git short sha) 分组对比新旧模型的 winrate + median return,
告诉 owner 每次调参是否真的改善. NS-2 model_version 标注已存在于 TrackingRecord,
但 rank_monotonicity / north_star_pnl / factor_attribution_by_state 均未按 version
分组 — 本模块补这半环.

镜像 north_star_pnl 的 footer-block 模式 (best-effort, 数据不足诚实标 insufficient,
永不破坏前门). 纯诊断, 不改 gate/factor/仓位/score (越界=过拟合).

完整运行需新模型累积 ≥ min_samples 个 mature T+5/T+10 记录; 数据成熟前
verdict=insufficient (诚实, 不强行下结论).
"""

from __future__ import annotations

from src.screening.model_version_comparison import (
    ModelVersionComparison,
    compute_model_version_metrics,
    compare_model_versions,
    render_model_version_comparison_line,
)


def _rec(version: str, ret5: float, date: str) -> dict:
    """Build a tracking record tagged with model_version + T+5 return + date.

    ``ret5`` is in **PERCENT** (e.g. 1.8 = 1.8%), matching the real
    ``next_5day_return`` unit in tracking_history (verified on 7500-record sample).
    """
    return {
        "model_version": version,
        "next_5day_return": ret5,
        "recommended_date": date,
    }


class TestComputeModelVersionMetrics:
    """Per-version winrate + median + n_samples, grouped by model_version."""

    def test_two_versions_grouped_with_correct_winrate_and_median(self) -> None:
        # v_old: 4 records, 1 positive (25% winrate), returns [-10, -5, 2, -3] percent
        # v_new: 4 records, 3 positive (75% winrate), returns [1, 3, -2, 5] percent
        records = [
            _rec("aaa1111aaaa", -10.0, "20260101"),
            _rec("aaa1111aaaa", -5.0, "20260102"),
            _rec("aaa1111aaaa", 2.0, "20260103"),
            _rec("aaa1111aaaa", -3.0, "20260104"),
            _rec("bbb2222bbbb", 1.0, "20260201"),
            _rec("bbb2222bbbb", 3.0, "20260202"),
            _rec("bbb2222bbbb", -2.0, "20260203"),
            _rec("bbb2222bbbb", 5.0, "20260204"),
        ]
        metrics = compute_model_version_metrics(records, min_samples=3)
        by_version = {m.model_version: m for m in metrics}
        assert by_version["aaa1111aaaa"].n_samples == 4
        assert by_version["aaa1111aaaa"].winrate == 0.25
        assert by_version["aaa1111aaaa"].median_return == -4.0  # median of sorted [-10,-5,-3,2]
        assert by_version["bbb2222bbbb"].n_samples == 4
        assert by_version["bbb2222bbbb"].winrate == 0.75
        assert by_version["bbb2222bbbb"].median_return == 2.0  # median of [-2,1,3,5]

    def test_records_without_model_version_skipped(self) -> None:
        records = [
            _rec("aaa1111aaaa", 0.02, "20260101"),
            {"next_5day_return": 0.05, "recommended_date": "20260102"},  # no model_version
            {"model_version": "", "next_5day_return": 0.05, "recommended_date": "20260103"},  # empty version
        ]
        metrics = compute_model_version_metrics(records, min_samples=1)
        assert len(metrics) == 1
        assert metrics[0].model_version == "aaa1111aaaa"
        assert metrics[0].n_samples == 1

    def test_nan_and_non_numeric_returns_skipped(self) -> None:
        records = [
            _rec("aaa1111aaaa", 0.02, "20260101"),
            _rec("aaa1111aaaa", float("nan"), "20260102"),
            _rec("aaa1111aaaa", "abc", "20260103"),  # type: ignore[arg-type]
            _rec("aaa1111aaaa", None, "20260104"),  # type: ignore[arg-type]
        ]
        metrics = compute_model_version_metrics(records, min_samples=1)
        assert metrics[0].n_samples == 1  # only the 0.02 record counts
        assert metrics[0].winrate == 1.0

    def test_versions_sorted_by_latest_date_descending(self) -> None:
        records = [
            _rec("old_ver00001", 0.01, "20260101"),
            _rec("new_ver00002", 0.01, "20260301"),
            _rec("mid_ver00003", 0.01, "20260201"),
        ]
        metrics = compute_model_version_metrics(records, min_samples=1)
        assert [m.model_version for m in metrics] == ["new_ver00002", "mid_ver00003", "old_ver00001"]

    def test_sufficient_flag_respects_min_samples(self) -> None:
        records = [_rec("aaa1111aaaa", 0.01, "20260101") for _ in range(3)]
        metrics = compute_model_version_metrics(records, min_samples=5)
        assert metrics[0].sufficient is False
        assert metrics[0].n_samples == 3


class TestCompareModelVersions:
    """Compare two most-recently-active versions; verdict on candidate vs baseline."""

    def test_candidate_higher_winrate_improved(self) -> None:
        records = [_rec("aaa1111aaaa", -0.10, "2026010%d" % d) for d in range(1, 5)] + [_rec("bbb2222bbbb", 0.03, "2026020%d" % d) for d in range(1, 5)]  # 0% winrate, baseline  # 100% winrate, candidate
        cmp = compare_model_versions(records, min_samples=3)
        assert cmp.verdict == "improved"
        assert cmp.candidate.model_version == "bbb2222bbbb"
        assert cmp.baseline.model_version == "aaa1111aaaa"
        assert cmp.delta_winrate == 1.0  # 1.0 - 0.0

    def test_candidate_lower_winrate_degraded(self) -> None:
        records = [_rec("aaa1111aaaa", 0.03, "2026010%d" % d) for d in range(1, 5)] + [_rec("bbb2222bbbb", -0.03, "2026020%d" % d) for d in range(1, 5)]  # 100% baseline  # 0% candidate
        cmp = compare_model_versions(records, min_samples=3)
        assert cmp.verdict == "degraded"
        assert cmp.delta_winrate == -1.0

    def test_candidate_insufficient_samples_verdict_insufficient(self) -> None:
        records = [_rec("aaa1111aaaa", 0.03, "2026010%d" % d) for d in range(1, 6)] + [_rec("bbb2222bbbb", 0.03, "2026020%d" % d) for d in range(1, 3)]  # 5 samples, baseline sufficient  # 2 samples, candidate insufficient
        cmp = compare_model_versions(records, min_samples=5)
        assert cmp.verdict == "insufficient"  # new model not enough data to judge

    def test_baseline_insufficient_verdict_inconclusive(self) -> None:
        records = [_rec("aaa1111aaaa", 0.03, "2026010%d" % d) for d in range(1, 3)] + [_rec("bbb2222bbbb", 0.03, "2026020%d" % d) for d in range(1, 6)]  # 2 samples, baseline insufficient  # 5 samples, candidate sufficient
        cmp = compare_model_versions(records, min_samples=5)
        assert cmp.verdict == "inconclusive"  # no reliable baseline to compare against

    def test_single_version(self) -> None:
        records = [_rec("only_ver00001", 0.03, "2026010%d" % d) for d in range(1, 6)]
        cmp = compare_model_versions(records, min_samples=3)
        assert cmp.verdict == "single_version"
        assert cmp.candidate.model_version == "only_ver00001"
        assert cmp.baseline is None

    def test_empty_records_no_data(self) -> None:
        cmp = compare_model_versions([], min_samples=3)
        assert cmp.verdict == "no_data"
        assert cmp.candidate is None
        assert cmp.baseline is None

    def test_equal_winrate_unchanged(self) -> None:
        records = [_rec("aaa1111aaaa", 0.03, "2026010%d" % d) for d in range(1, 5)] + [_rec("bbb2222bbbb", 0.03, "2026020%d" % d) for d in range(1, 5)]  # 100%  # 100%
        cmp = compare_model_versions(records, min_samples=3)
        assert cmp.verdict == "unchanged"
        assert cmp.delta_winrate == 0.0


class TestRenderLine:
    """Render a footer line; honest on insufficient, silent on no_data."""

    def test_no_data_renders_empty(self) -> None:
        cmp = compare_model_versions([], min_samples=3)
        assert render_model_version_comparison_line(cmp) == ""

    def test_improved_render_contains_versions_winrate_and_delta(self) -> None:
        records = [_rec("aaa1111aaaa", -0.10, "2026010%d" % d) for d in range(1, 5)] + [_rec("bbb2222bbbb", 0.03, "2026020%d" % d) for d in range(1, 5)]
        cmp = compare_model_versions(records, min_samples=3)
        line = render_model_version_comparison_line(cmp)
        assert "aaa1111" in line  # baseline version short sha
        assert "bbb2222" in line  # candidate version short sha
        assert "改善" in line or "✓" in line  # improved verdict (Chinese label + marker)
        assert "+100pp" in line  # delta winrate rendered

    def test_insufficient_render_marks_low_sample(self) -> None:
        records = [_rec("aaa1111aaaa", 0.03, "2026010%d" % d) for d in range(1, 6)] + [_rec("bbb2222bbbb", 0.03, "2026020%d" % d) for d in range(1, 3)]  # candidate n=2
        cmp = compare_model_versions(records, min_samples=5)
        line = render_model_version_comparison_line(cmp)
        assert "insufficient" in line.lower() or "不足" in line or "样本" in line
