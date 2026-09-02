"""btst_holding_evidence — 纯函数 + fixture 端到端 (第一百零一轮 Op1).

钉死的正确性面: 共享交集配对 (选择效应消元)、嵌套性 (k>10 ⊆ k=10)、
边际对数增速、对齐基线漂移、split-half 符号合取、R15 资格判据、
CI 确定性 (per-call seeded, R13)、log 域 fail-closed、渲染。
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd
import pytest

from scripts.btst_holding_evidence import (
    FOCUS_KS,
    PRIMARY_K,
    ROUNDTRIP_COST,
    _spearman,
    aligned_baseline_drift,
    analyze_universe,
    paired_rows,
    paired_summary,
    qualification,
    render_md,
    split_half_verdict,
)
from scripts.winrate_payoff_decomposition import MIN_CELL_N


def _cal(n=60):
    d0 = date(2026, 1, 5)
    out = []
    while len(out) < n:
        if d0.weekday() < 5:
            out.append(d0.strftime("%Y%m%d"))
        d0 += timedelta(days=1)
    return out


CAL = _cal()


def _extras(regime="normal", strength=0.55):
    return {"regime": regime, "strength": strength}


class TestPairedRows:
    def test_intersection_excludes_events_without_k(self):
        """含 10 不含 14 的事件被排除出 k=14 配对 (选择效应消元核心)。"""
        grids = [{10: 0.10, 14: 0.14}, {10: 0.05}]
        rows = paired_rows(grids, ["20260105", "20260106"], [_extras(), _extras()], 14)
        assert rows is not None and len(rows) == 1
        # d = (0.14 − cost) − (0.10 − cost) = 0.04 (成本在配对内消去)
        assert rows[0]["d"] == pytest.approx(0.04)

    def test_cost_cancels_in_pairing(self):
        grids = [{10: 0.0, 14: 0.0}]
        rows = paired_rows(grids, ["20260105"], [_extras()], 14)
        assert rows[0]["d"] == pytest.approx(0.0)

    def test_nesting_k_above_10_implied(self):
        """k>10: 构造中含 14 的 grid 必含 10 — 配对行数 == 含 14 的事件数。"""
        grids = [{10: 0.1, 14: 0.2}, {10: 0.1, 14: 0.3}, {10: 0.1}]
        rows = paired_rows(grids, ["d1", "d2", "d3"], [_extras()] * 3, 14)
        assert rows is not None and len(rows) == 2

    def test_k_below_10_pairs_on_shared_grid(self):
        """k<10: 交集 = 同含 k 与 10 (长期停牌使 t10 缺席时 t2 也不配对)。"""
        grids = [{2: 0.01, 10: 0.10, 14: 0.2}, {2: 0.02}]  # 第二事件无 t10
        rows = paired_rows(grids, ["d1", "d2"], [_extras()] * 2, 2)
        assert rows is not None and len(rows) == 1
        assert rows[0]["d"] == pytest.approx(0.01 - 0.10)

    def test_illegal_k_returns_none(self):
        grids = [{10: 0.1}]
        assert paired_rows(grids, ["d"], [_extras()], PRIMARY_K) is None
        assert paired_rows(grids, ["d"], [_extras()], 1) is None
        assert paired_rows(grids, ["d"], [_extras()], 16) is None

    def test_log_d_exact(self):
        grids = [{10: 0.0, 14: 0.1}]
        rows = paired_rows(grids, ["d"], [_extras()], 14)
        assert rows[0]["log_d"] == pytest.approx(math.log1p(0.1 - ROUNDTRIP_COST) - math.log1p(-ROUNDTRIP_COST))

    def test_extras_carried_through(self):
        grids = [{10: 0.1, 14: 0.2}]
        rows = paired_rows(grids, ["d"], [_extras(regime="crisis", strength=0.75)], 14)
        assert rows[0]["regime"] == "crisis"
        assert rows[0]["strength"] == 0.75


class TestPairedSummary:
    def test_mean_and_marginal_log_exact(self):
        grids = [
            {10: 0.0, 14: 0.08},
            {10: 0.02, 14: 0.10},
        ]
        rows = paired_rows(grids, ["d1", "d2"], [_extras()] * 2, 14)
        s = paired_summary(rows, 14)
        d1 = 0.08 - 0.0
        d2 = 0.10 - 0.02
        assert s["n"] == 2
        assert s["mean_d"] == pytest.approx((d1 + d2) / 2)
        lg1 = math.log1p(0.08 - ROUNDTRIP_COST) - math.log1p(0.0 - ROUNDTRIP_COST)
        lg2 = math.log1p(0.10 - ROUNDTRIP_COST) - math.log1p(0.02 - ROUNDTRIP_COST)
        assert s["marginal_log_per_day"] == pytest.approx(((lg1 + lg2) / 2) / (14 - 10))

    def test_below_min_n_ci_is_none(self):
        grids = [{10: 0.0, 14: 0.08}] * (MIN_CELL_N - 1)
        days = [f"d{i}" for i in range(MIN_CELL_N - 1)]
        rows = paired_rows(grids, days, [_extras()] * (MIN_CELL_N - 1), 14)
        assert paired_summary(rows, 14)["ci90_low"] is None

    def test_ci_deterministic_across_calls(self):
        """R13 纪律: per-call seeded RNG — 同输入两次调用 CI 逐位相同。"""
        grids = [{10: 0.0, 14: 0.01 * (i % 7)} for i in range(MIN_CELL_N + 5)]
        days = [f"d{i % 10}" for i in range(MIN_CELL_N + 5)]
        rows1 = paired_rows(grids, days, [_extras()] * (MIN_CELL_N + 5), 14)
        rows2 = paired_rows(grids, days, [_extras()] * (MIN_CELL_N + 5), 14)
        assert paired_summary(rows1, 14)["ci90_low"] == paired_summary(rows2, 14)["ci90_low"]

    def test_empty_rows(self):
        s = paired_summary([], 14)
        assert s["n"] == 0
        assert s["mean_d"] is None
        assert s["ci90_low"] is None
        assert s["marginal_log_per_day"] is None


class TestLogDomain:
    def test_gross_at_minus_one_fails_closed(self):
        """净收益 ≤ −100% (open=0, 现实不可能) → ValueError fail-closed,
        在配对构造处即 raise, 不静默产出 −inf。"""
        grids = [{10: 0.0, 14: -1.0}]
        with pytest.raises(ValueError):
            paired_rows(grids, ["d"], [_extras()], 14)

    def test_gross_just_above_minus_one_computes(self):
        grids = [{10: -0.99, 14: -0.5}]
        rows = paired_rows(grids, ["d"], [_extras()], 14)
        s = paired_summary(rows, 14)
        assert s["mean_d"] == pytest.approx(0.49)


class TestAlignedBaselineDrift:
    def test_drift_exact_and_counts(self):
        """净口径: e10 = gross − ROUNDTRIP_COST。"""
        grids = [{10: 0.0, 14: 0.10}, {10: 0.02, 14: 0.12}, {10: -0.04}]
        days = ["d1", "d2", "d3"]
        out = aligned_baseline_drift(grids, days, 14)
        assert out is not None
        assert out["n_full"] == 3
        assert out["n_aligned"] == 2
        assert out["e10_full"] == pytest.approx((0.0 + 0.02 - 0.04) / 3 - ROUNDTRIP_COST)
        assert out["e10_aligned"] == pytest.approx((0.0 + 0.02) / 2 - ROUNDTRIP_COST)
        assert out["drift"] == pytest.approx(out["e10_aligned"] - out["e10_full"])

    def test_illegal_k_none(self):
        assert aligned_baseline_drift([{10: 0.1}], ["d"], PRIMARY_K) is None


class TestSplitHalf:
    def _rows(self, ds, days):
        return [{"d": d, "day": day} for d, day in zip(ds, days)]

    def test_consistent_signs_true(self):
        rows = self._rows([0.05, -0.02, 0.03, 0.01], ["d1", "d1", "d2", "d2"])
        v = split_half_verdict(rows, ["d1", "d2"])
        assert v["sign_consistent"] is True
        assert v["mean_d_first"] == pytest.approx(0.015)
        assert v["mean_d_second"] == pytest.approx(0.02)

    def test_flipped_signs_false(self):
        rows = self._rows([0.05, 0.05, -0.01, -0.02], ["d1", "d1", "d2", "d2"])
        assert split_half_verdict(rows, ["d1", "d2"])["sign_consistent"] is False

    def test_single_day_not_judged(self):
        rows = self._rows([0.01, 0.02], ["d1", "d1"])
        v = split_half_verdict(rows, ["d1"])
        assert v["sign_consistent"] is None
        assert v["reason"] == "single_day"

    def test_empty_input(self):
        v = split_half_verdict([], [])
        assert v["sign_consistent"] is None


class TestSpearman:
    def test_monotonic_perfect(self):
        assert _spearman([1.0, 2.0, 3.0], [10.0, 20.0, 30.0]) == pytest.approx(1.0)

    def test_anti_monotonic(self):
        assert _spearman([1.0, 2.0, 3.0], [30.0, 20.0, 10.0]) == pytest.approx(-1.0)

    def test_ties_average_ranks(self):
        # a = [1, 2, 2], b = [1, 2, 3]: ranks a = [1, 2.5, 2.5], b = [1, 2, 3]
        # ρ = 1 − 6×(0.25+0.25)/(3×8) = 0.875
        assert _spearman([1.0, 2.0, 2.0], [1.0, 2.0, 3.0]) == pytest.approx(0.875)

    def test_two_points_gives_pm1(self):
        assert _spearman([1.0, 2.0], [5.0, 7.0]) == pytest.approx(1.0)

    def test_insufficient_returns_none(self):
        assert _spearman([1.0], [1.0]) is None
        assert _spearman([], []) is None


class TestQualification:
    def _supported(self, k):
        return (
            {k: {"ci90_low": 0.001, "mean_d": 0.01}},
            {k: {"sign_consistent": True, "mean_d_first": 0.01, "mean_d_second": 0.01}},
        )

    def test_all_supported_qualified_with_two_focus(self):
        s12, p12 = self._supported(12)
        s14, p14 = self._supported(14)
        q = qualification({**s12, **s14}, {**p12, **p14})
        assert q["qualified"] is True
        assert q["per_k"] == {"12": "supported", "14": "supported"}
        assert q["spearman_halves"] is None  # 2 焦点排序不可估, 如实 None

    def test_ci_none_marks_insufficient(self):
        s = {12: {"ci90_low": None, "mean_d": 0.01}, 14: {"ci90_low": 0.001, "mean_d": 0.01}}
        p = {12: {"sign_consistent": True}, 14: {"sign_consistent": True}}
        q = qualification(s, p)
        assert q["qualified"] is False
        assert q["per_k"]["12"] == "insufficient_n"

    def test_sign_flip_not_supported(self):
        s = {12: {"ci90_low": 0.001, "mean_d": 0.01}, 14: {"ci90_low": 0.001, "mean_d": 0.01}}
        p = {12: {"sign_consistent": True}, 14: {"sign_consistent": False}}
        q = qualification(s, p)
        assert q["qualified"] is False
        assert q["per_k"]["14"] == "not_supported"

    def test_three_focus_spearman_gate(self, monkeypatch):
        import scripts.btst_holding_evidence as m

        monkeypatch.setattr(m, "FOCUS_KS", (11, 12, 14))
        s = {k: {"ci90_low": 0.001, "mean_d": 0.01} for k in (11, 12, 14)}
        # 两半排序一致 (k 递增 mean_d 递增) → Spearman 1 → qualified
        halves_ok = {
            k: {"sign_consistent": True, "mean_d_first": 0.01 * k, "mean_d_second": 0.01 * k}
            for k in (11, 12, 14)
        }
        q = m.qualification(s, halves_ok)
        assert q["spearman_halves"] == pytest.approx(1.0)
        assert q["qualified"] is True
        # 两半排序翻转: 前半 11 最高 / 后半 11 最低 → Spearman −0.5 → 不合格
        halves_flip = dict(halves_ok)
        halves_flip[11] = {
            "sign_consistent": True,
            "mean_d_first": 0.30,
            "mean_d_second": 0.01,
        }
        q2 = m.qualification(s, halves_flip)
        assert q2["spearman_halves"] < m.SPEARMAN_MIN
        assert q2["qualified"] is False


# ---------------------------------------------------------------------------
# fixture 端到端 (落盘 event table + daily bars, 镜像真实管道格式)
# ---------------------------------------------------------------------------


def _write_event_table(path, rows):
    frame = pd.DataFrame(rows)
    frame.to_csv(path, index=False)
    return frame


def _write_daily(path, ts_code, opens, entry=10.0):
    rows = []
    prev = entry
    for px in opens:
        rows.append(
            {
                "ts_code": ts_code,
                "open": px,
                "high": px * 1.01,
                "low": px * 0.99,
                "close": px,
                "pre_close": prev,
            }
        )
        prev = px
    pd.DataFrame(rows).to_csv(path, index=False)


def _event_row(
    ts_code,
    signal_date,
    opens,
    entry=10.0,
    regime="normal",
    strength=0.55,
    fillable=True,
):
    """opens[i] = T+(i+1) 开盘价; None = 停牌。exit_session_t10/gross_ret_t10
    按 fixed_open 语义推导 (与 build 层一致)。"""
    avail = [(i + 1, px) for i, px in enumerate(opens) if px is not None]
    e10 = next((px for off, px in avail if off >= 10), None)
    exit_off = next((off for off, px in avail if off >= 10), None)
    return {
        "ts_code": ts_code,
        "signal_date": signal_date,
        "regime": regime,
        "trigger_strength": strength,
        "signal_close": entry,
        "gap_t1_open": (opens[0] / entry - 1) if opens[0] is not None else 0.0,
        "exit_session_t10": exit_off if exit_off is not None else float("nan"),
        "gross_ret_t10": (e10 / entry - 1) if e10 is not None else float("nan"),
        "fillable": fillable,
        "gate_blocked": False,
        "price_ge_3": True,
        "degraded": False,
        "st_name": False,
        "industry_missing": False,
        "excluded_ticker": False,
    }


class TestEndToEnd:
    @staticmethod
    def _make_world(tmp_path, opens_fn, n_events, signal_day=lambda i: CAL[i % 10], strength_fn=lambda i: 0.6):
        """构造完整世界: 事件表 + 按 (ts, session) 聚合的日线快照。

        pre_close 链逐事件维护 (detect_corp_action 依赖: pre_close 必须等于
        前一 bar 的 close, 否则整事件被 corp-action 排除 — 真实数据语义)。
        """
        raw_dir = tmp_path / "daily"
        raw_dir.mkdir()
        bars_by_session: dict[str, list] = {}
        rows = []
        for i in range(n_events):
            ts = f"{40000 + i:06d}.SZ"
            day = signal_day(i)
            entry = 10.0
            opens = opens_fn(i, entry)
            avail = [(j + 1, px) for j, px in enumerate(opens) if px is not None]
            # 事件表语义: gross_ret_t10 相对 T+1 开盘入场价 (与 build 层一致)
            entry_open = opens[0]
            e10 = next((px for off, px in avail if off >= 10), None)
            exit_off = next((off for off, _ in avail if off >= 10), None)
            rows.append(
                {
                    "ts_code": ts,
                    "signal_date": day,
                    "regime": "normal",
                    "trigger_strength": strength_fn(i),
                    "signal_close": entry,
                    "gap_t1_open": (opens[0] / entry - 1) if opens[0] is not None else 0.0,
                    "exit_session_t10": exit_off if exit_off is not None else float("nan"),
                    "gross_ret_t10": (
                        (e10 / entry_open - 1) if (e10 is not None and entry_open is not None) else float("nan")
                    ),
                    "fillable": True,
                    "gate_blocked": False,
                    "price_ge_3": True,
                    "degraded": False,
                    "st_name": False,
                    "industry_missing": False,
                    "excluded_ticker": False,
                }
            )
            prev = entry
            for j, px in enumerate(opens):
                if px is None:
                    continue
                sess = CAL[CAL.index(day) + 1 + j]
                bars_by_session.setdefault(sess, []).append((ts, px, prev))
                prev = px
        for sess, items in bars_by_session.items():
            pd.DataFrame(
                [
                    {
                        "ts_code": ts,
                        "open": px,
                        "high": px * 1.01,
                        "low": px * 0.99,
                        "close": px,
                        "pre_close": prev_close,
                    }
                    for ts, px, prev_close in items
                ]
            ).to_csv(raw_dir / f"daily_{sess}.csv", index=False)
        table = tmp_path / "events.csv"
        pd.DataFrame(rows).to_csv(table, index=False)
        return table, raw_dir

    def test_world_construction_and_pairing(self, tmp_path):
        """端到端: 交集构造 + 排除计数 + t10 基线行 + 资格判定的形状。

        世界: 32 个完整 15-bar 上升趋势事件 + 1 个尾部停牌事件
        (仅 10 bar → t11+ 缺席, unexited 披露)。
        """
        table, raw_dir = self._make_world(
            tmp_path,
            opens_fn=lambda i, entry: [entry * (1 + 0.005 * (j + 1)) for j in range(15)],
            n_events=32,
            signal_day=lambda i: CAL[i],
            strength_fn=lambda i: 0.55 + 0.01 * (i % 3),
        )
        # 追加尾部停牌事件 (仅 10 bar)
        ev_extra = pd.DataFrame(
            [
                {
                    "ts_code": "399999.SZ",
                    "signal_date": CAL[5],
                    "regime": "normal",
                    "trigger_strength": 0.4,
                    "signal_close": 10.0,
                    "gap_t1_open": 0.0,
                    "exit_session_t10": 10,
                    "gross_ret_t10": 0.0,
                    "fillable": True,
                    "gate_blocked": False,
                    "price_ge_3": True,
                    "degraded": False,
                    "st_name": False,
                    "industry_missing": False,
                    "excluded_ticker": False,
                }
            ]
        )
        ev_extra.to_csv(table, mode="a", header=False, index=False)
        # flat 事件 bars 追加进既有 session 文件 (勿覆盖聚合快照)
        flat = pd.DataFrame(
            [
                {
                    "ts_code": "399999.SZ",
                    "open": 10.0,
                    "high": 10.1,
                    "low": 9.9,
                    "close": 10.0,
                    "pre_close": 10.0,
                }
            ]
        )
        for j in range(10):
            flat.to_csv(raw_dir / f"daily_{CAL[5 + 1 + j]}.csv", mode="a", header=False, index=False)

        ev = pd.read_csv(table, dtype={"signal_date": str})
        payload = analyze_universe(ev, raw_dir, CAL)

        for scope in ("all_candidates", "production_aligned"):
            agg = payload[scope]
            # 33 事件全部可退 t10 (完整 bar) — t10 行 n=33
            t10 = next(r for r in agg["curve"] if r["k"] == PRIMARY_K)
            assert t10["n"] == 33
            # t14: 32 个完整 15-bar 事件 (ts3 只有 10 bar, 无 t14)
            t14 = next(r for r in agg["curve"] if r["k"] == 14)
            assert t14["n"] == 32
            # 上升趋势世界: 持有更久 d>0
            assert t14["mean_d"] > 0
            # 对齐基线漂移披露存在且 k 正确
            assert any(d["k"] == 14 for d in agg["baseline_drift"])
            # 资格判定: 单调上升世界 n=33 ≥ 30 → CI>0 + 同号 → supported + qualified
            assert agg["qualification"]["per_k"] == {"12": "supported", "14": "supported"}
            assert agg["qualification"]["qualified"] is True
        md = render_md({"production": payload})
        assert "BTST 持有期配对差证据包" in md
        assert "t14 *" in md  # 焦点标记
        assert "资格判定" in md

    def test_min_n_ci_present_with_large_world(self, tmp_path):
        """MIN_CELL_N 以上世界: CI 非 None + split-half 判定真值 + qualified。"""
        n_events = MIN_CELL_N + 5
        table, raw_dir = self._make_world(
            tmp_path,
            opens_fn=lambda i, entry: [entry * (1 + 0.004 * (j + 1)) for j in range(15)],
            n_events=n_events,
        )
        ev = pd.read_csv(table, dtype={"signal_date": str})
        payload = analyze_universe(ev, raw_dir, CAL)
        agg = payload["all_candidates"]
        t14 = next(r for r in agg["curve"] if r["k"] == 14)
        assert t14["n"] == n_events
        assert t14["ci90_low"] is not None
        # 单调上升世界: t12/t14 CI 均为正且 split-half 同号 → qualified
        assert agg["qualification"]["qualified"] is True
        assert agg["split_half"]["14"]["sign_consistent"] is True

    def test_crash_world_qualified_false(self, tmp_path):
        """先涨后崩世界: t11+ 深跌 → mean_d 为负 → not qualified。"""
        def opens_fn(i, entry):
            return [entry * (1 + 0.01 * min(j + 1, 8) - 0.02 * max(0, j - 7)) for j in range(15)]

        table, raw_dir = self._make_world(tmp_path, opens_fn=opens_fn, n_events=MIN_CELL_N + 5)
        ev = pd.read_csv(table, dtype={"signal_date": str})
        payload = analyze_universe(ev, raw_dir, CAL)
        agg = payload["all_candidates"]
        # 该世界 t14 相对 t10 的增量来自第 11-14 天的深跌 → mean_d 为负
        t14 = next(r for r in agg["curve"] if r["k"] == 14)
        assert t14["mean_d"] < 0
        assert agg["qualification"]["qualified"] is False

    def test_focus_ks_frozen(self):
        assert FOCUS_KS == (12, 14)
