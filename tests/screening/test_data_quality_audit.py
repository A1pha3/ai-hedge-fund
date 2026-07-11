"""测试 src.screening.data_quality_audit (P0-10)。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.screening.data_quality_audit import (
    audit_recommendation,
    audit_recommendations,
    compute_composite_completeness,
    DEFAULT_QUALITY_THRESHOLD,
    load_latest_recommendations,
    render_audit_report,
    render_data_quality_summary,
    STRATEGY_ORDER,
    summarize_data_quality,
)


def _make_rec(ticker: str, completeness: dict[str, float], score_b: float = 0.7, name: str = "测试") -> dict:
    """构造测试 recommendation dict。"""
    return {
        "ticker": ticker,
        "name": name,
        "industry_sw": "电子",
        "score_b": score_b,
        "strategy_signals": {s: {"direction": 1, "confidence": 80.0, "completeness": completeness.get(s, 0.0), "sub_factors": {}} for s in STRATEGY_ORDER},
        "metrics": {},
    }


# ---------------------------------------------------------------------------
# compute_composite_completeness
# ---------------------------------------------------------------------------


def test_compute_composite_completeness_all_full():
    sigs = {s: {"completeness": 1.0} for s in STRATEGY_ORDER}
    assert compute_composite_completeness(sigs) == 1.0


def test_compute_composite_completeness_all_zero():
    """关键回归: R20.17 修复的 bug — 0.0 不能被静默覆盖为 1.0。"""
    sigs = {s: {"completeness": 0.0} for s in STRATEGY_ORDER}
    assert compute_composite_completeness(sigs) == 0.0


def test_compute_composite_completeness_mixed():
    sigs = {
        "trend": {"completeness": 1.0},
        "mean_reversion": {"completeness": 0.5},
        "fundamental": {"completeness": 0.8},
        "event_sentiment": {"completeness": 0.0},
    }
    # 权重: trend 0.30 + mean_reversion 0.20 + fundamental 0.30 + event_sentiment 0.20 = 1.0
    # 加权: 0.30*1.0 + 0.20*0.5 + 0.30*0.8 + 0.20*0.0 = 0.30 + 0.10 + 0.24 + 0.0 = 0.64
    assert compute_composite_completeness(sigs) == pytest.approx(0.64, abs=1e-4)


def test_compute_composite_completeness_missing_strategy_uses_zero():
    """缺失策略应视为 completeness=0.0 (不静默覆盖)。"""
    sigs = {"trend": {"completeness": 1.0}}  # 其他三个缺失
    # 全部权重 1.0, 仅 trend 有值: 0.30 * 1.0 / 1.0 = 0.30
    assert compute_composite_completeness(sigs) == pytest.approx(0.30, abs=1e-4)


def test_compute_composite_completeness_none_value():
    """completeness=None 应视为 0.0 (区分"未传"与"传了 0.0")。"""
    sigs = {s: {"completeness": None} for s in STRATEGY_ORDER}
    assert compute_composite_completeness(sigs) == 0.0


# ---------------------------------------------------------------------------
# audit_recommendation
# ---------------------------------------------------------------------------


def test_audit_recommendation_high_quality():
    rec = _make_rec("000001", {s: 0.9 for s in STRATEGY_ORDER})
    result = audit_recommendation(rec)
    assert result["ticker"] == "000001"
    assert result["composite_completeness"] == pytest.approx(0.9, abs=1e-4)
    assert result["weak_strategies"] == []
    assert result["is_low_quality"] is False


def test_audit_recommendation_low_quality_one_weak():
    """一个策略 completeness 低于阈值, 但综合可能仍 OK。"""
    rec = _make_rec(
        "000002",
        {"trend": 0.9, "mean_reversion": 0.9, "fundamental": 0.9, "event_sentiment": 0.2},
    )
    result = audit_recommendation(rec, threshold=0.6)
    assert result["weak_strategies"] == ["event_sentiment"]
    # 综合: 0.30*0.9 + 0.20*0.9 + 0.30*0.9 + 0.20*0.2 = 0.27 + 0.18 + 0.27 + 0.04 = 0.76
    assert result["composite_completeness"] == pytest.approx(0.76, abs=1e-4)
    assert result["is_low_quality"] is False  # 综合仍 > 0.6


def test_audit_recommendation_all_weak_is_low_quality():
    rec = _make_rec("000003", {s: 0.3 for s in STRATEGY_ORDER})
    result = audit_recommendation(rec, threshold=0.6)
    assert set(result["weak_strategies"]) == set(STRATEGY_ORDER)
    assert result["composite_completeness"] == pytest.approx(0.3, abs=1e-4)
    assert result["is_low_quality"] is True


def test_audit_recommendation_threshold_boundary():
    """阈值边界: completeness == threshold 不算低质量 (用 < 而非 <=)。"""
    rec = _make_rec("000004", {s: 0.6 for s in STRATEGY_ORDER})
    result = audit_recommendation(rec, threshold=0.6)
    assert result["composite_completeness"] == pytest.approx(0.6, abs=1e-4)
    assert result["is_low_quality"] is False  # 0.6 < 0.6 为 False
    assert result["weak_strategies"] == []  # 0.6 < 0.6 为 False


def test_audit_recommendation_missing_strategy_signals():
    """无 strategy_signals 应综合=0.0, 低质量。"""
    rec = {"ticker": "000005", "name": "测试", "score_b": 0.7}
    result = audit_recommendation(rec, threshold=0.6)
    assert result["composite_completeness"] == 0.0
    assert result["is_low_quality"] is True


# ---------------------------------------------------------------------------
# audit_recommendations
# ---------------------------------------------------------------------------


def test_audit_recommendations_top_n_limit():
    recs = [_make_rec(f"{i:06d}", {s: 0.9 for s in STRATEGY_ORDER}) for i in range(5)]
    results = audit_recommendations(recs, top_n=3)
    assert len(results) == 3


def test_audit_recommendations_sorted_by_composite_ascending():
    """审计结果应按 composite_completeness 升序 (低质量在前, 便于优先审视)。"""
    recs = [
        _make_rec("000001", {s: 0.9 for s in STRATEGY_ORDER}),  # 高
        _make_rec("000002", {s: 0.3 for s in STRATEGY_ORDER}),  # 低
        _make_rec("000003", {s: 0.6 for s in STRATEGY_ORDER}),  # 中
    ]
    results = audit_recommendations(recs)
    assert results[0]["ticker"] == "000002"  # 最低在前
    assert results[1]["ticker"] == "000003"
    assert results[2]["ticker"] == "000001"


# ---------------------------------------------------------------------------
# load_latest_recommendations
# ---------------------------------------------------------------------------


def test_load_latest_recommendations_from_tmp(tmp_path: Path):
    """在 tmp 目录写入测试报告并验证加载。"""
    reports_dir = tmp_path / "data" / "reports"
    reports_dir.mkdir(parents=True)
    payload = {
        "mode": "auto",
        "date": "20260609",
        "recommendations": [
            _make_rec("000001", {s: 0.8 for s in STRATEGY_ORDER}),
        ],
    }
    (reports_dir / "auto_screening_20260609.json").write_text(json.dumps(payload), encoding="utf-8")

    date_str, recs = load_latest_recommendations(report_dir=reports_dir)
    assert date_str == "20260609"
    assert len(recs) == 1
    assert recs[0]["ticker"] == "000001"


def test_load_latest_recommendations_empty_dir(tmp_path: Path):
    """空目录应返回 ('', [])。"""
    empty = tmp_path / "empty_reports"
    empty.mkdir()
    date_str, recs = load_latest_recommendations(report_dir=empty)
    assert date_str == ""
    assert recs == []


def test_find_latest_report_skips_malformed_filename(tmp_path: Path):
    """R54 同族: _find_latest_report 校验文件名日期，跳过 malformed 文件。

    背景: 纯字母排序会把非数字开头的 malformed 文件名（如
    ``auto_screening_garbage.json``，字母在 ASCII 数字之后）排到合法日期之前，
    误选为"最新"。校验 stem 能解析为 ``%Y%m%d`` 后再排序，对齐 R54 的
    ``_load_auto_screening_reports`` 文件名校验。
    """
    from src.screening.data_quality_audit import _find_latest_report

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    # 一个合法日期报告
    (reports_dir / "auto_screening_20260609.json").write_text("{}", encoding="utf-8")
    # 一个 malformed 文件名（字母开头会被排到数字之前）
    (reports_dir / "auto_screening_garbage.json").write_text("{}", encoding="utf-8")

    latest = _find_latest_report(report_dir=reports_dir)

    # 必须选合法日期文件，而非 malformed（garbage 字母排序在数字之前）
    assert latest is not None
    assert latest.name == "auto_screening_20260609.json"


def test_load_latest_recommendations_picks_most_recent(tmp_path: Path):
    """多个报告时应选最新 (按文件名倒序)。"""
    reports_dir = tmp_path / "data" / "reports"
    reports_dir.mkdir(parents=True)
    for date in ("20260607", "20260608", "20260609"):
        payload = {"mode": "auto", "date": date, "recommendations": []}
        (reports_dir / f"auto_screening_{date}.json").write_text(json.dumps(payload), encoding="utf-8")

    date_str, _ = load_latest_recommendations(report_dir=reports_dir)
    assert date_str == "20260609"


def test_find_latest_report_skips_weekend_report(tmp_path: Path):
    """R89 cross-surface: 跳过周末伪交易日报告，选最近的开市日报告。

    背景: pre-fix legacy 或未来 regression 可能留下周六/周日日期的报告（如
    ``auto_screening_20260711.json``，07-11 是周六）。文件名排序 0711 > 0710，
    但 ``--daily-action`` 把信号日归一到 20260710（周五）。本 finder 被 top_picks
    / run_top / daily-action fallback / DQ block 共用，必须跳过周末报告以保持跨
    surface 一致，否则 operator 在 ``--daily-brief`` 看到周六决策卡，与
    ``--daily-action`` 的周五信号矛盾（2026-07-12 实跑发现）。
    """
    from src.screening.data_quality_audit import _find_latest_report

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    # 周五（开市日）+ 周六（伪交易日，文件名更新 → 排序更靠前）
    (reports_dir / "auto_screening_20260710.json").write_text("{}", encoding="utf-8")  # Fri
    (reports_dir / "auto_screening_20260711.json").write_text("{}", encoding="utf-8")  # Sat

    latest = _find_latest_report(report_dir=reports_dir)

    assert latest is not None
    # 必须选周五（开市日），跳过文件名更新的周六伪交易日报告
    assert latest.name == "auto_screening_20260710.json"


def test_find_latest_report_all_weekend_falls_back_to_newest(tmp_path: Path):
    """降级: 全部报告都是周末时，返回最新（不返回 None，让上层 stale 披露处理）。"""
    from src.screening.data_quality_audit import _find_latest_report

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    # 周六 + 周日（无任一开市日报告 → 无法优选，降级返回最新）
    (reports_dir / "auto_screening_20260711.json").write_text("{}", encoding="utf-8")  # Sat
    (reports_dir / "auto_screening_20260712.json").write_text("{}", encoding="utf-8")  # Sun

    latest = _find_latest_report(report_dir=reports_dir)

    assert latest is not None  # 降级返回，不 None
    assert latest.name == "auto_screening_20260712.json"  # 最新


# ---------------------------------------------------------------------------
# render_audit_report
# ---------------------------------------------------------------------------


def test_render_audit_report_empty_list():
    out = render_audit_report([], date_str="20260609")
    assert "未找到推荐数据" in out


def test_render_audit_report_has_summary():
    audits = [
        audit_recommendation(_make_rec("000001", {s: 0.9 for s in STRATEGY_ORDER})),
        audit_recommendation(_make_rec("000002", {s: 0.3 for s in STRATEGY_ORDER})),
    ]
    out = render_audit_report(audits, date_str="20260609")
    assert "数据质量审计" in out
    assert "摘要" in out
    assert "低质量 1 只" in out
    assert "000002" in out  # 低质量在提示中


def test_render_audit_report_threshold_default():
    """默认阈值 0.6 应生效。"""
    audits = [
        audit_recommendation(_make_rec("000001", {s: 0.55 for s in STRATEGY_ORDER})),
    ]
    out = render_audit_report(audits, date_str="20260609", threshold=DEFAULT_QUALITY_THRESHOLD)
    assert "⚠️ 低质量" in out


# ---------------------------------------------------------------------------
# _strategy_completeness / _completeness_bar
# ---------------------------------------------------------------------------


class TestStrategyCompleteness:
    """Safe completeness reader — 0.0 for missing/None (R20.17 bug-pattern guard)."""

    def test_present_value(self):
        from src.screening.data_quality_audit import _strategy_completeness

        signals = {"trend": {"completeness": 0.85}}
        assert _strategy_completeness(signals, "trend") == 0.85

    def test_missing_strategy_returns_zero(self):
        from src.screening.data_quality_audit import _strategy_completeness

        assert _strategy_completeness({}, "trend") == 0.0
        assert _strategy_completeness({"fundamental": {"completeness": 0.9}}, "trend") == 0.0

    def test_none_value_returns_zero(self):
        from src.screening.data_quality_audit import _strategy_completeness

        signals = {"trend": {"completeness": None}}
        assert _strategy_completeness(signals, "trend") == 0.0

    def test_empty_block_returns_zero(self):
        from src.screening.data_quality_audit import _strategy_completeness

        signals = {"trend": {}}
        assert _strategy_completeness(signals, "trend") == 0.0

    def test_zero_value_preserved_not_overridden(self):
        """R20.17 guard: 0.0 is valid 'no data', not silently overridden."""
        from src.screening.data_quality_audit import _strategy_completeness

        signals = {"trend": {"completeness": 0.0}}
        assert _strategy_completeness(signals, "trend") == 0.0

    def test_int_value_coerced_to_float(self):
        from src.screening.data_quality_audit import _strategy_completeness

        signals = {"trend": {"completeness": 1}}
        result = _strategy_completeness(signals, "trend")
        assert result == 1.0
        assert isinstance(result, float)


class TestCompletenessBar:
    """ASCII progress bar with three-state color coding."""

    def test_full_bar(self):
        from src.screening.data_quality_audit import _completeness_bar

        out = _completeness_bar(1.0)
        assert out.count("█") == 10
        assert "░" not in out

    def test_empty_bar(self):
        from src.screening.data_quality_audit import _completeness_bar

        out = _completeness_bar(0.0)
        assert out.count("░") == 10
        assert "█" not in out

    def test_half_bar(self):
        from src.screening.data_quality_audit import _completeness_bar

        out = _completeness_bar(0.5)
        assert out.count("█") == 5
        assert out.count("░") == 5

    def test_custom_width(self):
        from src.screening.data_quality_audit import _completeness_bar

        out = _completeness_bar(0.5, width=20)
        assert out.count("█") == 10
        assert out.count("░") == 10

    def test_clamps_above_one(self):
        from src.screening.data_quality_audit import _completeness_bar

        out = _completeness_bar(1.5)
        assert out.count("█") == 10

    def test_clamps_below_zero(self):
        from src.screening.data_quality_audit import _completeness_bar

        out = _completeness_bar(-0.5)
        assert out.count("░") == 10


# ---------------------------------------------------------------------------
# R-2 数据完整度门控 — summarize_data_quality / render_data_quality_summary
# ---------------------------------------------------------------------------


class TestSummarizeDataQuality:
    """R-2: 从 audit_recommendations 产出聚合数据完整度摘要。"""

    def test_empty_recommendations_returns_no_data(self) -> None:
        """空推荐列表 → 没有可摘要的数据。"""
        s = summarize_data_quality([])
        assert s.has_data is False

    def test_single_full_completeness(self) -> None:
        """单只票全部策略完整 → avg 完整度 = 那只票的 composite。"""
        rec = _make_rec("000001", {s: 1.0 for s in STRATEGY_ORDER})
        audits = audit_recommendations([rec])
        s = summarize_data_quality(audits)
        assert s.has_data is True
        assert s.pick_count == 1
        assert s.avg_completeness == pytest.approx(1.0)
        assert s.low_quality_count == 0
        # all 4 strategies ready → ready count == len(STRATEGY_ORDER)
        assert s.strategy_ready_count == len(STRATEGY_ORDER)

    def test_mixed_completeness_avg_and_low_count(self) -> None:
        """多只票: avg 取平均, low_quality_count 计 composite < threshold。"""
        full = _make_rec("000001", {s: 1.0 for s in STRATEGY_ORDER})
        half = _make_rec("000002", {s: 0.5 for s in STRATEGY_ORDER})  # 0.5 < 0.6 → low
        audits = audit_recommendations([full, half])
        s = summarize_data_quality(audits)
        assert s.pick_count == 2
        assert s.avg_completeness == pytest.approx(0.75)
        assert s.low_quality_count == 1

    def test_strategy_ready_counts_above_threshold(self) -> None:
        """一个策略在所有 picks 都完整 → 计入 ready; 一个都不完整 → 不计入。"""
        # trend=1.0 everywhere, fundamental=0.0 everywhere
        comps = {s: 0.0 for s in STRATEGY_ORDER}
        comps["trend"] = 1.0
        rec = _make_rec("000001", comps)
        audits = audit_recommendations([rec])
        s = summarize_data_quality(audits)
        # trend ready, the rest not
        assert s.strategy_ready_count == 1


class TestRenderDataQualitySummary:
    """R-2: 渲染单行数据完整度摘要 (空数据 → 空串)。"""

    def test_no_data_returns_empty_string(self) -> None:
        """无可摘要数据 → 空串 (前门不展示, 诚实)。"""
        s = summarize_data_quality([])
        assert render_data_quality_summary(s) == ""

    def test_full_completeness_renders_green(self) -> None:
        """全部完整 → 单行含百分比 + 就绪数 + 绿色。"""
        rec = _make_rec("000001", {s: 1.0 for s in STRATEGY_ORDER})
        audits = audit_recommendations([rec])
        line = render_data_quality_summary(summarize_data_quality(audits))
        assert line != ""
        assert "数据完整度" in line
        assert "100%" in line
        assert "4/4" in line or f"{len(STRATEGY_ORDER)}/{len(STRATEGY_ORDER)}" in line
        from src.utils.display import Fore

        assert Fore.GREEN in line

    def test_partial_completeness_renders_warning_and_low_count(self) -> None:
        """有低质量 pick → 含 ⚠ + 低质量计数。"""
        full = _make_rec("000001", {s: 1.0 for s in STRATEGY_ORDER})
        low = _make_rec("000002", {s: 0.3 for s in STRATEGY_ORDER})
        audits = audit_recommendations([full, low])
        line = render_data_quality_summary(summarize_data_quality(audits))
        assert "数据完整度" in line
        # one low-quality pick surfaced
        assert "1" in line  # low_quality_count == 1
        from src.utils.display import Fore

        assert Fore.YELLOW in line or Fore.RED in line

    def test_stamps_data_as_of_when_present(self) -> None:
        """loop 83 (asymmetric-staleness drain): the data-quality footer reads
        the latest auto_screening_*.json (stale-prone) but renders no 数据时点
        stamp while 10 sibling footer blocks do. The date IS loaded by
        load_latest_recommendations but discarded at the call site. A stale
        '100% complete' green would falsely reassure the operator that today's
        picks rest on complete data when the underlying report is days old.
        """
        rec = _make_rec("000001", {s: 1.0 for s in STRATEGY_ORDER})
        audits = audit_recommendations([rec])
        s = summarize_data_quality(audits)
        s.latest_report_date = "20260630"
        line = render_data_quality_summary(s)
        assert "数据完整度" in line
        assert "数据时点 2026-06-30" in line, (
            f"data-quality footer must stamp 数据时点 when latest_report_date is set, got: {line!r}"
        )

    def test_omits_stamp_when_no_data_as_of(self) -> None:
        """No latest_report_date → no stamp (don't fabricate)."""
        rec = _make_rec("000001", {s: 1.0 for s in STRATEGY_ORDER})
        audits = audit_recommendations([rec])
        line = render_data_quality_summary(summarize_data_quality(audits))
        assert "数据完整度" in line
        assert "数据时点" not in line
