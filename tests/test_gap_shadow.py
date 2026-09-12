# -*- coding: utf-8 -*-
"""gap 前向影子记录机 (R196 Op1) — 纯核心 + tracker 接线 + advisory 语义测试.

宪法 #2: 影子记录是纯披露事实面。本套件钉住: gap 校验不伪造 / would_skip
严格阈值单一实现 / 幂等首观察赢 PIT / 不可观测绝不冒充可交易性 / journal
损坏 fail-closed / advisory 接线绝不阻断交易流程。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd
import pytest

from src.screening.offensive import gap_disclosure, gap_shadow
from src.screening.offensive.gap_shadow import (
    GAP_SHADOW_FILENAME,
    GapShadowLedgerError,
    build_shadow_records_from_ledger,
    read_ledger_realized,
    read_ledger_trades,
    GAP_STATUS_NON_POSITIVE_PRICE,
    GAP_STATUS_OBSERVED,
    GAP_STATUS_PREV_CLOSE_MISSING,
    GAP_STATUS_T1_BAR_MISSING,
    GapShadowJournalError,
    append_shadow_records,
    build_shadow_records,
    load_shadow_entries,
    open_gap_pct,
    shadow_keys,
    would_skip,
)
from src.screening.offensive.paper_tracker import PaperTracker


def _frame(rows: list[tuple[str, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime([r[0] for r in rows], format="%Y%m%d"),
            "close": [r[1] for r in rows],
            "open": [r[2] for r in rows],
        }
    )


def _buy(date: str, ticker: str, setup: str = "btst_breakout", horizon: int = 10) -> dict:
    return {
        "action": "BUY",
        "date": date,
        "ticker": ticker,
        "setup": setup,
        "horizon": horizon,
        "entry_price": 10.0,
        "kelly_pct": 0.05,
    }


def _loader(frames: dict[str, pd.DataFrame]):
    def load(ticker: str, as_of: str):
        return frames.get(ticker)

    return load


def _cal(sessions: list[str]):
    return gap_shadow.t1_session_resolver(sessions)


# ---- open_gap_pct ----


class TestOpenGapPct:
    def test_up_and_down(self):
        assert open_gap_pct(100.0, 105.0) == pytest.approx(0.05)
        assert open_gap_pct(100.0, 95.0) == pytest.approx(-0.05)

    def test_non_finite_rejected(self):
        for bad in (float("nan"), float("inf"), -float("inf")):
            assert open_gap_pct(bad, 105.0) is None
            assert open_gap_pct(100.0, bad) is None

    def test_non_positive_rejected(self):
        assert open_gap_pct(0.0, 105.0) is None
        assert open_gap_pct(100.0, 0.0) is None
        assert open_gap_pct(-1.0, 105.0) is None

    def test_non_numeric_and_bool_rejected(self):
        assert open_gap_pct("100", 105.0) is None
        assert open_gap_pct(None, 105.0) is None
        assert open_gap_pct(True, 105.0) is None  # bool 毒化拒绝


# ---- would_skip ----


class TestWouldSkip:
    def test_strict_threshold(self):
        assert would_skip(0.05) is False  # 恰等阈值不 skip (严格 >)
        assert would_skip(0.050001) is True
        assert would_skip(-0.20) is False

    def test_unknown_gap_is_none(self):
        assert would_skip(None) is None

    def test_threshold_single_source(self):
        # 阈值是 gap_disclosure 单一实现, 不允许影子模块第二套常量
        assert gap_shadow.GAP_HIGH_THRESHOLD is gap_disclosure.GAP_HIGH_THRESHOLD

    def test_custom_threshold_used(self):
        assert would_skip(0.03, threshold=0.02) is True


# ---- build_shadow_records ----


class TestBuildShadowRecords:
    def test_observed_record_shape(self):
        frames = {"000001": _frame([("20260810", 10.0, 10.2), ("20260811", 10.5, 10.8)])}
        records, summary = build_shadow_records(
            [_buy("20260810", "000001")], set(), "20260812", _loader(frames), _cal(["20260810", "20260811"])
        )
        assert len(records) == 1
        rec = records[0]
        assert rec["signal_date"] == "20260810"
        assert rec["ticker"] == "000001"
        assert rec["setup"] == "btst_breakout"
        assert rec["horizon"] == 10
        assert rec["gap_pct"] == pytest.approx(0.08)
        assert rec["gap_status"] == GAP_STATUS_OBSERVED
        assert rec["would_skip"] is True
        assert rec["threshold"] == gap_disclosure.GAP_HIGH_THRESHOLD
        assert summary[GAP_STATUS_OBSERVED] == 1

    def test_idempotent_first_observation_wins(self):
        frames = {"000001": _frame([("20260810", 10.0, 10.2), ("20260811", 10.5, 10.8)])}
        records, summary = build_shadow_records(
            [_buy("20260810", "000001")], {("20260810", "000001")}, "20260812",
            _loader(frames), _cal(["20260810", "20260811"]),
        )
        assert records == []
        assert summary["already_recorded"] == 1

    def test_duplicate_buy_keys_deduped(self):
        frames = {"000001": _frame([("20260810", 10.0, 10.2), ("20260811", 10.5, 10.8)])}
        records, summary = build_shadow_records(
            [_buy("20260810", "000001"), _buy("20260810", "000001")], set(), "20260812",
            _loader(frames), _cal(["20260810", "20260811"]),
        )
        assert len(records) == 1
        assert summary["considered"] == 1

    def test_t1_bar_missing_permanent_and_never_skip(self):
        # T+1 停牌: 帧里没有 20260811 行 (下一行是 20260812)
        frames = {"000001": _frame([("20260810", 10.0, 10.2), ("20260812", 10.4, 10.5)])}
        records, summary = build_shadow_records(
            [_buy("20260810", "000001")], set(), "20260813", _loader(frames),
            _cal(["20260810", "20260811", "20260812"]),
        )
        assert len(records) == 1
        assert records[0]["gap_status"] == GAP_STATUS_T1_BAR_MISSING
        assert records[0]["would_skip"] is None
        assert records[0]["gap_pct"] is None

    def test_prev_close_missing_permanent(self):
        frames = {"000001": _frame([("20260811", 10.5, 10.8)])}
        records, summary = build_shadow_records(
            [_buy("20260810", "000001")], set(), "20260812", _loader(frames),
            _cal(["20260810", "20260811"]),
        )
        assert records[0]["gap_status"] == GAP_STATUS_PREV_CLOSE_MISSING
        assert records[0]["would_skip"] is None

    def test_non_positive_price_honest_status(self):
        frames = {"000001": _frame([("20260810", 0.0, 10.2), ("20260811", 10.5, 10.8)])}
        records, _ = build_shadow_records(
            [_buy("20260810", "000001")], set(), "20260812", _loader(frames),
            _cal(["20260810", "20260811"]),
        )
        assert records[0]["gap_status"] == GAP_STATUS_NON_POSITIVE_PRICE
        assert records[0]["would_skip"] is None

    def test_frame_missing_retried_not_recorded(self):
        records, summary = build_shadow_records(
            [_buy("20260810", "000001")], set(), "20260812", _loader({}), _cal(["20260810", "20260811"])
        )
        assert records == []
        assert summary["retried"] == 1

    def test_loader_exception_retried_not_recorded(self):
        def boom(ticker, as_of):
            raise RuntimeError("cache gone")

        records, summary = build_shadow_records(
            [_buy("20260810", "000001")], set(), "20260812", boom, _cal(["20260810", "20260811"])
        )
        assert records == []
        assert summary["retried"] == 1

    def test_calendar_unresolved_retried(self):
        frames = {"000001": _frame([("20260810", 10.0, 10.2), ("20260811", 10.5, 10.8)])}
        records, summary = build_shadow_records(
            [_buy("20260810", "000001")], set(), "20260812", _loader(frames), _cal([])
        )
        assert records == []
        assert summary["retried"] == 1

    def test_future_signal_skipped(self):
        records, summary = build_shadow_records(
            [_buy("20260812", "000001")], set(), "20260812", _loader({}), _cal(["20260812", "20260813"])
        )
        assert records == []
        assert summary["future"] == 1

    def test_non_buy_and_malformed_rows_ignored(self):
        frames = {"000001": _frame([("20260810", 10.0, 10.2), ("20260811", 10.5, 10.8)])}
        rows = [_buy("20260810", "000001"), {"action": "EXIT", "date": "20260810", "ticker": "000001"}, "junk"]
        records, summary = build_shadow_records(rows, set(), "20260812", _loader(frames), _cal(["20260810", "20260811"]))
        assert len(records) == 1
        assert summary["considered"] == 1

    def test_summary_identity_holds(self):
        # 恒等式: considered = already_recorded + future + retried + len(records)
        frames = {"000001": _frame([("20260810", 10.0, 10.2), ("20260811", 10.5, 10.8)])}
        rows = [
            _buy("20260810", "000001"),
            _buy("20260812", "000002"),  # future
            _buy("20260811", "000003"),  # frame missing → retried
        ]
        records, s = build_shadow_records(
            rows, set(), "20260812",
            _loader(frames), _cal(["20260810", "20260811"]),
        )
        assert s["considered"] == s["already_recorded"] + s["future"] + s["retried"] + len(records)


# ---- journal IO ----


class TestShadowJournalIO:
    def test_load_missing_file_empty(self, tmp_path):
        assert load_shadow_entries(tmp_path / "absent.jsonl") == []

    def test_append_and_load_roundtrip(self, tmp_path):
        p = tmp_path / GAP_SHADOW_FILENAME
        rec = {"signal_date": "20260810", "ticker": "000001", "gap_status": GAP_STATUS_OBSERVED,
               "gap_pct": 0.08, "would_skip": True, "threshold": 0.05, "setup": "s", "horizon": 10}
        assert append_shadow_records(p, [rec]) == 1
        assert append_shadow_records(p, [rec]) == 1  # append-only: 追加不覆盖
        entries = load_shadow_entries(p)
        assert len(entries) == 2
        assert shadow_keys(entries) == {("20260810", "000001")}

    def test_empty_records_zero_writes(self, tmp_path):
        p = tmp_path / GAP_SHADOW_FILENAME
        assert append_shadow_records(p, []) == 0
        assert not p.exists()

    def test_corrupt_line_fail_closed(self, tmp_path):
        p = tmp_path / GAP_SHADOW_FILENAME
        p.write_text("{not json}\n", encoding="utf-8")
        with pytest.raises(GapShadowJournalError):
            load_shadow_entries(p)
        with pytest.raises(GapShadowJournalError):
            append_shadow_records(p, [{"signal_date": "20260810", "ticker": "000001",
                                       "gap_status": GAP_STATUS_OBSERVED}])
        # 损坏事实未被静默覆盖
        assert p.read_text(encoding="utf-8") == "{not json}\n"

    def test_schema_missing_key_fail_closed(self, tmp_path):
        p = tmp_path / GAP_SHADOW_FILENAME
        p.write_text(json.dumps({"signal_date": "20260810", "ticker": "000001"}) + "\n", encoding="utf-8")
        with pytest.raises(GapShadowJournalError):
            load_shadow_entries(p)


# ---- tracker wiring ----


class TestTrackerWiring:
    def _tracker_with_buy(self, tmp_path: Path) -> PaperTracker:
        tracker = PaperTracker(journal_dir=tmp_path)
        tracker.record_buy("20260810", "000001", "btst_breakout", 10, 10.0, 0.05, 9.0, 8.5, "test")
        return tracker

    def test_sidecar_written_next_to_journal(self, tmp_path):
        tracker = self._tracker_with_buy(tmp_path)
        frames = {"000001": _frame([("20260810", 10.0, 11.5), ("20260811", 11.0, 11.2)])}
        summary = tracker.record_open_gap_shadow(
            "20260812", price_loader=_loader(frames), t1_session_of=_cal(["20260810", "20260811"])
        )
        sidecar = tmp_path / GAP_SHADOW_FILENAME
        assert sidecar.exists()
        entries = load_shadow_entries(sidecar)
        assert len(entries) == 1
        assert entries[0]["would_skip"] is True
        assert summary[GAP_STATUS_OBSERVED] == 1
        assert summary["appended"] == 1
        assert tracker.last_gap_shadow_summary == summary

    def test_second_run_idempotent(self, tmp_path):
        tracker = self._tracker_with_buy(tmp_path)
        frames = {"000001": _frame([("20260810", 10.0, 11.5), ("20260811", 11.0, 11.2)])}
        kw = {"price_loader": _loader(frames), "t1_session_of": _cal(["20260810", "20260811"])}
        tracker.record_open_gap_shadow("20260812", **kw)
        summary2 = tracker.record_open_gap_shadow("20260812", **kw)
        assert summary2["appended"] == 0
        assert summary2["already_recorded"] == 1
        assert len(load_shadow_entries(tmp_path / GAP_SHADOW_FILENAME)) == 1

    def test_corrupt_sidecar_raises_not_silent(self, tmp_path):
        tracker = self._tracker_with_buy(tmp_path)
        (tmp_path / GAP_SHADOW_FILENAME).write_text("garbage\n", encoding="utf-8")
        frames = {"000001": _frame([("20260810", 10.0, 11.5), ("20260811", 11.0, 11.2)])}
        with pytest.raises(GapShadowJournalError):
            tracker.record_open_gap_shadow(
                "20260812", price_loader=_loader(frames), t1_session_of=_cal(["20260810", "20260811"])
            )


# ---- daily_action advisory wiring ----


class TestAdvisoryWiring:
    def _call(self, tracker, sessions=("2026-08-10", "2026-08-11")):
        from src.screening.offensive.daily_action import _record_gap_shadow_advisory

        _record_gap_shadow_advisory(tracker, "20260812", lambda t, a: None, sessions)

    def test_happy_path_calls_once(self, tmp_path, monkeypatch):
        tracker = PaperTracker(journal_dir=tmp_path)
        calls = []
        monkeypatch.setattr(tracker, "record_open_gap_shadow",
                            lambda as_of, **kw: calls.append((as_of, kw)) or {})
        self._call(tracker)
        assert len(calls) == 1
        assert calls[0][0] == "20260812"
        # date 对象日历被归一化成紧凑串 resolver
        resolve = calls[0][1]["t1_session_of"]
        assert resolve("20260810") == "20260811"

    def test_failure_advisory_not_blocking(self, tmp_path, caplog):
        tracker = PaperTracker(journal_dir=tmp_path)

        def boom(as_of, **kw):
            raise RuntimeError("disk on fire")

        tracker.record_open_gap_shadow = boom
        with caplog.at_level(logging.WARNING):
            self._call(tracker)  # 不抛
        assert any("gap_shadow" in r.message for r in caplog.records)

    def test_calendar_failure_advisory(self, tmp_path, monkeypatch):
        from src.screening.offensive import daily_action as da

        tracker = PaperTracker(journal_dir=tmp_path)
        calls = []
        monkeypatch.setattr(tracker, "record_open_gap_shadow",
                            lambda as_of, **kw: calls.append(as_of) or {})
        monkeypatch.setattr(da, "_load_authoritative_session_dates", lambda: (_ for _ in ()).throw(RuntimeError("no cal")))
        self._call(tracker, sessions=None)
        assert len(calls) == 1  # 日历失败仍记录 (空日历 → 全部按重试语义)


# ---- 载入语义一致性校验 (R196 Op2 收口: 毒记录绝不冒充合法影子事实) ----


def _observed_line(**over):
    line = {"signal_date": "20260810", "ticker": "000001", "setup": "s", "horizon": 10,
            "gap_status": GAP_STATUS_OBSERVED, "gap_pct": 0.08, "would_skip": True,
            "threshold": 0.05}
    line.update(over)
    return json.dumps(line, ensure_ascii=False)


def _load_line(tmp_path, line):
    p = tmp_path / "sidecar.jsonl"
    p.write_text(line + "\n", encoding="utf-8")
    return load_shadow_entries(p)


class TestSemanticValidation:
    def test_valid_observed_negative_gap_loads(self, tmp_path):
        entries = _load_line(tmp_path, _observed_line(gap_pct=-0.02, would_skip=False))
        assert entries[0]["gap_pct"] == pytest.approx(-0.02)
        assert entries[0]["would_skip"] is False

    def test_valid_observed_exact_threshold_loads(self, tmp_path):
        entries = _load_line(tmp_path, _observed_line(gap_pct=0.05, would_skip=False))
        assert entries[0]["would_skip"] is False  # 恰等不 skip (严格 >)

    def test_valid_unobservable_all_none_loads(self, tmp_path):
        for status in (GAP_STATUS_T1_BAR_MISSING, GAP_STATUS_PREV_CLOSE_MISSING,
                       GAP_STATUS_NON_POSITIVE_PRICE):
            line = json.dumps({"signal_date": "20260810", "ticker": "000001", "setup": "s",
                               "horizon": 10, "gap_status": status, "gap_pct": None,
                               "would_skip": None, "threshold": 0.05})
            entries = _load_line(tmp_path, line)
            assert entries[0]["gap_status"] == status

    def test_B01_observed_missing_would_skip_rejected(self, tmp_path):
        line = json.dumps({"signal_date": "20260810", "ticker": "000001", "setup": "s",
                           "horizon": 10, "gap_status": GAP_STATUS_OBSERVED,
                           "gap_pct": 0.08, "threshold": 0.05})
        with pytest.raises(GapShadowJournalError):
            _load_line(tmp_path, line)

    def test_B02_bool_poison_gap_rejected(self, tmp_path):
        with pytest.raises(GapShadowJournalError):
            _load_line(tmp_path, _observed_line(gap_pct=True))

    def test_B03_inconsistent_membership_rejected(self, tmp_path):
        with pytest.raises(GapShadowJournalError):
            _load_line(tmp_path, _observed_line(gap_pct=0.08, would_skip=False))

    def test_B04_unknown_status_rejected(self, tmp_path):
        with pytest.raises(GapShadowJournalError):
            _load_line(tmp_path, _observed_line(gap_pct=None, would_skip=None,
                                                gap_status="observed "))
        with pytest.raises(GapShadowJournalError):
            _load_line(tmp_path, _observed_line(gap_pct=None, would_skip=None,
                                                gap_status="OBSERVED"))

    def test_unobservable_with_gap_poison_rejected(self, tmp_path):
        with pytest.raises(GapShadowJournalError):
            _load_line(tmp_path, _observed_line(gap_status=GAP_STATUS_T1_BAR_MISSING,
                                                gap_pct=0.01))

    def test_unobservable_with_skip_poison_rejected(self, tmp_path):
        with pytest.raises(GapShadowJournalError):
            _load_line(tmp_path, _observed_line(gap_status=GAP_STATUS_PREV_CLOSE_MISSING,
                                                gap_pct=None, would_skip=False))

    def test_threshold_bool_or_nonpositive_rejected(self, tmp_path):
        for bad in (True, 0, -0.05, "0.05", None):
            with pytest.raises(GapShadowJournalError):
                _load_line(tmp_path, _observed_line(threshold=bad))

    def test_would_skip_non_bool_rejected(self, tmp_path):
        with pytest.raises(GapShadowJournalError):
            _load_line(tmp_path, _observed_line(would_skip=1))

    def test_empty_key_rejected(self, tmp_path):
        with pytest.raises(GapShadowJournalError):
            _load_line(tmp_path, _observed_line(ticker=""))
        with pytest.raises(GapShadowJournalError):
            _load_line(tmp_path, _observed_line(signal_date=""))


# ---- v2 生产台账只读访问 + 影子记录 (R199 Op1: 基座 rebalance) ----


def _make_ledger(tmp_path: Path, trades: list[tuple], events: list[tuple]) -> Path:
    """构造最小 v2 台账 fixture: trades(trade_id,ticker,signal_date,planned_entry_date,state,setup)
    + trade_events(trade_id,event_type,cash_delta)。"""
    import sqlite3

    p = tmp_path / "ledger.sqlite3"
    conn = sqlite3.connect(p)
    conn.execute(
        "CREATE TABLE trades (trade_id TEXT, ticker TEXT, signal_date TEXT, "
        "planned_entry_date TEXT, state TEXT, setup TEXT)"
    )
    conn.execute(
        "CREATE TABLE trade_events (trade_id TEXT, event_type TEXT, cash_delta REAL)"
    )
    conn.executemany("INSERT INTO trades VALUES (?,?,?,?,?,?)", trades)
    conn.executemany("INSERT INTO trade_events VALUES (?,?,?)", events)
    conn.commit()
    conn.close()
    return p


class TestLedgerReadAccess:
    def test_read_trades_normalizes_dates(self, tmp_path):
        led = _make_ledger(
            tmp_path,
            [("t1", "600487", "2026-08-14", "2026-08-17", "closed", "btst_breakout")],
            [],
        )
        trades = read_ledger_trades(led)
        assert trades == [{
            "trade_id": "t1", "ticker": "600487",
            "signal_date": "20260814", "planned_entry_date": "20260817",
            "state": "closed", "setup": "btst_breakout",
        }]

    def test_missing_ledger_empty(self, tmp_path):
        assert read_ledger_trades(tmp_path / "absent.sqlite3") == []
        assert read_ledger_realized(tmp_path / "absent.sqlite3") == {}

    def test_corrupt_ledger_fail_closed(self, tmp_path):
        p = tmp_path / "broken.sqlite3"
        p.write_bytes(b"not a database at all")
        with pytest.raises(GapShadowLedgerError):
            read_ledger_trades(p)
        with pytest.raises(GapShadowLedgerError):
            read_ledger_realized(p)

    def test_realized_net_cash_and_pending_excluded(self, tmp_path):
        led = _make_ledger(
            tmp_path,
            [
                ("t1", "600487", "2026-08-14", "2026-08-17", "closed", "s"),
                ("t2", "000001", "2026-08-14", "2026-08-17", "exit_pending", "s"),
            ],
            [
                ("t1", "ENTRY_FILLED", -76789.68),
                ("t1", "EXIT_FILLED", 84901.80),
                ("t2", "ENTRY_FILLED", -10000.0),
            ],
        )
        realized = read_ledger_realized(led)
        assert realized[("20260814", "600487")] == pytest.approx((84901.80 - 76789.68) / 76789.68)
        assert ("20260814", "000001") not in realized  # 无 EXIT_FILLED = pending

    def test_realized_partial_exits_summed(self, tmp_path):
        led = _make_ledger(
            tmp_path,
            [("t1", "600487", "2026-08-14", "2026-08-17", "closed", "s")],
            [
                ("t1", "ENTRY_FILLED", -10000.0),
                ("t1", "EXIT_FILLED", 4000.0),
                ("t1", "EXIT_FILLED", 6500.0),
            ],
        )
        assert read_ledger_realized(led)[("20260814", "600487")] == pytest.approx(0.05)


class TestBuildShadowRecordsFromLedger:
    def test_observed_record_carries_source_and_execution_truth_t1(self):
        frames = {"600487": _frame([("20260814", 10.0, 10.2), ("20260817", 10.5, 11.8)])}
        trades = [{"trade_id": "t1", "ticker": "600487", "signal_date": "20260814",
                   "planned_entry_date": "20260817", "state": "open", "setup": "s"}]
        records, summary = build_shadow_records_from_ledger(
            trades, set(), "20260818", _loader(frames)
        )
        assert len(records) == 1
        rec = records[0]
        assert rec["source"] == "v2_ledger"
        assert rec["gap_pct"] == pytest.approx(0.18)  # t1 = planned_entry_date 开盘
        assert rec["would_skip"] is True
        assert summary["observed"] == 1

    def test_cross_source_idempotency_first_observation_wins(self):
        frames = {"600487": _frame([("20260814", 10.0, 10.2), ("20260817", 10.5, 11.8)])}
        trades = [{"ticker": "600487", "signal_date": "20260814",
                   "planned_entry_date": "20260817", "setup": "s"}]
        records, summary = build_shadow_records_from_ledger(
            trades, {("20260814", "600487")}, "20260818", _loader(frames)
        )
        assert records == []
        assert summary["already_recorded"] == 1  # legacy 先记 → 跨源首观察赢

    def test_unobservable_states_named_same_as_legacy(self):
        frames = {"600487": _frame([("20260814", 10.0, 10.2), ("20260819", 10.5, 10.6)])}
        trades = [{"ticker": "600487", "signal_date": "20260814",
                   "planned_entry_date": "20260817", "setup": "s"}]  # t1 bar 缺
        records, _ = build_shadow_records_from_ledger(trades, set(), "20260820", _loader(frames))
        assert records[0]["gap_status"] == GAP_STATUS_T1_BAR_MISSING
        assert records[0]["would_skip"] is None

    def test_missing_frame_retried_and_future_skipped(self):
        trades = [
            {"ticker": "000001", "signal_date": "20260814", "planned_entry_date": "20260817", "setup": "s"},
            {"ticker": "000002", "signal_date": "20260920", "planned_entry_date": "20260921", "setup": "s"},
        ]
        records, summary = build_shadow_records_from_ledger(trades, set(), "20260918", _loader({}))
        assert records == []
        assert summary["retried"] == 1
        assert summary["future"] == 1


# ---- R199 Op2 守卫钉 (探针 10/10 有牙 + 3 无钉盲区收口) ----


class TestOp2HardeningPins:
    def test_t1_semantics_distinguishable_from_next_row(self):
        # B01 钉: 中间行 (0815) 在场 — t1 必须取 planned_entry_date (0817) 而非
        # 帧内下一行; next-row 变异在旧无中间行 fixture 上逃逸, 此处当场红。
        frames = {"X": _frame([
            ("20260814", 10.0, 10.2),
            ("20260815", 10.1, 10.3),
            ("20260817", 10.5, 11.8),
        ])}
        trades = [{"ticker": "X", "signal_date": "20260814",
                   "planned_entry_date": "20260817", "setup": "s"}]
        records, _ = build_shadow_records_from_ledger(trades, set(), "20260818", _loader(frames))
        assert records[0]["gap_pct"] == pytest.approx(11.8 / 10.0 - 1)  # 0817 开盘

    def test_realized_guards_nonpositive_entry_cash(self, tmp_path):
        # B02 钉: ENTRY_FILLED cash_delta >= 0 是非交易形态 → 不进 realized (不伪造)
        led = _make_ledger(
            tmp_path,
            [("t1", "X", "20260814", "20260817", "closed", "s")],
            [
                ("t1", "ENTRY_FILLED", 100.0),   # 畸形: 入场净流入
                ("t1", "EXIT_FILLED", -50.0),
            ],
        )
        assert read_ledger_realized(led) == {}

    def test_scanner_stub_record_open_gap_shadow_noop(self):
        # B03 钉: 生产扫描 stub 必须有诚实 no-op (R199 Op1) — 方法被误删则
        # R196 advisory 在生产路径恢复每天 AttributeError 失败噪声。
        from src.screening.offensive.daily_action import _ScannerCompatibilityState

        assert _ScannerCompatibilityState().record_open_gap_shadow() == {}

    def test_missing_planned_entry_date_counted_future(self):
        # B04 钉: planned_entry_date 缺失 → future 计数 (不猜测 t1, 不落记录)
        trades = [{"ticker": "X", "signal_date": "20260814",
                   "planned_entry_date": None, "setup": "s"}]
        records, summary = build_shadow_records_from_ledger(trades, set(), "20260818", _loader({}))
        assert records == []
        assert summary["future"] == 1
