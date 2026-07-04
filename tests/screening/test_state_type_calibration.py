"""R-5.F Phase 0 state_type 诊断模块的合成数据测试.

不依赖真实报告文件 —— 全部用内联合成 history + tracking records.
"""

from __future__ import annotations

from src.screening.state_type_calibration import (
    _build_date_state_type_map,
    compute_state_type_calibration_from_loaded,
)


def test_build_date_state_type_map_reads_state_type_from_payload():
    history = [
        {"date": "2025-06-01", "payload": {"market_state": {"state_type": "TREND"}}},
        {"date": "20250602", "payload": {"market_state": {"state_type": "range"}}},
        {"date": "20250603", "payload": {"market_state": {}}},  # 缺 state_type → OTHER
    ]
    mapping = _build_date_state_type_map(history)
    assert mapping == {"20250601": "TREND", "20250602": "RANGE", "20250603": "OTHER"}


def test_q1_groups_t30_by_state_type_with_winrate_and_median():
    history = [
        {"date": "20250601", "payload": {"market_state": {"state_type": "TREND"}}},
        {"date": "20250602", "payload": {"market_state": {"state_type": "RANGE"}}},
    ]
    # 20250601(TREND) 两只都涨; 20250602(RANGE) 两只都跌
    records = [
        {"recommended_date": "20250601", "score_b": 0.5, "next_30day_return": 5.0},
        {"recommended_date": "20250601", "score_b": 0.4, "next_30day_return": 3.0},
        {"recommended_date": "20250602", "score_b": 0.5, "next_30day_return": -4.0},
        {"recommended_date": "20250602", "score_b": 0.4, "next_30day_return": -2.0},
    ]
    report = compute_state_type_calibration_from_loaded(history, records)
    by_st = {r.state_type: r for r in report.rows}
    assert by_st["TREND"].t30_win_rate == 1.0
    assert by_st["TREND"].t30_median_return == 4.0
    assert by_st["RANGE"].t30_win_rate == 0.0
    assert by_st["RANGE"].t30_median_return == -3.0
    assert by_st["TREND"].mature_t30_count == 2
    assert by_st["RANGE"].mature_t30_count == 2


# ---------------------------------------------------------------------------
# Task 2: 问2 震荡市 score-bucket 细分
# ---------------------------------------------------------------------------

from src.screening.state_type_calibration import (  # noqa: E402
    _score_bucket,
    compute_state_type_bucket_subdivision,
)


def test_score_bucket_bands():
    assert _score_bucket(None) == "unknown"
    assert _score_bucket(0.10) == "low"
    assert _score_bucket(0.29) == "low"
    assert _score_bucket(0.30) == "mid_low"
    assert _score_bucket(0.39) == "mid_low"
    assert _score_bucket(0.40) == "mid_high"
    assert _score_bucket(0.499) == "mid_high"
    assert _score_bucket(0.50) == "high"
    assert _score_bucket(0.90) == "high"


def test_q2_subdivides_target_state_types_by_score_bucket():
    history = [
        {"date": "20250601", "payload": {"market_state": {"state_type": "RANGE"}}},
    ]
    # RANGE 市内: high bucket 两只都涨, low bucket 两只都跌
    records = [
        {"recommended_date": "20250601", "score_b": 0.55, "next_30day_return": 6.0},
        {"recommended_date": "20250601", "score_b": 0.60, "next_30day_return": 4.0},
        {"recommended_date": "20250601", "score_b": 0.10, "next_30day_return": -5.0},
        {"recommended_date": "20250601", "score_b": 0.20, "next_30day_return": -3.0},
    ]
    rows = compute_state_type_bucket_subdivision(history, records, target_state_types=("RANGE",))
    by_bucket = {(r.state_type, r.bucket): r for r in rows}
    assert by_bucket[("RANGE", "high")].t30_win_rate == 1.0
    assert by_bucket[("RANGE", "low")].t30_win_rate == 0.0
    assert by_bucket[("RANGE", "high")].sample_count == 2
    # TREND 日的记录不应出现 (非 target)
    assert all(r.state_type == "RANGE" for r in rows)


# ---------------------------------------------------------------------------
# Task 3: 问3 留一时段样本外验证 (防 in-sample 过拟合核心)
# ---------------------------------------------------------------------------

from src.screening.state_type_calibration import (  # noqa: E402
    leave_one_period_out_validation,
)


def test_q3_lopo_rediscovers_real_signal_out_of_sample():
    # 3 个 RANGE 日期; 每个日期内 high bucket 涨、low bucket 跌 (跨所有日期一致)
    history = [{"date": f"2025060{d}", "payload": {"market_state": {"state_type": "RANGE"}}} for d in (1, 2, 3)]
    records = []
    for d in (1, 2, 3):
        records += [
            {"recommended_date": f"2025060{d}", "score_b": 0.55, "next_30day_return": 6.0},
            {"recommended_date": f"2025060{d}", "score_b": 0.10, "next_30day_return": -5.0},
        ]
    report = leave_one_period_out_validation(history, records, target_state_types=("RANGE",), min_n=1)
    # 每次留出一个日期, 用其余两日发现 high 是赢家 → high 在留出日也应高胜率
    assert report.heldout_periods == 3
    assert report.rediscovered_winner_rate == 1.0  # 3/3 留出日 high 都维持高胜率
    assert report.robust is True


