# -*- coding: utf-8 -*-
"""gap 影子配对读数包 (R197 Op1) — 装配/对账/纪律面/渲染守卫测试.

纯披露装配面: 钉住 realized 单一真值解析 / 配对恒等 / 具名排除计数 /
n<30 披露不判定 / 渲染 fail-open / 无墙钟确定性。
"""

from __future__ import annotations

import json

import pytest

from scripts.gap_shadow_pack import (
    GapShadowJournalReadError,
    assemble_shadow_reading,
    load_journal_actions,
    parse_exit_realized,
    render_md,
)


def _entry(date: str, ticker: str, *, would_skip=True, threshold=0.05, gap_pct=0.08):
    return {"signal_date": date, "ticker": ticker, "setup": "btst_breakout", "horizon": 10,
            "gap_status": "observed" if would_skip is not None else "t1_bar_missing",
            "gap_pct": gap_pct, "would_skip": would_skip, "threshold": threshold}


def _buy(date: str, ticker: str):
    return {"action": "BUY", "date": date, "ticker": ticker, "setup": "btst_breakout",
            "horizon": 10, "entry_price": 10.0, "kelly_pct": 0.05}


def _exit(date: str, ticker: str, realized: str):
    return {"action": "EXIT", "date": date, "ticker": ticker, "setup": "btst_breakout",
            "horizon": 10, "reasoning": f"T+10 到期平仓; realized={realized}; stop_would_trigger=False"}


# ---- parse_exit_realized ----


class TestParseExitRealized:
    def test_valid_forms(self):
        assert parse_exit_realized("T+10 到期平仓; realized=+5.32%; stop_would_trigger=False") == pytest.approx(0.0532)
        assert parse_exit_realized("T+10 到期平仓; realized=-3.10%; stop_executed=False") == pytest.approx(-0.031)
        assert parse_exit_realized("realized=+0.00%") == 0.0

    def test_garbage_or_missing_returns_none(self):
        assert parse_exit_realized("no realized here") is None
        assert parse_exit_realized("") is None
        assert parse_exit_realized(None) is None
        assert parse_exit_realized(123) is None
        assert parse_exit_realized("realized=5.32%") is None  # 缺符号位 — 严格格式
        assert parse_exit_realized("realized=+5.3%") is None  # 一位小数 — 严格格式


# ---- assemble_shadow_reading ----


class TestAssembleShadowReading:
    def test_paired_aggregates_and_penalty_direction(self):
        entries = [
            _entry("20260810", "000001", would_skip=True),   # skip: +10%
            _entry("20260810", "000002", would_skip=True),   # skip: -20%
            _entry("20260810", "000003", would_skip=False),  # keep: +2%
            _entry("20260810", "000004", would_skip=False),  # keep: +4%
        ]
        actions = (
            [_buy("20260810", t) for t in ("000001", "000002", "000003", "000004")]
            + [_exit("20260810", "000001", "+10.00%"), _exit("20260810", "000002", "-20.00%"),
               _exit("20260810", "000003", "+2.00%"), _exit("20260810", "000004", "+4.00%")]
        )
        r = assemble_shadow_reading(entries, actions)
        assert r["skip"]["n"] == 2
        assert r["skip"]["mean"] == pytest.approx(-0.05)
        assert r["keep"]["n"] == 2
        assert r["keep"]["mean"] == pytest.approx(0.03)
        assert r["penalty_keep_minus_skip"] == pytest.approx(0.08)  # 正 = 跳过高开有利
        assert r["keep"]["win_rate"] == pytest.approx(1.0)
        assert r["skip"]["win_rate"] == pytest.approx(0.5)

    def test_membership_from_preregistered_field_not_recomputed(self):
        # would_skip=False + gap 0.08 (>0.05): 记录字段是唯一成员籍 (不重算)
        entries = [_entry("20260810", "000001", would_skip=False, gap_pct=0.08)]
        actions = [_buy("20260810", "000001"), _exit("20260810", "000001", "+3.00%")]
        r = assemble_shadow_reading(entries, actions)
        assert r["keep"]["n"] == 1 and r["skip"]["n"] == 0

    def test_exclusion_counts_named(self):
        entries = [
            _entry("20260810", "000001"),                     # pending (无 EXIT)
            {"signal_date": "20260810", "ticker": "000009", "setup": "s", "horizon": 10,
             "gap_status": "t1_bar_missing", "gap_pct": None, "would_skip": None,
             "threshold": 0.05},                              # unobservable
            _entry("20260811", "000077"),                     # orphan (无 BUY)
        ]
        actions = [_buy("20260810", "000001"), _buy("20260812", "000100")]  # 000100 unshadowed
        r = assemble_shadow_reading(entries, actions)
        assert r["counts"]["pending"] == 1
        assert r["counts"]["unobservable"] == 1
        assert r["unobservable_by_status"] == {"t1_bar_missing": 1}
        assert r["counts"]["orphan_entries"] == 1
        assert r["counts"]["unshadowed_buys"] == 1
        assert r["skip"]["n"] == 0 and r["keep"]["n"] == 0

    def test_unparseable_exit_disclosed_and_excluded(self):
        entries = [_entry("20260810", "000001")]
        actions = [_buy("20260810", "000001"),
                   {"action": "EXIT", "date": "20260810", "ticker": "000001",
                    "reasoning": "realized 字段缺失"}]
        r = assemble_shadow_reading(entries, actions)
        assert r["counts"]["unparseable_exits"] == 1
        assert r["skip"]["n"] == 0
        assert r["skip"]["mean"] is None  # 零样本不伪造

    def test_n_below_30_disclosed_not_judged(self):
        entries = [_entry("20260810", "000001", would_skip=True),
                   _entry("20260810", "000002", would_skip=False)]
        actions = ([_buy("20260810", "000001"), _exit("20260810", "000001", "+1.00%")]
                   + [_buy("20260810", "000002"), _exit("20260810", "000002", "+2.00%")])
        r = assemble_shadow_reading(entries, actions)
        assert r["judgable"] is False
        assert "只披露不判定" in r["verdict_hint"]
        assert r["min_n_for_judgment"] == 30

    def test_judgable_when_threshold_met(self):
        entries = ([_entry("20260810", f"S{i:03d}", would_skip=True) for i in range(30)]
                   + [_entry("20260810", f"K{i:03d}", would_skip=False) for i in range(30)])
        actions = []
        for t in [f"S{i:03d}" for i in range(30)] + [f"K{i:03d}" for i in range(30)]:
            actions += [_buy("20260810", t), _exit("20260810", t, "+1.00%")]
        r = assemble_shadow_reading(entries, actions)
        assert r["judgable"] is True

    def test_threshold_mixture_disclosed(self):
        entries = [_entry("20260810", "000001", threshold=0.05),
                   _entry("20260810", "000002", threshold=0.03)]
        actions = ([_buy("20260810", "000001"), _exit("20260810", "000001", "+1.00%")]
                   + [_buy("20260810", "000002"), _exit("20260810", "000002", "+2.00%")])
        r = assemble_shadow_reading(entries, actions)
        assert r["thresholds"] == {"0.05": 1, "0.03": 1}

    def test_window_from_entry_truth(self):
        entries = [_entry("20260803", "000001"), _entry("20260810", "000002")]
        r = assemble_shadow_reading(entries, [])
        assert r["window"] == {"start": "20260803", "end": "20260810"}

    def test_empty_inputs_no_crash(self):
        r = assemble_shadow_reading([], [])
        assert r["window"] == {"start": None, "end": None}
        assert r["counts"]["unshadowed_buys"] == 0
        assert r["penalty_keep_minus_skip"] is None


