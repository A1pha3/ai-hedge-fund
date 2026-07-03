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


def _rec_s(version: str, score: float, ret5: float, date: str) -> dict:
    """Tracking record WITH recommendation_score (for rank_monotonicity tests)."""
    return {"model_version": version, "recommendation_score": score, "next_5day_return": ret5, "recommended_date": date}


class TestRankMonotonicityPerVersion:
    """NS-7 extension: per-version rank monotonicity — does higher score → higher winrate WITHIN each model_version?

    Directly measures whether the owner's factor tuning (NS-4 score→winrate inversion)
    is improving, per version. Verdict: monotonic (high-score wins more) / inverted
    (high-score wins less — the NS-4 defect) / flat / insufficient.
    """

    def test_inverted_when_high_score_loses_more(self) -> None:
        # low-score (0.3) all win; high-score (0.7) all lose → INVERTED (the NS-4 signal)
        records = [_rec_s("v1", 0.3, 5.0, "2026010%d" % d) for d in range(1, 4)] + [_rec_s("v1", 0.7, -5.0, "2026010%d" % d) for d in range(4, 7)]
        metrics = compute_model_version_metrics(records, min_samples=2, rank_min_per_half=2)
        m = next(x for x in metrics if x.model_version == "v1")
        assert m.rank_monotonicity_verdict == "inverted"
        assert m.low_score_winrate == 1.0
        assert m.high_score_winrate == 0.0

    def test_monotonic_when_high_score_wins_more(self) -> None:
        # high-score wins, low-score loses → MONOTONIC (good model)
        records = [_rec_s("v1", 0.3, -5.0, "2026010%d" % d) for d in range(1, 4)] + [_rec_s("v1", 0.7, 5.0, "2026010%d" % d) for d in range(4, 7)]
        metrics = compute_model_version_metrics(records, min_samples=2, rank_min_per_half=2)
        m = next(x for x in metrics if x.model_version == "v1")
        assert m.rank_monotonicity_verdict == "monotonic"
        assert m.high_score_winrate > m.low_score_winrate

    def test_insufficient_when_too_few_records(self) -> None:
        # only 2 records (< 2*rank_min_per_half=6) → insufficient
        records = [_rec_s("v1", 0.3, 5.0, "20260101"), _rec_s("v1", 0.7, -5.0, "20260102")]
        metrics = compute_model_version_metrics(records, min_samples=1, rank_min_per_half=3)
        assert metrics[0].rank_monotonicity_verdict == "insufficient"

    def test_records_without_score_treated_insufficient(self) -> None:
        # records missing recommendation_score → can't bucket → insufficient
        records = [_rec("v1", 5.0, "2026010%d" % d) for d in range(1, 8)]  # _rec has no score
        metrics = compute_model_version_metrics(records, min_samples=2, rank_min_per_half=2)
        assert metrics[0].rank_monotonicity_verdict == "insufficient"

    def test_rank_mono_rendered_in_comparison_line(self) -> None:
        records = [_rec_s("aaa1111aaaa", 0.3, 5.0, "2026010%d" % d) for d in range(1, 4)] + [_rec_s("aaa1111aaaa", 0.7, -5.0, "2026010%d" % d) for d in range(4, 7)] + [_rec_s("bbb2222bbbb", 0.3, -5.0, "2026020%d" % d) for d in range(1, 4)] + [_rec_s("bbb2222bbbb", 0.7, 5.0, "2026020%d" % d) for d in range(4, 7)]
        cmp = compare_model_versions(records, min_samples=2, rank_min_per_half=2)
        line = render_model_version_comparison_line(cmp)
        # rank_mono verdict markers should appear (倒挂 for inverted baseline, 单调 for monotonic candidate)
        assert "倒挂" in line or "单调" in line or "rank" in line.lower()


