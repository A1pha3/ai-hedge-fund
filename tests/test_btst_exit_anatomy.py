"""btst_exit_anatomy — 纯函数 + fixture 端到端 (第九十五轮 Op1).

纪律钉死: A 股 T+1 规则 (可实现窗口 T+2 起)、corp-action 显式排除、
止损诚实成交 (跳空按 open/日内按止损价/未触及按合约退出)、entry 交叉验证、
确定性聚合。
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts.btst_exit_anatomy import (
    CORP_ACTION_TICK,
    ROUNDTRIP_COST,
    STOP_GRID_PCT,
    aggregate_anatomy,
    aligned_mask,
    anatomy_event,
    detect_corp_action,
    extract_path_bars,
    path_anatomy,
    realizable_path,
    render_md,
    sessions_for_window,
    stop_counterfactual,
)


def _bar(session, open_, high, low, close, pre_close=None):
    return {
        "session": session,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "pre_close": pre_close if pre_close is not None else close,
    }


def _cal(n=30, start=20260101):
    """合成交易日历 (工作日序; 只保证升序唯一, 不对齐真实假日)。"""
    from datetime import date, timedelta

    d0 = date(2026, 1, 5)
    out = []
    while len(out) < n:
        if d0.weekday() < 5:
            out.append(d0.strftime("%Y%m%d"))
        d0 += timedelta(days=1)
    return out


CAL = _cal()


def _flat_path(entry=10.0, sessions=10, drift=0.0):
    """合成路径: 从 T+1 (CAL[1]) 起逐日; pre_close 链正确接前日收盘。"""
    bars = [_bar(CAL[1], entry, entry, entry, entry, pre_close=entry)]
    for i in range(1, sessions):
        px = entry * (1 + drift * i)
        bars.append(_bar(CAL[1 + i], px, px, px, px, pre_close=bars[-1]["close"]))
    return bars


class TestSessionsForWindow:
    def test_slice_is_signal_exclusive_offset_inclusive(self):
        """offset 语义与 build 层逐一对应: fwd[offset-1] = T+offset 会话。"""
        sessions = sessions_for_window(CAL[0], 10, CAL)
        assert sessions[0] == CAL[1]
        assert sessions[-1] == CAL[10]
        assert len(sessions) == 10

    def test_exit_beyond_forward_window_truncated(self):
        sessions = sessions_for_window(CAL[0], 99, CAL)
        assert len(sessions) == 15  # FORWARD_SESSIONS

    def test_offset_semantics_matches_build_bars_j_plus_1(self):
        """build 的 bars[j] → offset=j+1: offset=3 ⇒ 切片恰含 T+1..T+3。"""
        sessions = sessions_for_window(CAL[0], 3, CAL)
        assert [s for s in sessions] == [CAL[1], CAL[2], CAL[3]]


class TestRealizablePath:
    def test_t1_entry_day_excluded_ashare_t1_rule(self):
        bars = _flat_path(sessions=12)  # 覆盖 T+1=CAL[1]..CAL[12]
        path = realizable_path(bars)
        assert path[0]["session"] == CAL[2]  # T+2 起
        assert all(bar["session"] != CAL[1] for bar in path)  # T+1 不在路径

    def test_path_runs_to_window_end(self):
        bars = _flat_path(sessions=12)
        path = realizable_path(bars)
        assert len(path) == 11  # T+2..T+12


class TestCorpAction:
    def test_pre_close_discontinuity_flagged(self):
        bars = _flat_path(sessions=6)
        bars[3]["pre_close"] = bars[2]["close"] * 0.5  # 10送10 型跳变
        flagged = detect_corp_action(bars)
        assert flagged == [bars[3]["session"]]

    def test_rounding_within_tick_not_flagged(self):
        bars = _flat_path(sessions=6)
        bars[2]["pre_close"] = bars[1]["close"] + 0.005  # 半档以内 (舍入域)
        assert detect_corp_action(bars) == []

    def test_first_bar_no_prior_close_never_flagged(self):
        bars = _flat_path(sessions=3)
        bars[0]["pre_close"] = 999.0
        assert detect_corp_action(bars) == []

    def test_across_suspension_compares_last_seen_close(self):
        bars = _flat_path(sessions=6)
        bars[2] = _bar(bars[2]["session"], None, None, None, None)  # 停牌
        bars[3]["pre_close"] = bars[1]["close"] * 0.8  # 与上一可见收盘比较
        assert detect_corp_action(bars) == [bars[3]["session"]]


class TestPathAnatomy:
    def test_mfe_ignores_t1_intraday_high(self):
        bars = _flat_path(sessions=10)
        bars[0]["high"] = 99.0  # T+1 日内高点 — 买入当日不可卖
        path = realizable_path(bars)
        anatomy = path_anatomy(entry=10.0, path=path)
        assert anatomy["mfe"] == pytest.approx(0.0)  # 其余日持平

    def test_mfe_mae_and_time_indices(self):
        path = [
            _bar(CAL[0], 10.0, 10.5, 9.8, 10.0),
            _bar(CAL[1], 10.0, 12.0, 9.9, 11.0),  # 峰 T+3 (idx 1)
            _bar(CAL[2], 11.0, 11.2, 8.8, 9.0),  # 谷 T+4 (idx 2)
            _bar(CAL[3], 9.0, 9.5, 8.9, 9.2),
        ]
        anatomy = path_anatomy(entry=10.0, path=path)
        assert anatomy["mfe"] == pytest.approx(0.20)
        assert anatomy["mae"] == pytest.approx(-0.12)
        assert anatomy["time_to_peak"] == 1
        assert anatomy["time_to_trough"] == 2

    def test_tie_on_high_reports_earliest(self):
        path = [
            _bar(CAL[0], 10.0, 11.0, 10.0, 10.0),
            _bar(CAL[1], 10.0, 11.0, 10.0, 10.0),
        ]
        anatomy = path_anatomy(entry=10.0, path=path)
        assert anatomy["time_to_peak"] == 0

    def test_all_suspended_yields_none(self):
        path = [_bar(CAL[0], None, None, None, None)]
        anatomy = path_anatomy(entry=10.0, path=path)
        assert anatomy["mfe"] is None and anatomy["mae"] is None


class TestStopCounterfactual:
    def test_gap_through_fills_at_open_not_stop_price(self):
        path = [_bar(CAL[1], 9.0, 9.2, 8.8, 9.0)]  # open 9.0 < 止损 9.2
        out = stop_counterfactual(10.0, path, contract_exit_open=11.0, stop_pct=-0.08)
        assert out["stopped"] is True
        assert out["reason"] == "gap_through_open"
        assert out["fill"] == 9.0
        assert out["net"] == pytest.approx(9.0 / 10.0 - 1 - ROUNDTRIP_COST)

    def test_intrabar_touch_fills_at_stop_price(self):
        path = [_bar(CAL[1], 9.6, 9.8, 9.1, 9.5)]  # low 9.1 ≤ 9.2 < open
        out = stop_counterfactual(10.0, path, contract_exit_open=11.0, stop_pct=-0.08)
        assert out["stopped"] is True
        assert out["reason"] == "intrabar_touch"
        assert out["fill"] == pytest.approx(9.2)

    def test_no_touch_exits_at_contract_open(self):
        path = [_bar(CAL[1], 10.5, 11.0, 10.2, 10.8)]
        out = stop_counterfactual(10.0, path, contract_exit_open=11.0, stop_pct=-0.08)
        assert out["stopped"] is False
        assert out["reason"] == "contract_exit"
        assert out["fill"] == 11.0

    def test_exit_missing_bar_disclosed_not_fabricated(self):
        path = [_bar(CAL[1], 10.5, 11.0, 10.2, 10.8)]
        out = stop_counterfactual(10.0, path, contract_exit_open=None, stop_pct=-0.08)
        assert out["reason"] == "contract_exit_missing_bar"
        assert out["net"] is None

    def test_suspended_session_skipped_not_stopped(self):
        path = [
            _bar(CAL[1], None, None, None, None),
            _bar(CAL[2], 10.5, 11.0, 10.2, 10.8),
        ]
        out = stop_counterfactual(10.0, path, contract_exit_open=11.0, stop_pct=-0.08)
        assert out["reason"] == "contract_exit"


class TestAnatomyEvent:
    def _event(self, signal_close=10.0, gap=0.0, exit_offset=10):
        return pd.Series(
            {
                "ts_code": "000001.SZ",
                "signal_date": CAL[0],
                "exit_session_t10": exit_offset,  # 偏移量 (build 层语义)
                "signal_close": signal_close,
                "gap_t1_open": gap,
            }
        )

    def _by_day(self, bars):
        return {
            session: pd.DataFrame(
                [
                    {
                        "ts_code": "000001.SZ",
                        "open": b["open"],
                        "high": b["high"],
                        "low": b["low"],
                        "close": b["close"],
                        "pre_close": b["pre_close"],
                    }
                    for b in bars
                    if b["session"] == session
                ]
            )
            for session in {b["session"] for b in bars}
        }

    def test_entry_crosscheck_mismatch_excluded_distinctly(self):
        bars = _flat_path(sessions=11)
        bars[0]["open"] = 10.5  # 与 signal_close×(1+gap) 不一致
        out = anatomy_event(self._event(), self._by_day(bars), CAL)
        assert out == {"excluded_entry_mismatch": True, "signal_date": CAL[0]}

    def test_t1_bar_missing_excluded_distinctly(self):
        bars = _flat_path(sessions=11)
        bars[0] = _bar(bars[0]["session"], None, None, None, None)
        out = anatomy_event(self._event(), self._by_day(bars), CAL)
        assert out == {"excluded_t1_bar_missing": True, "signal_date": CAL[0]}

    def test_exit_unfilled_nan_offset_excluded_distinctly(self):
        bars = _flat_path(sessions=11)
        out = anatomy_event(self._event(exit_offset=float("nan")), self._by_day(bars), CAL)
        assert out == {"excluded_exit_unfilled": True, "signal_date": CAL[0]}

    def test_corp_action_excluded_with_count(self):
        bars = _flat_path(sessions=11)
        bars[4]["pre_close"] = bars[3]["close"] * 0.5
        out = anatomy_event(self._event(), self._by_day(bars), CAL)
        assert out == {
            "excluded_corp_action": [bars[4]["session"]],
            "signal_date": CAL[0],
        }

    def test_happy_path_stops_and_base_present(self):
        bars = _flat_path(sessions=11)
        bars[5] = _bar(bars[5]["session"], 9.5, 9.6, 8.9, 9.0, pre_close=10.0)  # 触发 -8%
        bars[6]["pre_close"] = bars[5]["close"]  # 普通下跌: 交易所 pre_close=前收盘
        out = anatomy_event(self._event(), self._by_day(bars), CAL)
        assert out is not None and "excluded_corp_action" not in out
        assert out["stops"]["-8%"]["reason"] == "intrabar_touch"
        assert out["contract_exit_net"] == pytest.approx(-ROUNDTRIP_COST)  # 全平路径


class TestAggregate:
    def test_counts_all_exclusion_classes(self):
        rows = [
            None,
            {"excluded_corp_action": ["x"], "signal_date": "d"},
            {"excluded_exit_bar_missing": True, "signal_date": "d"},
            {"excluded_exit_unfilled": True, "signal_date": "d"},
            {"excluded_t1_bar_missing": True, "signal_date": "d"},
            {"excluded_entry_mismatch": True, "signal_date": "d"},
            {
                "mfe": 0.1,
                "mae": -0.1,
                "time_to_peak": 0,
                "time_to_trough": 1,
                "realizable_sessions": 9,
                "observed_sessions": 9,
                "contract_exit_net": 0.05,
                "signal_date": "d",
                "stops": {
                    f"{p:.0%}": {
                        "stopped": False,
                        "reason": "contract_exit",
                        "session": "d",
                        "fill": 1.0,
                        "net": 0.04,
                    }
                    for p in STOP_GRID_PCT
                },
            },
        ]
        agg = aggregate_anatomy(rows)
        assert agg["n_events"] == 7
        assert agg["n_entry_mismatch"] == 1
        assert agg["n_t1_bar_missing"] == 1
        assert agg["n_exit_unfilled"] == 1
        assert agg["n_corp_action_excluded"] == 1
        assert agg["n_exit_bar_missing"] == 1
        assert agg["n_included"] == 1  # None 行不计入任何排除类, 也不计入 included
        assert agg["time_to_peak_buckets"]["T+2"] == 1

    def test_empty_rows_safe(self):
        agg = aggregate_anatomy([])
        assert agg["n_included"] == 0
        assert agg["base"]["mean_net"] is None

    def test_deterministic_output(self):
        rows = [
            {
                "mfe": 0.2 - i * 0.01,
                "mae": -0.1 - i * 0.01,
                "time_to_peak": i % 4,
                "time_to_trough": 1,
                "realizable_sessions": 9,
                "observed_sessions": 9,
                "contract_exit_net": 0.03 + i * 0.001,
                "signal_date": f"d{i}",
                "stops": {
                    f"{p:.0%}": {
                        "stopped": i % 2 == 0,
                        "reason": "intrabar_touch" if i % 2 == 0 else "contract_exit",
                        "session": "d",
                        "fill": 9.2,
                        "net": 0.01 + i * 0.001,
                    }
                    for p in STOP_GRID_PCT
                },
            }
            for i in range(7)
        ]
        assert json.dumps(aggregate_anatomy(rows), sort_keys=True) == json.dumps(
            aggregate_anatomy(list(reversed(rows))), sort_keys=True
        )


class TestAlignedMask:
    def test_missing_production_columns_returns_none(self):
        ev = pd.DataFrame([{"fillable": True, "regime": "normal"}])
        assert aligned_mask(ev) is None

    def test_full_columns_mask_excludes_flagged_rows(self):
        from scripts.review_btst_prior_court import PRODUCTION_EXCLUDE_COLS

        base = {
            "fillable": True,
            "gate_blocked": False,
            "price_ge_3": True,
            "gross_ret_t10": 0.05,
            **{c: False for c in PRODUCTION_EXCLUDE_COLS},
        }
        ev = pd.DataFrame([base, {**base, "st_name": True}])
        mask = aligned_mask(ev)
        assert list(mask) == [True, False]


class TestUniverseEndToEnd:
    def test_analyze_universe_fixture(self, tmp_path):
        from scripts.btst_exit_anatomy import analyze_universe

        sessions = CAL[:11]
        rows = []
        frames = {s: [] for s in sessions}
        prev_close: dict[str, float] = {}
        for j, ts in enumerate(("000001.SZ", "000002.SZ")):
            rows.append(
                {
                    "ts_code": ts,
                    "symbol": ts[:6],
                    "signal_date": sessions[0],
                    "regime": "normal" if j == 0 else "crisis",
                    "trigger_strength": 0.7,
                    "signal_close": 10.0,
                    "gap_t1_open": 0.01,  # T+1 open 10.1 = 10×(1+0.01)
                    "exit_session_t10": 10,  # 偏移量: signal 后第 10 个会话
                    "gross_ret_t10": 0.05,
                    "fillable": True,
                    "gate_blocked": False,
                }
            )
        for i, s in enumerate(sessions):
            for ts in ("000001.SZ", "000002.SZ"):
                px = 10.0 * (1 + 0.01 * i)
                frames[s].append(
                    {
                        "ts_code": ts,
                        "open": px,
                        "high": px * 1.02,
                        "low": px * 0.98,
                        "close": px,
                        "pre_close": prev_close.get(ts, px),  # 交易所 pre_close=前收盘
                    }
                )
                prev_close[ts] = px
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        for s in sessions:
            pd.DataFrame(frames[s]).to_csv(raw_dir / f"daily_{s}.csv", index=False)
        ev = pd.DataFrame(rows)
        payload = analyze_universe(ev, raw_dir, CAL)
        allc = payload["all_candidates"]
        assert allc["n_events"] == 2
        assert allc["n_included"] == 2
        assert allc["mfe"]["p50"] > 0
        assert allc["stop_grid"]["-10%"]["n_stopped"] == 0  # 单调上行路径不触发
        assert set(payload["by_regime"]) == {"crisis", "normal"}

    def test_render_md_includes_stop_table(self):
        rows = [
            {
                "mfe": 0.2,
                "mae": -0.1,
                "time_to_peak": 0,
                "time_to_trough": 1,
                "realizable_sessions": 9,
                "observed_sessions": 9,
                "contract_exit_net": 0.03,
                "signal_date": "d",
                "stops": {
                    f"{p:.0%}": {
                        "stopped": False,
                        "reason": "contract_exit",
                        "session": "d",
                        "fill": 1.0,
                        "net": 0.02,
                    }
                    for p in STOP_GRID_PCT
                },
            }
        ]
        payload = {
            "u": {
                "all_candidates": aggregate_anatomy(rows),
                "production_aligned": {"skipped": "production_filter_columns_missing"},
                "by_regime": {"normal": aggregate_anatomy(rows)},
            }
        }
        text = render_md(payload)
        assert "无止损(基准)" in text
        assert "-5%" in text
        assert "regime=normal" in text
        assert "skipped" in text