def test_q3_lopo_rejects_in_sample_artifact():
    # high bucket 只在 day1 大涨, day2/day3 都跌 → 留出 day2/day3 时 high 不再维持
    # (整体均值可能被 day1 拉高, 但逐留出日不稳定 = in-sample 假象)
    history = [{"date": f"2025060{d}", "payload": {"market_state": {"state_type": "RANGE"}}} for d in (1, 2, 3)]
    rets_by_day = {"1": 10.0, "2": -8.0, "3": -8.0}
    records = []
    for d, ret in rets_by_day.items():
        records.append({"recommended_date": f"2025060{d}", "score_b": 0.55, "next_30day_return": ret})
        records.append({"recommended_date": f"2025060{d}", "score_b": 0.10, "next_30day_return": -1.0})
    report = leave_one_period_out_validation(history, records, target_state_types=("RANGE",), min_n=1)
    # 留出 day2/day3 时 high 在留出日胜率为 0 → 维持率 1/3 < 60% → 不稳健
    assert report.robust is False
    assert report.rediscovered_winner_rate < 0.6


# ---------------------------------------------------------------------------
# Task 4: verdict 聚合 (1A/1B/STOP) — spec §九 映射表
# ---------------------------------------------------------------------------

from src.screening.state_type_calibration import (  # noqa: E402
    aggregate_verdict,
    DiagnosisVerdict,
    LopoReport,
    StateTypeCalibrationReport,
    StateTypeWinRate,
)


def test_verdict_stop_when_state_type_not_discriminative():
    # 问1 no: TREND 与 RANGE 胜率接近 (< 10pp 差)
    q1 = StateTypeCalibrationReport(
        rows=[
            StateTypeWinRate("TREND", t30_win_rate=0.45, mature_t30_count=60),
            StateTypeWinRate("RANGE", t30_win_rate=0.43, mature_t30_count=80),
        ]
    )
    verdict = aggregate_verdict(q1=q1, q2_best_bucket_winrate=None, q3=LopoReport(target_state_types=("RANGE",), robust=False))
    assert verdict.phase1_branch == "STOP"
    assert "not discriminative" in verdict.reason.lower()


def test_verdict_1a_when_all_three_yes():
    q1 = StateTypeCalibrationReport(
        rows=[
            StateTypeWinRate("TREND", t30_win_rate=0.80, mature_t30_count=60),
            StateTypeWinRate("RANGE", t30_win_rate=0.25, mature_t30_count=80),
        ]
    )
    q3 = LopoReport(target_state_types=("RANGE",), robust=True, rediscovered_winner_rate=0.8, heldout_periods=10)
    verdict = aggregate_verdict(q1=q1, q2_best_bucket_winrate=0.62, q3=q3)
    assert verdict.phase1_branch == "1A"


def test_verdict_1b_when_q1_yes_but_no_robust_subset():
    q1 = StateTypeCalibrationReport(
        rows=[
            StateTypeWinRate("TREND", t30_win_rate=0.80, mature_t30_count=60),
            StateTypeWinRate("RANGE", t30_win_rate=0.25, mature_t30_count=80),
        ]
    )
    q3 = LopoReport(target_state_types=("RANGE",), robust=False)
    verdict = aggregate_verdict(q1=q1, q2_best_bucket_winrate=0.40, q3=q3)
    assert verdict.phase1_branch == "1B"


# ---------------------------------------------------------------------------
# Task 5 fix: tracking_history 真实字段是 recommendation_score (非 score_b)
# ---------------------------------------------------------------------------


def test_q2_uses_recommendation_score_field_not_score_b():
    """tracking_history 记录用 recommendation_score; 须能正确分桶 (回归守卫)."""
    history = [
        {"date": "20250601", "payload": {"market_state": {"state_type": "RANGE"}}},
    ]
    records = [
        # recommendation_score=0.55 → high bucket 涨; 0.10 → low bucket 跌
        {"recommended_date": "20250601", "recommendation_score": 0.55, "next_30day_return": 6.0},
        {"recommended_date": "20250601", "recommendation_score": 0.10, "next_30day_return": -5.0},
    ]
    rows = compute_state_type_bucket_subdivision(history, records, target_state_types=("RANGE",))
    by_bucket = {(r.state_type, r.bucket): r for r in rows}
    assert ("RANGE", "high") in by_bucket  # 0.55 → high
    assert ("RANGE", "low") in by_bucket  # 0.10 → low
    assert by_bucket[("RANGE", "high")].t30_win_rate == 1.0
    assert by_bucket[("RANGE", "low")].t30_win_rate == 0.0
