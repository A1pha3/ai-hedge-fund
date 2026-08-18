"""公共前向收益函数测试 (题材动量 Tier A Task 1; 计划 v3.3).

forward_open_returns 语义与 court 执行口径逐字同源 (原 review_cond2_fund_flow_gate
._forward_returns 提升): T+1 open 买 / 一字锁死不可成交 / T+k open 卖缺 bar 顺延
至 FORWARD_SESSIONS 内。注意 T+k 语义 = 信号日之后第 k 个**交易日** (fwd 列表
第 k 位, 缺票 bar 的日子占位), 测试的 sessions_cal 必须提供完整会话序列。
"""

from __future__ import annotations

import pandas as pd

from scripts._btst_court_common import forward_open_returns


def _by_day(rows):
    df = pd.DataFrame(rows, columns=["trade_date", "ts_code", "open", "close", "pre_close"])
    return {d: g for d, g in df.groupby("trade_date")}


# 01005 信号日之后 10 个连续会话 (T+1..T+10)
_SESSIONS = ["20260105"] + [f"2026010{d}" for d in (6, 7, 8, 9)] + [
    "20260112", "20260113", "20260114", "20260115", "20260116", "20260119",
]


def test_normal_path_t8():
    by_day = _by_day([
        ("20260106", "600000.SH", 10.5, 10.6, 10.0),   # T+1 开盘买入 (+5% gap, 非一字)
        ("20260115", "600000.SH", 12.0, 12.5, 11.8),   # T+8 (fwd[7]) 开盘卖出
    ])
    out = forward_open_returns(by_day, _SESSIONS, "600000.SH", "20260105", 10.0, "600000")
    assert out["fillable"] is True
    assert out["t1_unbuyable"] is False
    assert out["t1_missing_bar"] is False
    assert abs(out["gap_t1_open"] - 0.05) < 1e-9
    assert abs(out["gross_ret_t8"] - (12.0 / 10.5 - 1)) < 1e-9


def test_yizi_unbuyable_at_limit_price():
    # T+1 open = pre_close × 1.10 (主板涨停价) → 一字锁死, 不可成交, 无收益键
    by_day = _by_day([("20260106", "600000.SH", 11.0, 11.0, 10.0)])
    out = forward_open_returns(by_day, _SESSIONS, "600000.SH", "20260105", 10.0, "600000")
    assert out["fillable"] is False
    assert out["t1_unbuyable"] is True
    assert "gross_ret_t8" not in out


def test_t1_missing_bar_unfillable():
    out = forward_open_returns({}, _SESSIONS, "600000.SH", "20260105", 10.0, "600000")
    assert out["fillable"] is False
    assert out["t1_missing_bar"] is True


def test_missing_exit_bar_defers_forward():
    # T+8 (fwd[7], 20260115) 票缺 bar → 顺延到 fwd[8] (20260116) 开盘
    by_day = _by_day([
        ("20260106", "600000.SH", 10.5, 10.6, 10.0),
        ("20260116", "600000.SH", 11.5, 11.6, 11.4),
    ])
    out = forward_open_returns(by_day, _SESSIONS, "600000.SH", "20260105", 10.0, "600000")
    assert out["fillable"] is True
    assert abs(out["gross_ret_t8"] - (11.5 / 10.5 - 1)) < 1e-9


def test_horizons_parameter_custom():
    by_day = _by_day([
        ("20260106", "600000.SH", 10.5, 10.6, 10.0),
        ("20260107", "600000.SH", 11.2, 11.3, 11.1),   # T+2 (自定义 horizon)
    ])
    out = forward_open_returns(by_day, _SESSIONS, "600000.SH", "20260105", 10.0, "600000",
                               horizons=(2,))
    assert abs(out["gross_ret_t2"] - (11.2 / 10.5 - 1)) < 1e-9
    assert "gross_ret_t8" not in out
