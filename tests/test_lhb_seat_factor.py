"""龙虎榜席位质量因子契约 (R60, owner 数据效率工作线④)。

全合成 hermetic。钉死的生死线:
- **PIT**: D 日榜的任何行不得进入 D 的因子值 (巨值对照断言) —
  court 是 T0 收盘决策, D 日榜晚间才发布, 用当日榜 = 未来函数。
- 窗口语义: 因子(D) = 严格 <D 的最近 3 个日历会话的金额加权净买比均值。
- 比率正确性: 合成榜手算精确相等; 无出现 → NaN 不冒充 0。
- fetch_lhb_daily --start: 有界回补, 窗外零调用。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from build_lhb_seat_factor import (  # noqa: E402
    LhbFactorError,
    _day_ratios,
    build_factor,
)
from fetch_lhb_daily import run_fetch  # noqa: E402

CAL = ["20260101", "20260102", "20260105", "20260106", "20260107", "20260108"]


def _write_lhb(tmp_path: Path, session: str, rows: list[dict]) -> None:
    lhb = tmp_path / "lhb_cache"
    lhb.mkdir(exist_ok=True)
    base = {"trade_date": session, "exalter": "机构专用", "buy_rate": 1.0,
            "sell_rate": 0.0, "side": 0, "reason": "r"}
    frame = pd.DataFrame([{**base, **r} for r in rows])
    frame.to_csv(lhb / f"{session}.csv", index=False)


def _write_cal(tmp_path: Path, sessions: list[str]) -> Path:
    p = tmp_path / "cal.json"
    p.write_text(json.dumps(sessions), encoding="utf-8")
    return p


def test_day_ratio_weighted_by_amount(tmp_path: Path) -> None:
    # 同票两席位: (100-0) 与 (100-100) → 比率 = (200-100)/300? 不 — 按日聚合:
    # buy=200 sell=100 → ratio=1/3, weight=300
    _write_lhb(tmp_path, "20260105", [
        {"ts_code": "000001.SZ", "buy": 100.0, "sell": 0.0},
        {"ts_code": "000001.SZ", "buy": 100.0, "sell": 100.0},
        {"ts_code": "000002.SZ", "buy": 0.0, "sell": 50.0},
    ])
    ratios = _day_ratios(tmp_path / "lhb_cache", "20260105")
    assert ratios["000001.SZ"] == pytest.approx((1 / 3, 300.0))
    assert ratios["000002.SZ"] == pytest.approx((-1.0, 50.0))


def test_pit_day_d_lhb_legal_in_day_window_and_d1_rejected(tmp_path: Path) -> None:
    """R64 纠错后的 PIT 锚: 决策截断 = 当日 23:00 北京, D 日榜 (~18:00 发布)
    **合法进入** D 的因子 (day 窗口); 跨日泄漏 (D+1 的行进入 D) 仍拒绝。"""
    cal = _write_cal(tmp_path, CAL)
    # D (0106): 巨幅净买 — day 窗口下合法进入 D 的因子
    _write_lhb(tmp_path, "20260106", [
        {"ts_code": "000001.SZ", "buy": 9_999_999.0, "sell": 0.0},
    ])
    factor, _ = build_factor(lhb_dir=tmp_path / "lhb_cache", calendar_path=cal,
                             start="20260106", end="20260106", window_end="day")
    row = factor[factor["ts_code"] == "000001.SZ"].iloc[0]
    assert row["signal_date"] == "20260106"
    assert row["factor"] == pytest.approx(1.0)  # 当日榜 (净买比 1.0) 合法计入
    # D+1 (0107) 的行不得进入 D (跨日泄漏拒绝, 与 window_end 无关)
    _write_lhb(tmp_path, "20260107", [
        {"ts_code": "000001.SZ", "buy": 5_000_000.0, "sell": 0.0},
    ])
    factor_d, _ = build_factor(lhb_dir=tmp_path / "lhb_cache", calendar_path=cal,
                               start="20260106", end="20260106", window_end="day")
    assert factor_d[factor_d["ts_code"] == "000001.SZ"].iloc[0]["factor"] == pytest.approx(1.0)
    # prior 变体: 旧 T-1 语义逐字节保留 (D 日榜不进 D)
    factor_prior, _ = build_factor(lhb_dir=tmp_path / "lhb_cache", calendar_path=cal,
                                   start="20260106", end="20260106", window_end="prior")
    assert len(factor_prior) == 0  # 仅有的 0106 榜不在 prior 窗口内


def test_day_window_includes_signal_day_and_weights(tmp_path: Path) -> None:
    """day 窗口 = [D-2, D] 三会话 (含当日), 金额加权手算精确。"""
    cal = _write_cal(tmp_path, CAL)
    _write_lhb(tmp_path, "20260104", [   # 窗口外 (0107 的窗口 = 0105/0106/0107)
        {"ts_code": "000001.SZ", "buy": 100.0, "sell": 0.0},
    ])
    _write_lhb(tmp_path, "20260105", [
        {"ts_code": "000001.SZ", "buy": 150.0, "sell": 100.0},   # ratio 0.2, w 250
    ])
    _write_lhb(tmp_path, "20260106", [
        {"ts_code": "000001.SZ", "buy": 60.0, "sell": 40.0},     # ratio 0.2, w 100
    ])
    _write_lhb(tmp_path, "20260107", [
        {"ts_code": "000001.SZ", "buy": 100.0, "sell": 0.0},     # ratio 1.0, w 100
    ])
    factor, _ = build_factor(lhb_dir=tmp_path / "lhb_cache", calendar_path=cal,
                             start="20260107", end="20260107", window_end="day")
    row = factor[factor["ts_code"] == "000001.SZ"].iloc[0]
    expected = (0.2 * 250 + 0.2 * 100 + 1.0 * 100) / (250 + 100 + 100)
    assert row["factor"] == pytest.approx(expected)


def test_window_is_strictly_before_and_three_sessions(tmp_path: Path) -> None:
    # prior 变体契约 (R64 后为兼容保留语义): 窗口严格 <D
    cal = _write_cal(tmp_path, CAL)
    # 0102: +1.0; 0105: -1.0; 0106: +1.0 → 因子(0107) 窗口=0102/0105/0106
    _write_lhb(tmp_path, "20260102", [{"ts_code": "000001.SZ", "buy": 10.0, "sell": 0.0}])
    _write_lhb(tmp_path, "20260105", [{"ts_code": "000001.SZ", "buy": 0.0, "sell": 10.0}])
    _write_lhb(tmp_path, "20260106", [{"ts_code": "000001.SZ", "buy": 10.0, "sell": 0.0}])
    factor, summary = build_factor(lhb_dir=tmp_path / "lhb_cache", calendar_path=cal,
                                   start="20260107", end="20260107", window_end="prior")
    row = factor[factor["ts_code"] == "000001.SZ"].iloc[0]
    assert row["factor"] == pytest.approx((10 - 10 + 10) / 30)  # 加权: (1-1+1)/3
    assert summary["window"] == 3


def test_missing_window_files_counted_not_silent(tmp_path: Path) -> None:
    cal = _write_cal(tmp_path, CAL)
    # 只写 0102; 0105/0106 缺文件 → 因子(0107) 仍从 0102 得值, 缺文件计数=2
    _write_lhb(tmp_path, "20260102", [{"ts_code": "000001.SZ", "buy": 10.0, "sell": 0.0}])
    factor, summary = build_factor(lhb_dir=tmp_path / "lhb_cache", calendar_path=cal,
                                   start="20260107", end="20260107", window_end="prior")
    row = factor[factor["ts_code"] == "000001.SZ"].iloc[0]
    assert row["factor"] == 1.0
    assert summary["missing_window_files"] == 2


def test_no_appearance_no_row_no_zero_faking(tmp_path: Path) -> None:
    cal = _write_cal(tmp_path, CAL)
    _write_lhb(tmp_path, "20260106", [{"ts_code": "000001.SZ", "buy": 10.0, "sell": 0.0}])
    factor, _ = build_factor(lhb_dir=tmp_path / "lhb_cache", calendar_path=cal,
                             start="20260107", end="20260107")
    assert "000002.SZ" not in set(factor["ts_code"])  # 未上榜票无行 (不伪装 0)
    assert len(factor) == 1


def test_range_and_calendar_contracts(tmp_path: Path) -> None:
    cal = _write_cal(tmp_path, ["20251231"])  # max < end → 过期响亮
    with pytest.raises(LhbFactorError) as ei:
        build_factor(lhb_dir=tmp_path / "lhb_cache", calendar_path=cal,
                     start="20260101", end="20260105")
    assert ei.value.code == "calendar_stale"
    cal2 = _write_cal(tmp_path, CAL)
    with pytest.raises(LhbFactorError) as ei2:
        build_factor(lhb_dir=tmp_path / "lhb_cache", calendar_path=cal2,
                     start="20260108", end="20260101")
    assert ei2.value.code == "invalid_date_args"
    with pytest.raises(LhbFactorError) as ei3:
        build_factor(lhb_dir=tmp_path / "lhb_cache", calendar_path=cal2,
                     start="19990101", end="19990105")
    assert ei3.value.code == "no_sessions_in_range"


# ---- fetch_lhb_daily --start 有界回补 ----


def test_fetch_start_bounds_catchup(tmp_path: Path) -> None:
    cal = _write_cal(tmp_path, CAL)
    cache = tmp_path / "lhb_cache"
    cache.mkdir()
    calls: list[str] = []

    def fetch_fn(session: str):
        calls.append(session)
        return pd.DataFrame([{"trade_date": session, "ts_code": "x"}])

    run_fetch(cache_dir=cache, calendar_path=cal, today="20260108",
              fetch_fn=fetch_fn, rate_sleep=0, start="20260106")
    # T-1 语义: expected=0107 (今日 0108 不可达); 带 start 只补 06/07
    assert calls == ["20260106", "20260107"]


def test_fetch_start_invalid_typed(tmp_path: Path) -> None:
    cal = _write_cal(tmp_path, CAL)
    with pytest.raises(Exception) as ei:
        run_fetch(cache_dir=tmp_path, calendar_path=cal, today="20260108",
                  fetch_fn=lambda s: None, rate_sleep=0, start="2026-01-01")
    assert "invalid_start" in str(ei.value)


def test_fetch_start_backfills_gaps_below_cached_max(tmp_path: Path) -> None:
    """R61 生死线: --start 能回补既有缓存**之前**的历史缺口 (R60 实锤阻塞)。"""
    cal = _write_cal(tmp_path, CAL)
    cache = tmp_path / "lhb_cache"
    cache.mkdir()
    (cache / "20260105.csv").write_text("trade_date,ts_code\n", encoding="utf-8")
    calls: list[str] = []

    def fetch_fn(session: str):
        calls.append(session)
        return pd.DataFrame([{"trade_date": session, "ts_code": "x"}])

    summary = run_fetch(cache_dir=cache, calendar_path=cal, today="20260107",
                        fetch_fn=fetch_fn, rate_sleep=0, start="20260101")
    # 窗口 [0101, 0106(expected=0107 之前)] 减已缓存 0105 → 01/02/06
    assert calls == ["20260101", "20260102", "20260106"]
    assert summary["fetched"] == ["20260101", "20260102", "20260106"]


def test_fetch_no_start_daily_catchup_semantics_unchanged(tmp_path: Path) -> None:
    """无 start: 日更追平语义逐字节回归 — 缓存之前的历史缺口不被触碰。"""
    cal = _write_cal(tmp_path, CAL)
    cache = tmp_path / "lhb_cache"
    cache.mkdir()
    (cache / "20260105.csv").write_text("trade_date,ts_code\n", encoding="utf-8")
    calls: list[str] = []
    run_fetch(cache_dir=cache, calendar_path=cal, today="20260107",
              fetch_fn=lambda s: (calls.append(s),
                                  pd.DataFrame([{"trade_date": s, "ts_code": "x"}]))[1],
              rate_sleep=0)
    assert calls == ["20260106"]  # 只追平 max(cached) 之后


def test_invalid_window_end_typed(tmp_path: Path) -> None:
    cal = _write_cal(tmp_path, CAL)
    with pytest.raises(LhbFactorError) as ei:
        build_factor(lhb_dir=tmp_path / "lhb_cache", calendar_path=cal,
                     start="20260107", end="20260107", window_end="tomorrow")
    assert ei.value.code == "invalid_window_end"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
