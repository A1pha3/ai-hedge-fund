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


# ---- R197 Op2 守卫钉 (探针定谳 P14 BLIND + B07 真实盲区收口) ----


class TestOp2HardeningPins:
    def test_zero_realized_is_not_a_win(self):
        # P14 守卫: realized 恰 0 不计胜 (>= 变异在此红)
        r = assemble_shadow_reading(
            [_entry("20260810", "000001", would_skip=True)],
            [_buy("20260810", "000001"), _exit("20260810", "000001", "+0.00%")],
        )
        assert r["skip"]["win_rate"] == 0.0
        assert r["skip"]["n"] == 1

    def test_divergent_duplicate_exit_first_wins(self):
        # B02 守卫: 重复 EXIT (篡改/重放分叉) 首条是 journal 真相
        r = assemble_shadow_reading(
            [_entry("20260810", "000001", would_skip=True)],
            [_buy("20260810", "000001"), _exit("20260810", "000001", "+1.00%"),
             _exit("20260810", "000001", "+99.00%")],
        )
        assert r["skip"]["mean"] == pytest.approx(0.01)

    def test_empty_bucket_winrate_and_mean_both_none(self):
        # B03 守卫: 零桶 mean/win_rate 双 None (无伪造)
        r = assemble_shadow_reading([_entry("20260810", "000001", would_skip=True)], [])
        assert r["skip"]["mean"] is None
        assert r["skip"]["win_rate"] is None

    def test_non_bool_would_skip_excluded_named(self):
        # B07 收口: 绕过严格 loader 直传的毒值按真值性入桶即改写会员籍
        for poison in (1, 0, "true", ""):
            r = assemble_shadow_reading(
                [{**_entry("20260810", "000001", would_skip=True), "would_skip": poison}],
                [_buy("20260810", "000001"), _exit("20260810", "000001", "+5.00%")],
            )
            assert r["counts"]["invalid_entries"] == 1, poison
            assert r["skip"]["n"] == 0 and r["keep"]["n"] == 0
        md = render_md(assemble_shadow_reading(
            [{**_entry("20260810", "000001", would_skip=True), "would_skip": 1}], []))
        assert "invalid_entries 1" in md


# ---- R199 Op1: 双源配对 (v2 台账真相 + legacy journal) ----


def _ledger_trade(date, ticker, planned):
    return {"trade_id": "t", "ticker": ticker, "signal_date": date,
            "planned_entry_date": planned, "state": "open", "setup": "s"}


class TestDualSourcePairing:
    def test_v2_record_pairs_against_ledger_realized(self):
        entries = [{"signal_date": "20260814", "ticker": "600487", "setup": "s",
                    "horizon": 10, "gap_status": "observed", "gap_pct": 0.18,
                    "would_skip": True, "threshold": 0.05, "source": "v2_ledger"}]
        r = assemble_shadow_reading(
            entries, [],
            ledger_trades=[_ledger_trade("20260814", "600487", "20260817")],
            ledger_realized={("20260814", "600487"): 0.1057},
        )
        assert r["counts"]["orphan_entries"] == 0
        assert r["skip"]["n"] == 1
        assert r["skip"]["mean"] == pytest.approx(0.1057)  # 台账净现金, 非 journal 解析
        assert r["sources"] == {"v2_ledger": 1}

    def test_v2_record_without_ledger_supply_disclosed_as_orphan(self):
        # ledger 真相未供给 → 诚实降级 orphan, 绝不冒充配对
        entries = [{"signal_date": "20260814", "ticker": "600487", "setup": "s",
                    "horizon": 10, "gap_status": "observed", "gap_pct": 0.18,
                    "would_skip": True, "threshold": 0.05, "source": "v2_ledger"}]
        r = assemble_shadow_reading(entries, [])
        assert r["counts"]["orphan_entries"] == 1
        assert r["skip"]["n"] == 0

    def test_v2_record_without_exit_pending(self):
        entries = [{"signal_date": "20260814", "ticker": "600487", "setup": "s",
                    "horizon": 10, "gap_status": "observed", "gap_pct": 0.18,
                    "would_skip": True, "threshold": 0.05, "source": "v2_ledger"}]
        r = assemble_shadow_reading(
            entries, [],
            ledger_trades=[_ledger_trade("20260814", "600487", "20260817")],
            ledger_realized={},
        )
        assert r["counts"]["pending"] == 1
        assert r["skip"]["n"] == 0

    def test_legacy_record_pairs_against_journal_not_ledger(self):
        # legacy 记录即使台账有同键 realized, 也走 journal EXIT 解析 (源不互串)
        entries = [_entry("20260810", "000001", would_skip=True)]
        actions = [_buy("20260810", "000001"), _exit("20260810", "000001", "+1.00%")]
        r = assemble_shadow_reading(
            entries, actions,
            ledger_trades=[_ledger_trade("20260810", "000001", "20260811")],
            ledger_realized={("20260810", "000001"): 0.99},
        )
        assert r["skip"]["mean"] == pytest.approx(0.01)  # journal 真相胜

    def test_unshadowed_ledger_trades_counted(self):
        r = assemble_shadow_reading(
            [], [],
            ledger_trades=[_ledger_trade("20260910", "600001", "20260911")],
            ledger_realized={},
        )
        assert r["counts"]["unshadowed_ledger_trades"] == 1

    def test_sources_mixed_disclosed(self):
        entries = [
            _entry("20260810", "000001", would_skip=True),
            {"signal_date": "20260814", "ticker": "600487", "setup": "s",
             "horizon": 10, "gap_status": "observed", "gap_pct": 0.18,
             "would_skip": False, "threshold": 0.05, "source": "v2_ledger"},
        ]
        actions = [_buy("20260810", "000001"), _exit("20260810", "000001", "+2.00%")]
        r = assemble_shadow_reading(
            entries, actions,
            ledger_trades=[_ledger_trade("20260814", "600487", "20260817")],
            ledger_realized={("20260814", "600487"): 0.03},
        )
        assert r["sources"] == {"legacy_journal": 1, "v2_ledger": 1}
        assert r["keep"]["n"] == 1 and r["skip"]["n"] == 1