# ---- journal read + determinism ----


class TestJournalReadAndDeterminism:
    def test_missing_journal_empty(self, tmp_path):
        assert load_journal_actions(tmp_path / "absent.jsonl") == []

    def test_corrupt_line_fail_closed(self, tmp_path):
        p = tmp_path / "journal.jsonl"
        p.write_text("{bad json}\n", encoding="utf-8")
        with pytest.raises(GapShadowJournalReadError):
            load_journal_actions(p)

    def test_duplicate_buys_first_wins(self):
        actions = [_buy("20260810", "000001"), _buy("20260810", "000001")]
        r = assemble_shadow_reading([_entry("20260810", "000001")],
                                    actions + [_exit("20260810", "000001", "+1.00%")])
        assert r["counts"]["unshadowed_buys"] == 0  # 去重后恰一 BUY, 有影子有 EXIT

    def test_determinism_same_input_same_bytes(self):
        entries = [_entry("20260810", f"00000{i}", would_skip=(i % 2 == 0)) for i in range(1, 6)]
        actions = []
        for i in range(1, 6):
            t = f"00000{i}"
            actions += [_buy("20260810", t), _exit("20260810", t, f"+{i}.00%")]
        a = assemble_shadow_reading(entries, actions)
        b = assemble_shadow_reading(list(reversed(entries)), list(reversed(actions)))
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
        assert render_md(a) == render_md(b)  # 无墙钟


# ---- render_md fail-open ----


class TestRenderMd:
    def test_happy_shape(self):
        r = assemble_shadow_reading(
            [_entry("20260810", "000001"), _entry("20260810", "000002", would_skip=False)],
            [_buy("20260810", "000001"), _exit("20260810", "000001", "+8.00%"),
             _buy("20260810", "000002"), _exit("20260810", "000002", "+2.00%")],
        )
        md = render_md(r)
        assert "would-skip (高开>阈值)" in md
        assert "罚分 (E_keep − E_skip): -6.00%" in md  # keep +2% − skip +8% = 负 (跳过不利)
        assert "只披露不判定" in md
        assert "纯披露" in md

    def test_fail_open_on_malformed(self):
        for bad in (None, [], "junk", {"window": "x", "counts": 3, "skip": None, "keep": 7}):
            md = render_md(bad)  # 不抛
            assert isinstance(md, str)
        assert render_md(None).startswith("gap_shadow_pack:")
