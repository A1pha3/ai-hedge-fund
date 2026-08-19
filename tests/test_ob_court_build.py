"""ob_court_build / ob_court_report 口径核心纯函数测试 — OB 暂停复核 court 管道首张回归网.

锁定 (预注册契约):
- drop30_index 与生产 chained_return_pct 同数学 (prod(1+pct/100)-1, 30 行窗),
  窗口不足/任一 pct 缺失 → 不产出键 (与 detect 保守 miss 一致); 北交所排除;
- ticker_frame PIT 截断与列契约 (detect 语义输入);
- 生产 detect 忠实重放: 预筛放行的构造 fixture 也过 detect 条件 1 (同面板同数学);
- pause_verdict: 样本不足 → None (fail-closed 不判); 深负样本 → pause_holds True;
  强正样本 (CI 下界 > 0) → pause_holds False (如实上报, 不因结论方向改判定);
- 防覆盖护栏: 同指纹允许, 异指纹拒绝, force 例外 (btst_court 同族);
- net 口径 = gross - 65bps (与 btst_court_views.net_ret 同源)。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ob_court_build import (  # noqa: E402
    _DROP_THRESHOLD,
    _LOOKBACK_DROP_ROWS,
    drop30_index,
    overwrite_allowed,
    ticker_frame,
)
from ob_court_report import JOURNAL_ANCHOR, pause_verdict  # noqa: E402


def _panel_group(pcts: list[float], dates: list[str] | None = None, ts: str = "600000.SH") -> pd.DataFrame:
    n = len(pcts)
    dates = dates or [f"2026{i:04d}" for i in range(1, n + 1)]  # 占位, 测试里都显式传
    close = np.cumprod(1 + np.array(pcts) / 100.0) * 10.0
    return pd.DataFrame({
        "ts_code": [ts] * n,
        "trade_date": dates,
        "open": close * 0.99,
        "high": close * 1.02,
        "low": close * 0.98,
        "close": close,
        "pct_chg": pcts,
        "vol": [1000.0] * n,
    })


def _dates(n: int, start="20260101") -> list[str]:
    return pd.bdate_range(start, periods=n).strftime("%Y%m%d").tolist()


# ---------- drop30_index: 与生产 chained_return_pct 同数学 ----------


def test_drop30_matches_chained_return_pct():
    from src.screening.offensive.price_returns import chained_return_pct

    rng = np.random.default_rng(7)
    pcts = rng.normal(-0.5, 4, 60).round(4).tolist()  # 偏负漂移 → 若干窗口达 -20%
    panel = _panel_group(pcts, _dates(60))
    idx = drop30_index(panel)
    frame = ticker_frame(panel, "20991231")
    checked = 0
    for i in range(_LOOKBACK_DROP_ROWS, 60):
        d = panel["trade_date"].iloc[i]
        expect = chained_return_pct(frame, i - _LOOKBACK_DROP_ROWS, i)
        if expect is not None and expect <= _DROP_THRESHOLD:
            assert abs(idx[("600000.SH", d)] - expect) < 1e-9  # 达标键值一致
            checked += 1
        else:
            assert ("600000.SH", d) not in idx  # 未达标键不产出
    assert checked > 0  # 本种子确有达标窗口 (随机回归钉死种子)


def test_drop30_short_window_and_nan_excluded():
    # 30 行整 (i=29 是第一个可判行, 30×-1%=-26% 达标) — 29 行不可判
    panel = _panel_group([-1.0] * 31, _dates(31))
    idx = drop30_index(panel)
    assert ("600000.SH", panel["trade_date"].iloc[28]) not in idx
    assert ("600000.SH", panel["trade_date"].iloc[29]) in idx
    pcts = [-1.0] * 35
    pcts[33] = float("nan")
    panel2 = _panel_group(pcts, _dates(35))
    idx2 = drop30_index(panel2)
    assert ("600000.SH", panel2["trade_date"].iloc[34]) not in idx2  # NaN 在窗内 → 排除
    assert ("600000.SH", panel2["trade_date"].iloc[32]) in idx2  # 窗内无 NaN (0..32 恒 -1%) → 达标


def test_drop30_threshold_boundary_and_bj_excluded():
    # 达标 (-21%) 放行 / 未达标 (-19%) 不产出 — 与 detect 条件 1 阈值互补
    for daily, expect_in in ((-0.78, True), (-0.70, False)):  # 30 日复合 ≈ -21% / -19%
        panel = _panel_group([0.0] + [daily] * 30, _dates(31))
        idx = drop30_index(panel)
        key = ("600000.SH", panel["trade_date"].iloc[30])
        assert (key in idx) is expect_in
    bj = _panel_group([-1.0] * 31, _dates(31), ts="832000.BJ")
    assert drop30_index(bj) == {}  # 北交所排除 (即使达标)


# ---------- 生产 detect 忠实重放: 预筛放行 ⇒ detect 条件 1 也过 ----------


def test_prefilter_passes_detect_condition1():
    from src.screening.offensive.price_returns import chained_return_pct

    pcts = [0.2] * 29 + [-2.0] * 15  # 深跌尾段 → 末日 30d 链 ≈ -23.7% ≤ -20%
    panel = _panel_group(pcts, _dates(44))
    frame = ticker_frame(panel, panel["trade_date"].iloc[-1])
    # 预筛放行的 (drop ≤ -20), 生产 detect 同款链式跌幅也放行 — 同面板同数学
    drop = chained_return_pct(frame, len(frame) - 31, len(frame) - 1)
    assert drop <= _DROP_THRESHOLD
    # 反向: 温和窗口 (链 ≈ -9.5%) 预筛不放行, detect 条件 1 同样 miss
    mild = [0.2] * 29 + [-0.7] * 15
    panel2 = _panel_group(mild, _dates(44))
    frame2 = ticker_frame(panel2, panel2["trade_date"].iloc[-1])
    drop2 = chained_return_pct(frame2, len(frame2) - 31, len(frame2) - 1)
    assert drop2 > _DROP_THRESHOLD


# ---------- ticker_frame: PIT 截断 + 列契约 ----------


def test_ticker_frame_pit_truncation_and_columns():
    panel = _panel_group([1.0, -1.0, 0.5], _dates(3))
    upto = panel["trade_date"].iloc[1]
    frame = ticker_frame(panel, upto)
    assert list(frame.columns) == ["date", "open", "high", "low", "close", "volume", "pct_change"]
    assert len(frame) == 2
    assert frame.iloc[-1]["date"].replace("-", "") == upto
    assert str(frame["pct_change"].iloc[-1]) == str(-1.0)


# ---------- pause_verdict: 预注册谓词 ----------


def _events(rets: list[float], dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame({
        "fillable": [True] * len(rets),
        "gross_ret_t5": rets,
        "signal_date": dates,
    })


def test_pause_verdict_insufficient_sample_fail_closed():
    v = pause_verdict(_events([0.01] * 10, _dates(10)))
    assert v["pause_holds"] is None and v["n"] == 10


def test_pause_verdict_deeply_negative_holds_pause():
    rng = np.random.default_rng(3)
    rets = (rng.normal(-0.03, 0.05, 400)).tolist()
    v = pause_verdict(_events(rets, _dates(400)))
    assert v["mean_net"] < 0
    assert v["pause_holds"] is True


def test_pause_verdict_strong_positive_flags_owner_review():
    rng = np.random.default_rng(4)
    rets = (rng.normal(+0.05, 0.02, 400)).tolist()
    v = pause_verdict(_events(rets, _dates(400)))
    assert v["mean_net"] > 0
    assert v["ci_low_90"] > 0
    assert v["pause_holds"] is False  # 如实: 上报复议, 不因方向改判定


def test_pause_verdict_excludes_unfillable_and_missing():
    df = _events([0.01] * 50, _dates(50))
    df.loc[0, "fillable"] = False
    df.loc[1, "gross_ret_t5"] = None
    v = pause_verdict(df)
    assert v["n"] == 48


# ---------- 防覆盖护栏 (btst_court 同族) ----------


def test_overwrite_guard_same_fp_allowed_diff_refused_force_exception():
    assert overwrite_allowed(None, "aa", force=False) is True
    assert overwrite_allowed("aa", "aa", force=False) is True
    assert overwrite_allowed("aa", "bb", force=False) is False
    assert overwrite_allowed("aa", "bb", force=True) is True


# ---------- net 口径 & 对照锚 ----------


def test_net_ret_65bps_and_journal_anchor_disclosed():
    from btst_court_views import net_ret

    gross = pd.Series([0.0, 0.1])
    net = net_ret(gross, 30.0)
    assert abs((net - gross).iloc[0] + 0.0065) < 1e-12  # 2×30bps + 5bps
    assert JOURNAL_ANCHOR["n"] == 56 and JOURNAL_ANCHOR["mean"] == -0.0215
