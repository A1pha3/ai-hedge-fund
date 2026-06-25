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