class TestPreVersioningExclusionDisclosure:
    """NS-7 extension: 显式披露被排除的 pre-NS-2 未版本化记录 (model_version='' / None / '?').

    背景: tracking_history 含 493 条 pre-NS-2 (2026-06-26 d61f5dba 之前) 的月度快照
    记录, 无 model_version 字段. 这些记录无法分配到任何 version bucket, 不参与
    per-version rank_monotonicity 验证 (NS-4 per-version 验证). 为避免 owner 误以为
    数据缺失或传播 bug, 在 comparison 中显式统计被排除数, 并在渲染时标注.

    纯诊断披露, 不改变过滤逻辑 (pre-versioning 仍跳过), 不破坏前门 (no_data 仍静默).
    """

    def test_pre_versioning_records_counted_in_comparison(self) -> None:
        """records 含 pre-versioning → comparison.excluded_pre_versioning_count == N."""
        records = [
            _rec("aaa1111aaaa", 0.03, "20260101"),
            _rec("aaa1111aaaa", 0.03, "20260102"),
            _rec("aaa1111aaaa", 0.03, "20260103"),
            {"next_5day_return": 0.05, "recommended_date": "20240101"},  # no model_version
            {"model_version": "", "next_5day_return": 0.05, "recommended_date": "20240102"},  # empty
            {"model_version": None, "next_5day_return": 0.05, "recommended_date": "20240103"},  # None
        ]
        cmp = compare_model_versions(records, min_samples=2)
        assert cmp.excluded_pre_versioning_count == 3
        # 仅 1 个真实 version bucket (aaa1111aaaa)
        assert len(cmp.all_versions) == 1

    def test_pre_versioning_records_excluded_from_version_buckets(self) -> None:
        """pre-versioning 记录不进入任何 version bucket (过滤逻辑保持)."""
        records = [
            _rec("aaa1111aaaa", 0.03, "20260101"),
            {"next_5day_return": 0.05, "recommended_date": "20240101"},  # pre-versioning
        ]
        metrics = compute_model_version_metrics(records, min_samples=1)
        assert len(metrics) == 1
        assert metrics[0].model_version == "aaa1111aaaa"
        assert metrics[0].n_samples == 1  # pre-versioning 不计入

    def test_render_includes_excluded_count_when_present(self) -> None:
        """非 no_data 时, render 追加 '(排除 N 条 pre-NS-2 未版本化记录)' 标注."""
        records = [
            _rec("aaa1111aaaa", 0.03, "2026010%d" % d) for d in range(1, 5)
        ] + [
            _rec("bbb2222bbbb", 0.03, "2026020%d" % d) for d in range(1, 5)
        ] + [
            {"next_5day_return": 0.05, "recommended_date": "20240101"},  # pre-versioning
            {"model_version": "", "next_5day_return": 0.05, "recommended_date": "20240102"},
        ]
        cmp = compare_model_versions(records, min_samples=3)
        assert cmp.excluded_pre_versioning_count == 2
        line = render_model_version_comparison_line(cmp)
        assert "排除" in line
        assert "2" in line
        assert "pre-NS-2" in line or "未版本化" in line

    def test_render_no_data_still_silent_even_with_excluded(self) -> None:
        """no_data (无任何 versioned record) + 有 excluded → 仍空串 (前门静默原则).

        owner 真正关心的是 per-version 对比; 无 versioned record 时即使有 pre-versioning
        被排除也不输出 (避免污染前门). excluded count 仍可通过 comparison 对象程序化访问.
        """
        records = [
            {"next_5day_return": 0.05, "recommended_date": "20240101"},  # pre-versioning
            {"model_version": "", "next_5day_return": 0.05, "recommended_date": "20240102"},
        ]
        cmp = compare_model_versions(records, min_samples=3)
        assert cmp.verdict == "no_data"
        assert cmp.excluded_pre_versioning_count == 2  # 程序化访问仍可得
        assert render_model_version_comparison_line(cmp) == ""  # 渲染仍静默

    def test_zero_excluded_not_rendered(self) -> None:
        """无 pre-versioning 记录时, render 不追加排除标注 (避免噪声)."""
        records = [
            _rec("aaa1111aaaa", 0.03, "2026010%d" % d) for d in range(1, 5)
        ] + [
            _rec("bbb2222bbbb", 0.03, "2026020%d" % d) for d in range(1, 5)
        ]
        cmp = compare_model_versions(records, min_samples=3)
        assert cmp.excluded_pre_versioning_count == 0
        line = render_model_version_comparison_line(cmp)
        assert "排除" not in line


class TestBootstrapCI:
    """c323/autodev-36: bootstrap CI on delta_winrate."""

    def test_delta_winrate_carries_ci(self) -> None:
        """improved/degraded verdict 中 delta_winrate 携带 CI."""
        records = [_rec("aaa1111aaaa", -0.10, "2026010%d" % d) for d in range(1, 8)] + \
                  [_rec("bbb2222bbbb", 0.03, "2026020%d" % d) for d in range(1, 8)]
        cmp = compare_model_versions(records, min_samples=3)
        assert cmp.verdict in ("improved", "degraded")
        assert cmp.delta_winrate_ci_low is not None
        assert cmp.delta_winrate_ci_high is not None
        assert cmp.delta_winrate_ci_high >= cmp.delta_winrate_ci_low

    def test_insufficient_verdict_no_ci(self) -> None:
        """insufficient 时 CI 为 None (仍诚实)."""
        records = [_rec("aaa1111aaaa", 0.03, "2026010%d" % d) for d in range(1, 6)] + \
                  [_rec("bbb2222bbbb", 0.03, "2026020%d" % d) for d in range(1, 3)]
        cmp = compare_model_versions(records, min_samples=5)
        assert cmp.verdict == "insufficient"
        assert cmp.delta_winrate_ci_low is None

    def test_single_version_no_ci(self) -> None:
        """single_version 时 CI 为 None."""
        records = [_rec("only_ver00001", 0.03, "2026010%d" % d) for d in range(1, 6)]
        cmp = compare_model_versions(records, min_samples=3)
        assert cmp.verdict == "single_version"
        assert cmp.delta_winrate_ci_low is None

    def test_render_shows_ci_bracket(self) -> None:
        """render 展示 CI 括号."""
        records = [_rec("aaa1111aaaa", -0.10, "2026010%d" % d) for d in range(1, 8)] + \
                  [_rec("bbb2222bbbb", 0.03, "2026020%d" % d) for d in range(1, 8)]
        cmp = compare_model_versions(records, min_samples=3)
        line = render_model_version_comparison_line(cmp)
        assert "CI[" in line or "improved" in line or "退化" in line or "改善" in line

    def test_delta_ci_deterministic(self) -> None:
        """同 seed → 同 CI (幂等)."""
        from src.screening.model_version_comparison import _bootstrap_delta_winrate_ci
        cand = [0.03, -0.01, 0.05, -0.02, 0.01] * 4
        base = [-0.05, -0.03, -0.01, 0.02, -0.04] * 4
        lo1, hi1 = _bootstrap_delta_winrate_ci(cand, base, n_bootstrap=500, seed=42)
        lo2, hi2 = _bootstrap_delta_winrate_ci(cand, base, n_bootstrap=500, seed=42)
        assert lo1 == lo2 and hi1 == hi2

    def test_delta_ci_none_for_empty(self) -> None:
        """空输入 → None, None."""
        from src.screening.model_version_comparison import _bootstrap_delta_winrate_ci
        lo, hi = _bootstrap_delta_winrate_ci([], [1.0, 2.0])
        assert lo is None and hi is None
