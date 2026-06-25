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

from src.screening.state_type_calibration import _score_bucket, compute_state_type_bucket_subdivision  # noqa: E402


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

from src.screening.state_type_calibration import leave_one_period_out_validation  # noqa: E402


def test_q3_lopo_rediscovers_real_signal_out_of_sample():
    # 3 个 RANGE 日期; 每个日期内 high bucket 涨、low bucket 跌 (跨所有日期一致)
    history = [
        {"date": f"2025060{d}", "payload": {"market_state": {"state_type": "RANGE"}}}
        for d in (1, 2, 3)
    ]
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
    history = [
        {"date": f"2025060{d}", "payload": {"market_state": {"state_type": "RANGE"}}}
        for d in (1, 2, 3)
    ]
    rets_by_day = {"1": 10.0, "2": -8.0, "3": -8.0}
    records = []
    for d, ret in rets_by_day.items():
        records.append({"recommended_date": f"2025060{d}", "score_b": 0.55, "next_30day_return": ret})
        records.append({"recommended_date": f"2025060{d}", "score_b": 0.10, "next_30day_return": -1.0})
    report = leave_one_period_out_validation(history, records, target_state_types=("RANGE",), min_n=1)
    # 留出 day2/day3 时 high 在留出日胜率为 0 → 维持率 1/3 < 60% → 不稳健
    assert report.robust is False
    assert report.rediscovered_winner_rate < 0.6
