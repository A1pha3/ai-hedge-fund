"""P0-3 信号衰减检测器 — 单元测试"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from src.screening.signal_decay_detector import (
    _classify_decay,
    _coerce_score_b,
    _compute_change_pct,
    build_decay_summary,
    DecayInfo,
    DecayLevel,
    detect_signal_decay,
)

# ============================================================================
# Helpers
# ============================================================================


def _write_auto_report(
    report_dir: Path,
    date_str: str,
    recommendations: list[dict] | None = None,
    tickers: list[str] | None = None,
    score_b: float = 0.5,
) -> Path:
    """写入一个最小可用的 auto_screening_{date}.json 文件。"""
    report_dir.mkdir(parents=True, exist_ok=True)
    if recommendations is None:
        recommendations = [
            {"ticker": t, "score_b": score_b, "decision": "watch"}
            for t in (tickers or [])
        ]
    payload = {
        "mode": "auto_screening",
        "date": date_str,
        "recommendations": recommendations,
    }
    out = report_dir / f"auto_screening_{date_str}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return out


# ============================================================================
# 1. 首次出现标的 -> DecayLevel.NONE
# ============================================================================


def test_first_appearance_is_none(tmp_path: Path) -> None:
    """首次出现的标的（无历史数据）应为 DecayLevel.NONE。"""
    # 只写当天报告，不写历史
    recs = [{"ticker": "000001", "score_b": 0.5}]
    _write_auto_report(tmp_path, "20260607", recommendations=recs)

    current = [{"ticker": "000001", "score_b": 0.5}]
    result = detect_signal_decay(current, tmp_path, lookback_days=3, end_date="20260607")

    info = result["000001"]
    assert info.level == DecayLevel.NONE
    assert info.previous_score is None
    assert info.change_pct is None
    assert info.current_score == 0.5


# ============================================================================
# 2. score_b 下降 5% -> NONE
# ============================================================================


def test_small_drop_5pct_is_none(tmp_path: Path) -> None:
    """score_b 下降 5% (< 10%) 应为 NONE。"""
    _write_auto_report(tmp_path, "20260606", tickers=["000001"], score_b=1.0)
    # 当天：score_b = 0.95, drop 5%
    _write_auto_report(tmp_path, "20260607", tickers=["000001"], score_b=0.5)

    current = [{"ticker": "000001", "score_b": 0.95}]
    result = detect_signal_decay(current, tmp_path, lookback_days=3, end_date="20260607")

    info = result["000001"]
    assert info.level == DecayLevel.NONE
    assert info.change_pct == pytest.approx(-5.0, abs=0.1)


# ============================================================================
# 3. score_b 下降 15% -> MILD
# ============================================================================


def test_drop_15pct_is_mild(tmp_path: Path) -> None:
    """score_b 下降 15% 应为 MILD。"""
    _write_auto_report(tmp_path, "20260606", tickers=["000001"], score_b=1.0)
    _write_auto_report(tmp_path, "20260607", tickers=["000001"], score_b=0.5)

    current = [{"ticker": "000001", "score_b": 0.85}]  # drop 15%
    result = detect_signal_decay(current, tmp_path, lookback_days=3, end_date="20260607")

    info = result["000001"]
    assert info.level == DecayLevel.MILD
    assert info.change_pct == pytest.approx(-15.0, abs=0.1)


# ============================================================================
# 4. score_b 下降 25% -> MODERATE
# ============================================================================


def test_drop_25pct_is_moderate(tmp_path: Path) -> None:
    """score_b 下降 25% 应为 MODERATE。"""
    _write_auto_report(tmp_path, "20260606", tickers=["000001"], score_b=1.0)
    _write_auto_report(tmp_path, "20260607", tickers=["000001"], score_b=0.5)

    current = [{"ticker": "000001", "score_b": 0.75}]  # drop 25%
    result = detect_signal_decay(current, tmp_path, lookback_days=3, end_date="20260607")

    info = result["000001"]
    assert info.level == DecayLevel.MODERATE
    assert info.change_pct == pytest.approx(-25.0, abs=0.1)


# ============================================================================
# 5. score_b 下降 50% -> SEVERE
# ============================================================================


def test_drop_50pct_is_severe(tmp_path: Path) -> None:
    """score_b 下降 50% 应为 SEVERE。"""
    _write_auto_report(tmp_path, "20260606", tickers=["000001"], score_b=1.0)
    _write_auto_report(tmp_path, "20260607", tickers=["000001"], score_b=0.5)

    current = [{"ticker": "000001", "score_b": 0.50}]  # drop 50%
    result = detect_signal_decay(current, tmp_path, lookback_days=3, end_date="20260607")

    info = result["000001"]
    assert info.level == DecayLevel.SEVERE
    assert info.change_pct == pytest.approx(-50.0, abs=0.1)


# ============================================================================
# 6. score_b 上升 -> NONE
# ============================================================================


def test_score_increase_is_none(tmp_path: Path) -> None:
    """score_b 上升时应为 NONE (信号增强)。"""
    _write_auto_report(tmp_path, "20260606", tickers=["000001"], score_b=0.5)
    _write_auto_report(tmp_path, "20260607", tickers=["000001"], score_b=0.5)

    current = [{"ticker": "000001", "score_b": 0.8}]  # increase 60%
    result = detect_signal_decay(current, tmp_path, lookback_days=3, end_date="20260607")

    info = result["000001"]
    assert info.level == DecayLevel.NONE
    assert info.change_pct == pytest.approx(60.0, abs=0.1)


# ============================================================================
# 7. previous_score = 0 -> NONE (不除零)
# ============================================================================


def test_previous_score_zero_is_none(tmp_path: Path) -> None:
    """previous_score 为 0 时不计算 change_pct，标记 NONE。"""
    _write_auto_report(tmp_path, "20260606", tickers=["000001"], score_b=0.0)
    _write_auto_report(tmp_path, "20260607", tickers=["000001"], score_b=0.0)

    current = [{"ticker": "000001", "score_b": 0.5}]
    result = detect_signal_decay(current, tmp_path, lookback_days=3, end_date="20260607")

    info = result["000001"]
    assert info.level == DecayLevel.NONE
    assert info.previous_score == 0.0
    assert info.change_pct is None  # 不除零


# ============================================================================
# 8. 空历史 -> 所有标的 NONE
# ============================================================================


def test_empty_history_all_none(tmp_path: Path) -> None:
    """空历史目录下所有标的应为 NONE。"""
    current = [
        {"ticker": "000001", "score_b": 0.5},
        {"ticker": "000002", "score_b": 0.8},
    ]
    result = detect_signal_decay(current, tmp_path, lookback_days=3, end_date="20260607")

    assert len(result) == 2
    for info in result.values():
        assert info.level == DecayLevel.NONE
        assert info.previous_score is None
        assert info.change_pct is None


# ============================================================================
# 9. 损坏 JSON -> 优雅降级
# ============================================================================


def test_corrupted_json_graceful_degradation(tmp_path: Path) -> None:
    """损坏的 JSON 应被跳过，不影响其他有效报告。"""
    _write_auto_report(tmp_path, "20260605", tickers=["000001"], score_b=0.8)
    # 写一个损坏的报告
    bad = tmp_path / "auto_screening_20260606.json"
    bad.write_text("not valid json{{{", encoding="utf-8")
    _write_auto_report(tmp_path, "20260607", tickers=["000001"], score_b=0.5)

    current = [{"ticker": "000001", "score_b": 0.6}]
    # end_date = 20260608, 历史窗口 3 天 = 06-05/06/07
    result = detect_signal_decay(current, tmp_path, lookback_days=3, end_date="20260608")

    # 应使用 06-07 作为 previous (06-06 被跳过)
    info = result["000001"]
    assert info.previous_score == 0.5
    # (0.6 - 0.5) / 0.5 * 100 = 20% increase -> NONE
    assert info.level == DecayLevel.NONE


# ============================================================================
# 10. days_since_peak 计算
# ============================================================================


def test_days_since_peak_calculation(tmp_path: Path) -> None:
    """days_since_peak 应正确计算距离历史最高分的天数。"""
    # Day -2: score 0.9 (peak)
    _write_auto_report(tmp_path, "20260605", tickers=["000001"], score_b=0.9)
    # Day -1: score 0.7
    _write_auto_report(tmp_path, "20260606", tickers=["000001"], score_b=0.7)
    # Current day (no report written for 06-07 since it's end_date)
    _write_auto_report(tmp_path, "20260607", tickers=["000001"], score_b=0.5)

    current = [{"ticker": "000001", "score_b": 0.6}]  # today
    result = detect_signal_decay(current, tmp_path, lookback_days=3, end_date="20260607")

    info = result["000001"]
    # Peak was 0.9 on 06-05, today is 06-07 -> 2 days since peak
    assert info.days_since_peak == 2
    assert info.current_score == 0.6
    assert info.previous_score == 0.7


def test_days_since_peak_zero_when_today_is_peak(tmp_path: Path) -> None:
    """当前 score 为最高时 days_since_peak 应为 0。"""
    _write_auto_report(tmp_path, "20260605", tickers=["000001"], score_b=0.5)
    _write_auto_report(tmp_path, "20260606", tickers=["000001"], score_b=0.6)
    _write_auto_report(tmp_path, "20260607", tickers=["000001"], score_b=0.3)

    current = [{"ticker": "000001", "score_b": 0.9}]  # new peak today
    result = detect_signal_decay(current, tmp_path, lookback_days=3, end_date="20260607")

    info = result["000001"]
    assert info.days_since_peak == 0
    assert info.level == DecayLevel.NONE  # signal is strengthening


# ============================================================================
# Additional edge case tests
# ============================================================================


def test_boundary_mild_exactly_10pct(tmp_path: Path) -> None:
    """恰好 10% 下降应为 MILD (>=10)。"""
    _write_auto_report(tmp_path, "20260606", tickers=["000001"], score_b=1.0)
    _write_auto_report(tmp_path, "20260607", tickers=["000001"], score_b=0.5)

    current = [{"ticker": "000001", "score_b": 0.9}]  # exactly 10% drop
    result = detect_signal_decay(current, tmp_path, lookback_days=3, end_date="20260607")

    assert result["000001"].level == DecayLevel.MILD


def test_boundary_moderate_exactly_20pct(tmp_path: Path) -> None:
    """恰好 20% 下降应为 MODERATE (>=20)。"""
    _write_auto_report(tmp_path, "20260606", tickers=["000001"], score_b=1.0)
    _write_auto_report(tmp_path, "20260607", tickers=["000001"], score_b=0.5)

    current = [{"ticker": "000001", "score_b": 0.8}]  # exactly 20% drop
    result = detect_signal_decay(current, tmp_path, lookback_days=3, end_date="20260607")

    assert result["000001"].level == DecayLevel.MODERATE


def test_boundary_severe_exactly_40pct(tmp_path: Path) -> None:
    """恰好 40% 下降应为 SEVERE (>=40)。"""
    _write_auto_report(tmp_path, "20260606", tickers=["000001"], score_b=1.0)
    _write_auto_report(tmp_path, "20260607", tickers=["000001"], score_b=0.5)

    current = [{"ticker": "000001", "score_b": 0.6}]  # exactly 40% drop
    result = detect_signal_decay(current, tmp_path, lookback_days=3, end_date="20260607")

    assert result["000001"].level == DecayLevel.SEVERE


def test_negative_score_b(tmp_path: Path) -> None:
    """负 score_b 也应正确计算衰减。"""
    _write_auto_report(tmp_path, "20260606", recommendations=[{"ticker": "000001", "score_b": -0.3}])
    _write_auto_report(tmp_path, "20260607", recommendations=[{"ticker": "000001", "score_b": 0.5}])

    # current = -0.6, previous = -0.3
    # change_pct = (-0.6 - (-0.3)) / max(abs(-0.3), 0.01) * 100 = -0.3/0.3*100 = -100%
    current = [{"ticker": "000001", "score_b": -0.6}]
    result = detect_signal_decay(current, tmp_path, lookback_days=3, end_date="20260607")

    info = result["000001"]
    assert info.level == DecayLevel.SEVERE
    assert info.change_pct == pytest.approx(-100.0, abs=0.1)


def test_multiple_tickers_mixed_levels(tmp_path: Path) -> None:
    """多个标的应有各自独立的衰减等级。"""
    _write_auto_report(
        tmp_path,
        "20260606",
        recommendations=[
            {"ticker": "000001", "score_b": 1.0},
            {"ticker": "000002", "score_b": 0.8},
            {"ticker": "000003", "score_b": 0.5},
        ],
    )
    _write_auto_report(tmp_path, "20260607", recommendations=[{"ticker": "DUMMY", "score_b": 0.5}])

    current = [
        {"ticker": "000001", "score_b": 0.85},   # -15% -> MILD
        {"ticker": "000002", "score_b": 0.56},   # -30% -> MODERATE
        {"ticker": "000003", "score_b": 0.20},   # -60% -> SEVERE
        {"ticker": "NEW_TICKER", "score_b": 0.7},  # first appearance -> NONE
    ]
    result = detect_signal_decay(current, tmp_path, lookback_days=3, end_date="20260607")

    assert result["000001"].level == DecayLevel.MILD
    assert result["000002"].level == DecayLevel.MODERATE
    assert result["000003"].level == DecayLevel.SEVERE
    assert result["NEW_TICKER"].level == DecayLevel.NONE
    assert result["NEW_TICKER"].previous_score is None


# ============================================================================
# Unit tests for internal helpers
# ============================================================================


def test_compute_change_pct_basic() -> None:
    """_compute_change_pct 基本计算。"""
    assert _compute_change_pct(0.8, 1.0) == pytest.approx(-20.0)
    assert _compute_change_pct(1.2, 1.0) == pytest.approx(20.0)
    assert _compute_change_pct(0.0, 1.0) == pytest.approx(-100.0)


def test_compute_change_pct_zero_previous() -> None:
    """_compute_change_pct previous=0 时返回 None。"""
    assert _compute_change_pct(0.5, 0.0) is None


def test_compute_change_pct_tiny_previous() -> None:
    """_compute_change_pct previous 非常小时使用 max(abs(prev), 0.01)。"""
    # previous = 0.001, denominator = max(0.001, 0.01) = 0.01
    result = _compute_change_pct(0.5, 0.001)
    assert result == pytest.approx(4990.0, rel=0.01)


def test_classify_decay_boundaries() -> None:
    """_classify_decay 边界值测试。"""
    assert _classify_decay(None) == DecayLevel.NONE
    assert _classify_decay(0.0) == DecayLevel.NONE
    assert _classify_decay(10.0) == DecayLevel.NONE
    assert _classify_decay(-9.9) == DecayLevel.NONE
    assert _classify_decay(-10.0) == DecayLevel.MILD
    assert _classify_decay(-19.9) == DecayLevel.MILD
    assert _classify_decay(-20.0) == DecayLevel.MODERATE
    assert _classify_decay(-39.9) == DecayLevel.MODERATE
    assert _classify_decay(-40.0) == DecayLevel.SEVERE
    assert _classify_decay(-99.9) == DecayLevel.SEVERE


def test_coerce_score_b_variants() -> None:
    """_coerce_score_b 各种异常输入。"""
    assert _coerce_score_b(None) == 0.0
    assert _coerce_score_b("not_a_number") == 0.0
    assert _coerce_score_b(float("nan")) == 0.0
    assert _coerce_score_b(float("inf")) == 0.0
    assert _coerce_score_b(float("-inf")) == 0.0
    assert _coerce_score_b(0.5) == 0.5
    assert _coerce_score_b("0.7") == 0.7


# ============================================================================
# build_decay_summary tests
# ============================================================================


def test_build_decay_summary_counts(tmp_path: Path) -> None:
    """build_decay_summary 应正确统计各等级数量。"""
    _write_auto_report(tmp_path, "20260606", recommendations=[
        {"ticker": "A", "score_b": 1.0},
        {"ticker": "B", "score_b": 1.0},
        {"ticker": "C", "score_b": 1.0},
        {"ticker": "D", "score_b": 1.0},
    ])
    _write_auto_report(tmp_path, "20260607", recommendations=[{"ticker": "DUMMY", "score_b": 0.5}])

    current = [
        {"ticker": "A", "score_b": 0.85},   # -15% -> MILD
        {"ticker": "B", "score_b": 0.7},    # -30% -> MODERATE
        {"ticker": "C", "score_b": 0.4},    # -60% -> SEVERE
        {"ticker": "D", "score_b": 1.1},    # +10% -> NONE
    ]
    decay_map = detect_signal_decay(current, tmp_path, lookback_days=3, end_date="20260607")
    summary = build_decay_summary(decay_map)

    assert summary["none"] == 1
    assert summary["mild"] == 1
    assert summary["moderate"] == 1
    assert summary["severe"] == 1


def test_build_decay_summary_all_none() -> None:
    """全部 NONE 的汇总。"""
    summary = build_decay_summary({
        "A": DecayInfo("A", DecayLevel.NONE, 0.5, None, None, 0),
        "B": DecayInfo("B", DecayLevel.NONE, 0.3, None, None, 0),
    })
    assert summary == {"none": 2, "mild": 0, "moderate": 0, "severe": 0}


# ============================================================================
# DecayInfo.to_dict()
# ============================================================================


def test_decay_info_to_dict() -> None:
    """DecayInfo.to_dict() 应正确序列化。"""
    info = DecayInfo(
        ticker="000001",
        level=DecayLevel.MODERATE,
        current_score=0.75,
        previous_score=1.0,
        change_pct=-25.0,
        days_since_peak=2,
    )
    d = info.to_dict()
    assert d == {
        "level": "moderate",
        "current_score": 0.75,
        "previous_score": 1.0,
        "change_pct": -25.0,
        "days_since_peak": 2,
    }


def test_decay_info_to_dict_with_none_fields() -> None:
    """DecayInfo.to_dict() None 字段应正确处理。"""
    info = DecayInfo(
        ticker="000001",
        level=DecayLevel.NONE,
        current_score=0.5,
        previous_score=None,
        change_pct=None,
        days_since_peak=0,
    )
    d = info.to_dict()
    assert d["previous_score"] is None
    assert d["change_pct"] is None


# ============================================================================
# DecayLevel enum
# ============================================================================


def test_decay_level_enum_values() -> None:
    """DecayLevel 应有 4 个枚举值。"""
    expected = {"none", "mild", "moderate", "severe"}
    actual = {level.value for level in DecayLevel}
    assert actual == expected


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
