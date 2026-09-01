"""btst_horizon_curve — 纯函数 + fixture 端到端 (第九十五轮 Op5).

钉死的正确性面: 顺延语义 (fixed_open 同款)、corp-action 排除、t10 哨点、
MIN_CELL_N 纪律、确定性。
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts.btst_horizon_curve import (
    FORWARD_SESSIONS,
    HORIZONS,
    PRIMARY_K,
    T10_CROSSCHECK_TOL,
    aggregate_curve,
    event_horizon_gross,
    win_loss_stats,
)


def _cal(n=30):
    from datetime import date, timedelta

    d0 = date(2026, 1, 5)
    out = []
    while len(out) < n:
        if d0.weekday() < 5:
            out.append(d0.strftime("%Y%m%d"))
        d0 += timedelta(days=1)
    return out


CAL = _cal()


def _bars(entry=10.0, sessions=FORWARD_SESSIONS, pattern=None):
    """T+1 起逐日 bars; pattern[i] = 第 i+1 天的倍率 (None = 停牌缺 bar)。"""
    bars = []
    prev = entry
    for i in range(sessions):
        if pattern is not None and pattern[i] is None:
            bars.append(
                {
                    "session": CAL[1 + i],
                    "open": None,
                    "high": None,
                    "low": None,
                    "close": None,
                    "pre_close": None,
                }
            )
            continue
        px = entry if pattern is None else entry * pattern[i]
        bars.append(
            {
                "session": CAL[1 + i],
                "open": px,
                "high": px * 1.01,
                "low": px * 0.99,
                "close": px,
                "pre_close": prev,
            }
        )
        prev = px
    return bars


def _by_day(bars, ts_code="000001.SZ"):
    frames = {}
    for b in bars:
        frames.setdefault(
            b["session"],
            pd.DataFrame(
                [
                    {
                        "ts_code": ts_code,
                        "open": b["open"],
                        "high": b["high"],
                        "low": b["low"],
                        "close": b["close"],
                        "pre_close": b["pre_close"],
                    }
                ]
            ),
        )
    return frames


def _event(gap=0.0, gross_t10=0.0, exit_offset=10, ts_code="000001.SZ"):
    return pd.Series(
        {
            "ts_code": ts_code,
            "signal_date": CAL[0],
            "exit_session_t10": exit_offset,
            "gross_ret_t10": gross_t10,
            "signal_close": 10.0,
            "gap_t1_open": gap,
        }
    )


class TestForwardExtendSemantics:
    def test_t2_exit_uses_t2_open(self):
        bars = _bars(pattern=[1.0, 1.02] + [1.0] * 13)
        out = event_horizon_gross(_event(), _by_day(bars), CAL)
        assert out[2] == pytest.approx(0.02)

    def test_suspension_extends_to_next_available_open(self):
        """T+2 停牌 → t2 顺延到 T+3 开盘 (fixed_open 同款)。"""
        bars = _bars(pattern=[1.0, None, 1.03] + [1.0] * 12)
        out = event_horizon_gross(_event(), _by_day(bars), CAL)
        assert out[2] == pytest.approx(0.03)
        assert out[3] == pytest.approx(0.03)

    def test_window_end_without_bar_leaves_k_absent(self):
        """尾部停牌 (T+5..T+15 缺 bar): 可用 k=2..4, 其后缺席 (unexited 披露)。"""
        pattern = [1.0] * 4 + [None] * 11
        bars = _bars(pattern=pattern)
        out = event_horizon_gross(_event(), _by_day(bars), CAL)
        assert 4 in out and 5 not in out and 15 not in out

    def test_all_horizons_covered_when_no_suspension(self):
        bars = _bars()
        out = event_horizon_gross(_event(), _by_day(bars), CAL)
        assert sorted(out.keys()) == list(HORIZONS)


class TestT10Sentinel:
    def test_matches_table_gross(self):
        bars = _bars()  # 平价路径 → t10 毛 = 0
        out = event_horizon_gross(_event(gross_t10=0.0), _by_day(bars), CAL)
        assert out[PRIMARY_K] == pytest.approx(0.0)

    def test_mismatch_fail_closed(self):
        # 入场日平价 (entry 一致), t10 实际 +1% 但事件表报 0 → 哨点拦截
        pattern = [1.0] * 9 + [1.01] + [1.0] * 5
        bars = _bars(pattern=pattern)
        out = event_horizon_gross(
            _event(gross_t10=0.0), _by_day(bars), CAL
        )
        assert out == {"excluded_t10_sentinel_mismatch": True}

    def test_table_nan_with_computed_t10_rejected(self):
        bars = _bars()
        out = event_horizon_gross(
            _event(gross_t10=float("nan")), _by_day(bars), CAL
        )
        assert out == {"excluded_t10_sentinel_mismatch": True}

    def test_tolerance_is_tight(self):
        assert T10_CROSSCHECK_TOL <= 1e-9


class TestExclusions:
    def test_unfilled_offset(self):
        out = event_horizon_gross(
            _event(exit_offset=float("nan")), _by_day(_bars()), CAL
        )
        assert out == {"excluded_exit_unfilled": True}

    def test_corp_action_excluded_whole_event(self):
        bars = _bars()
        bars[5]["pre_close"] = bars[4]["close"] * 0.5
        out = event_horizon_gross(_event(), _by_day(bars), CAL)
        assert "excluded_corp_action" in out

    def test_t1_missing(self):
        bars = _bars()
        bars[0]["open"] = None
        out = event_horizon_gross(_event(), _by_day(bars), CAL)
        assert out == {"excluded_t1_bar_missing": True}


class TestAggregate:
    def test_net_applies_roundtrip_and_unexited_counts(self):
        grids = [{2: 0.10, PRIMARY_K: 0.05}, {2: -0.02, PRIMARY_K: 0.05}]
        days = [{2: "d1", PRIMARY_K: "d1"}, {2: "d2", PRIMARY_K: "d2"}]
        rows = aggregate_curve(grids, days)
        by_k = {r["k"]: r for r in rows}
        assert by_k[2]["expectancy"] == pytest.approx((0.10 - 0.02) / 2 - 0.0065)
        assert by_k[2]["n"] == 2
        assert by_k[15]["n"] == 0 and by_k[15]["unexited"] == 2
        assert by_k[15]["expectancy"] is None

    def test_ci_suppressed_below_min_cell_n(self):
        grids = [{2: 0.01} for _ in range(5)]  # n=5 < MIN_CELL_N=30
        days = [{2: "d1"} for _ in range(5)]
        rows = aggregate_curve(grids, days)
        assert rows[0]["ci90_low"] is None

    def test_deterministic(self):
        grids = [{2: 0.01 * ((i * 7) % 13 - 6), 3: 0.02} for i in range(40)]
        days = [{2: f"d{i % 8}", 3: f"d{i % 8}"} for i in range(40)]
        a = json.dumps(aggregate_curve(grids, days), sort_keys=True)
        b = json.dumps(aggregate_curve(list(reversed(grids)), list(reversed(days))), sort_keys=True)
        assert a == b


class TestWinLossStatsDelegate:
    def test_matches_decomposition_single_implementation(self):
        from scripts.winrate_payoff_decomposition import (
            win_loss_stats as table_impl,
        )

        assert win_loss_stats is table_impl


class TestEndToEnd:
    def test_analyze_universe_fixture(self, tmp_path):
        from scripts.btst_horizon_curve import analyze_universe

        sessions = CAL[:16]
        frames = {}
        prev = {}
        # 价格路径: signal 日 10.0, T+1 起 10.1×(1+0.001·(i-1)) 加性上行
        for i, s in enumerate(sessions):
            frame_rows = []
            for ts in ("000001.SZ", "000002.SZ"):
                px = 10.0 if i == 0 else 10.1 * (1 + 0.001 * (i - 1))
                frame_rows.append(
                    {
                        "ts_code": ts,
                        "open": px,
                        "high": px * 1.01,
                        "low": px * 0.99,
                        "close": px,
                        "pre_close": prev.get(ts, px),
                    }
                )
                prev[ts] = px
            frames[s] = pd.DataFrame(frame_rows)
        t1_px = 10.1 * (1 + 0.001 * 0)
        t10_px = 10.1 * (1 + 0.001 * 9)
        gross_t10 = t10_px / t1_px - 1  # 与工具同源计算, 哨点必过
        rows = []
        for j, ts in enumerate(("000001.SZ", "000002.SZ")):
            rows.append(
                {
                    "ts_code": ts,
                    "signal_date": sessions[0],
                    "regime": "normal",
                    "trigger_strength": 0.7,
                    "signal_close": 10.0,
                    "gap_t1_open": t1_px / 10.0 - 1,
                    "exit_session_t10": 10,
                    "gross_ret_t10": gross_t10,
                    "fillable": True,
                    "gate_blocked": False,
                }
            )
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        for s in sessions:
            frames[s].to_csv(raw_dir / f"daily_{s}.csv", index=False)
        ev = pd.DataFrame(rows)
        payload = analyze_universe(ev, raw_dir, CAL)
        curve = payload["all_candidates"]["curve"]
        by_k = {r["k"]: r for r in curve}
        assert by_k[15]["n"] == 2
        assert by_k[15]["expectancy"] > by_k[2]["expectancy"]  # 单调上行路径
        assert payload["all_candidates"]["exclusions"] == {}
        aligned = payload["production_aligned"]
        assert "skipped" in aligned  # fixture 未带生产过滤列 → 口径缺位诚实披露

    def test_render_md_has_curve_columns(self):
        from scripts.btst_horizon_curve import render_md

        payload = {
            "u": {
                "all_candidates": {
                    "n_events": 2,
                    "curve": [
                        {
                            "k": 2,
                            "n": 2,
                            "unexited": 0,
                            "winrate": 0.5,
                            "avg_win": 0.1,
                            "avg_loss": -0.05,
                            "payoff": 2.0,
                            "expectancy": 0.02,
                            "ci90_low": -0.01,
                        }
                    ],
                    "exclusions": {},
                },
                "production_aligned": {
                    "skipped": "production_filter_columns_missing"
                },
            }
        }
        text = render_md(payload)
        assert "| k | n | unexited |" in text
        assert "| t2 | 2 | 0 |" in text
        assert "skipped" in text


class TestAdversarialReview:
    """R95 Op7 对抗性审查返工的三处回归钉死。"""

    def test_aligned_subset_stays_aligned_with_exclusions_present(self):
        """排除事件夹在中间时, production_aligned 仍选对事件 (A13 错位 PoC)。

        构造: 3 事件, 第 2 个 t10 哨点失配 (被排除), 第 1/3 个生产对齐干净。
        修复前: mask 与 per_event 错位 → aligned 错取第 1/2 个。
        """
        import tempfile
        from pathlib import Path

        from scripts.btst_horizon_curve import analyze_universe

        sessions = CAL[:16]
        rows = []
        frames = {s: [] for s in sessions}
        prev = {}
        # 事件 A (干净, 对齐), B (哨点失配 → 排除), C (干净, 非 prod: st_name)
        specs = [
            ("000001.SZ", False, None),
            ("000002.SZ", False, 0.99),  # gross_t10 错位 → 哨点排除
            ("000003.SZ", True, None),   # st_name → 非生产对齐
        ]
        for ts, st_flag, wrong_gross in specs:
            gross = 0.05 if wrong_gross is None else wrong_gross
            rows.append(
                {
                    "ts_code": ts,
                    "signal_date": sessions[0],
                    "regime": "normal",
                    "trigger_strength": 0.7,
                    "signal_close": 10.0,
                    "gap_t1_open": 0.0,
                    "exit_session_t10": 10,
                    "gross_ret_t10": gross,
                    "fillable": True,
                    "gate_blocked": False,
                    "price_ge_3": True,
                    "degraded": False,
                    "st_name": st_flag,
                    "industry_missing": False,
                    "excluded_ticker": False,
                }
            )
        for i, s in enumerate(sessions):
            for ts, _, _ in specs:
                px = 10.0  # 平价路径: t10 毛 = 0, 与 A/C 表值一致
                frames[s].append(
                    {
                        "ts_code": ts,
                        "open": px,
                        "high": px * 1.01,
                        "low": px * 0.99,
                        "close": px,
                        "pre_close": prev.get(ts, px),
                    }
                )
                prev[ts] = px
        raw_dir = Path(tempfile.mkdtemp()) / "raw"
        raw_dir.mkdir(parents=True)
        for s in sessions:
            pd.DataFrame(frames[s]).to_csv(raw_dir / f"daily_{s}.csv", index=False)
        # 平价路径: t10 毛 = 0; 事件 A/C 报 0.05 → 哨点也会拦! 改 A/C 报 0
        for r in rows:
            if r["gross_ret_t10"] == 0.05:
                r["gross_ret_t10"] = 0.0
        # 事件 B 保留 0.99 (失配 → 排除)
        ev = pd.DataFrame(rows)
        payload = analyze_universe(ev, raw_dir, CAL)
        aligned = payload["production_aligned"]
        # aligned 只含事件 A (事件 C 被 st_name 排除, B 被哨点排除)
        assert aligned["n_events"] == 1
        curve_t15 = next(r for r in aligned["curve"] if r["k"] == 15)
        assert curve_t15["n"] == 1

    def test_empty_grid_excluded_without_crash(self):
        """T+2.. 全停牌 → 空 grid 显式排除类, 不抛 StopIteration (A2)。"""
        pattern = [1.0] + [None] * 14
        bars = _bars(pattern=pattern)
        out = event_horizon_gross(_event(gross_t10=0.0), _by_day(bars), CAL)
        # t10 无 bar → 哨点不触发 (PRIMARY_K not in out), 返回空 grid
        assert out == {}

    def test_main_smoke_with_injected_calendar(self, tmp_path, monkeypatch):
        """main 层冒烟 (A14): CLI 层不再零覆盖。"""
        import scripts.btst_horizon_curve as mod

        sessions = CAL[:16]
        ev = pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "signal_date": sessions[0],
                    "regime": "normal",
                    "trigger_strength": 0.7,
                    "signal_close": 10.0,
                    "gap_t1_open": 0.0,
                    "exit_session_t10": 10,
                    "gross_ret_t10": 0.0,
                    "fillable": True,
                    "gate_blocked": False,
                }
            ]
        )
        table = tmp_path / "event_table_v1.csv.gz"
        ev.to_csv(table, index=False)
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        frames = {s: [] for s in sessions}
        for i, s in enumerate(sessions):
            px = 10.0
            frames[s].append(
                {
                    "ts_code": "000001.SZ",
                    "open": px,
                    "high": px,
                    "low": px,
                    "close": px,
                    "pre_close": px,
                }
            )
            pd.DataFrame(frames[s]).to_csv(raw_dir / f"daily_{s}.csv", index=False)
        out_json = tmp_path / "out.json"
        monkeypatch.setattr(
            mod, "load_sessions", lambda start, end: list(CAL)
        )
        monkeypatch.setattr(
            "sys.argv",
            [
                "btst_horizon_curve.py",
                "--event-table", str(table),
                "--event-table-early", str(table),
                "--raw-dir", str(raw_dir),
                "--raw-dir-early", str(raw_dir),
                "--output-json", str(out_json),
            ],
        )
        assert mod.main() == 0
        payload = json.loads(out_json.read_text())
        assert payload["production"]["all_candidates"]["curve"][0]["n"] == 1
