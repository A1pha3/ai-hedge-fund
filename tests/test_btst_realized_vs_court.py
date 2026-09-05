"""btst_realized_vs_court — 六类宇宙分裂分类 + 聚合的 fixture 驱动测试.

零网络/零 gitignored 资产: 全部输入在测试内构造 (R10 slot 自足纪律)。
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts.btst_realized_vs_court import (
    CLASSES,
    build_alignment_summary,
    build_classification_inputs,
    classify_buy,
    extract_realized,
    normalize_day,
    realized_map_from_journal,
    realized_stats,
    reconcile,
    render_md,
    write_alignment_summary,
    summary_payload,
)


def _journal_buy(date: str, ticker: str, horizon: int = 10, strength: float = 0.6) -> dict:
    return {
        "date": date,
        "ticker": ticker,
        "action": "BUY",
        "horizon": horizon,
        "trigger_strength": strength,
        "entry_price": 10.0,
        "kelly_pct": 0.08,
    }


def _journal_exit(date: str, ticker: str, realized: str | None) -> dict:
    reasoning = f"T+10 到期平仓; realized={realized}%" if realized else "T+10 到期平仓; 数据未成熟"
    return {"date": date, "ticker": ticker, "action": "EXIT", "reasoning": reasoning}


def _court_frame(rows: list[dict]) -> pd.DataFrame:
    base = {
        "ts_code": [],
        "signal_date": [],
        "trigger_strength": [],
        "gross_ret_t3": [],
        "gross_ret_t5": [],
        "gross_ret_t8": [],
        "gross_ret_t10": [],
    }
    for row in rows:
        base["ts_code"].append(row["ts_code"])
        base["signal_date"].append(row["signal_date"])
        base["trigger_strength"].append(row.get("strength", 0.5))
        for col in ("gross_ret_t3", "gross_ret_t5", "gross_ret_t8", "gross_ret_t10"):
            base[col].append(row.get(col))
    return pd.DataFrame(base)


def _inputs(court_rows: list[dict], *, sessions: list[str], regime: dict, panel: list[str]):
    table = _court_frame(court_rows)
    return build_classification_inputs(
        court_table=table,
        window_sessions=sessions,
        regime_labels=regime,
        panel_dates=panel,
    )


class TestNormalizeDay:
    def test_int64_and_dashed(self):
        assert normalize_day(20260807) == "20260807"
        assert normalize_day("2026-08-07") == "20260807"

    def test_garbage_raises(self):
        with pytest.raises(ValueError):
            normalize_day("not-a-date")


class TestExtractRealized:
    def test_positive_and_negative(self):
        assert extract_realized({"reasoning": "x realized=+6.42%; y"}) == 6.42
        assert extract_realized({"reasoning": "realized=-9.11%; stop"}) == -9.11

    def test_missing_returns_none(self):
        assert extract_realized({"reasoning": "no marker"}) is None
        assert extract_realized({"reasoning": None}) is None


class TestSixClasses:
    def test_outside_window(self):
        inputs = _inputs([], sessions=["20260801"], regime={"20260801": "normal"}, panel=["20260801"])
        rec = classify_buy(_journal_buy("20260815", "000001"), inputs, {})
        assert rec.classification == "outside_window"

    def test_regime_gap_excluded_day(self):
        inputs = _inputs([], sessions=["20260709", "20260710"], regime={"20260709": "crisis"}, panel=["20260709", "20260710"])
        rec = classify_buy(_journal_buy("20260710", "002317"), inputs, {})
        assert rec.classification == "day_excluded_regime_gap"

    def test_panel_missing(self):
        inputs = _inputs([], sessions=["20260801"], regime={"20260801": "normal"}, panel=[])
        rec = classify_buy(_journal_buy("20260801", "000001"), inputs, {})
        assert rec.classification == "day_missing_panel_data"

    def test_day_missing_from_court(self):
        inputs = _inputs(
            [],
            sessions=["20260801", "20260813"],
            regime={"20260801": "normal", "20260813": "crisis"},
            panel=["20260801", "20260813"],
        )
        rec = classify_buy(_journal_buy("20260813", "002066"), inputs, {})
        assert rec.classification == "day_missing_from_court"

    def test_ticker_not_in_court_day(self):
        inputs = _inputs(
            [{"ts_code": "301234.SZ", "signal_date": "20260807", "strength": 0.43, "gross_ret_t10": 0.1002}],
            sessions=["20260807"],
            regime={"20260807": "normal"},
            panel=["20260807"],
        )
        rec = classify_buy(_journal_buy("20260807", "600651"), inputs, {})
        assert rec.classification == "ticker_not_in_court_day"

    def test_matched_with_strength_drift_and_direction(self):
        inputs = _inputs(
            [{"ts_code": "301234.SZ", "signal_date": 20260807, "strength": 0.43, "gross_ret_t10": 0.1002}],
            sessions=["20260807"],
            regime={"20260807": "normal"},
            panel=["20260807"],
        )
        realized = {("20260807", "301234"): -5.0}
        rec = classify_buy(_journal_buy("20260807", "301234", strength=0.50), inputs, realized)
        assert rec.classification == "matched"
        assert rec.court_strength == 0.43
        assert rec.strength_drift == pytest.approx(0.07)
        assert rec.court_gross_ret_horizon == pytest.approx(10.02)
        assert rec.realized_pct == -5.0
        assert rec.direction_agree is False

    def test_matched_missing_column_value_gives_none(self):
        inputs = _inputs(
            [{"ts_code": "301234.SZ", "signal_date": "20260821", "strength": 0.6, "gross_ret_t10": None}],
            sessions=["20260821"],
            regime={"20260821": "normal"},
            panel=["20260821"],
        )
        rec = classify_buy(_journal_buy("20260821", "301234"), inputs, {("20260821", "301234"): 2.0})
        assert rec.classification == "matched"
        assert rec.court_gross_ret_horizon is None
        assert rec.direction_agree is None


class TestReconcile:
    def _world(self):
        court_rows = [
            {"ts_code": "301234.SZ", "signal_date": 20260807, "strength": 0.43, "gross_ret_t10": 0.1002},
            {"ts_code": "601212.SH", "signal_date": 20260821, "strength": 0.655, "gross_ret_t10": None},
            {"ts_code": "000603.SZ", "signal_date": 20260821, "strength": 0.60, "gross_ret_t10": None},
            {"ts_code": "002491.SZ", "signal_date": 20260821, "strength": 0.51, "gross_ret_t10": None},
        ]
        journal = [
            _journal_buy("20260710", "002317", horizon=8, strength=0.75),
            _journal_buy("20260710", "600879", horizon=8, strength=0.675),
            _journal_buy("20260807", "600651", strength=0.65),
            _journal_buy("20260807", "301234", strength=0.50),
            _journal_buy("20260813", "300534", strength=0.63),
            _journal_buy("20260821", "601212", strength=0.6554),
            _journal_buy("20260821", "601212", strength=0.6554),  # 幂等键去重
            _journal_exit("20260710", "002317", "-6.42"),
            _journal_exit("20260710", "600879", "-35.47"),
            _journal_exit("20260807", "301234", "-2.00"),
            _journal_exit("20260813", "300534", None),
            _journal_exit("20260821", "601212", "数据未成熟, 无 realized"),
        ]
        return court_rows, journal

    def test_counts_and_dedup(self):
        court_rows, journal = self._world()
        inputs = _inputs(
            court_rows,
            sessions=["20260710", "20260807", "20260813", "20260821"],
            regime={"20260807": "normal", "20260813": "crisis", "20260821": "normal"},
            panel=["20260710", "20260807", "20260813", "20260821"],
        )
        recon = reconcile(journal, inputs)
        assert recon.class_counts == {
            "outside_window": 0,
            "day_excluded_regime_gap": 2,  # 20260710 两笔
            "day_missing_panel_data": 0,
            "day_missing_from_court": 1,   # 20260813 面板有 regime 有 court 零行
            "ticker_not_in_court_day": 1,  # 600651@0807
            "matched": 2,                  # 301234@0807 + 601212@0821
        }
        assert len(recon.records) == 6  # 重复 BUY 去重

    def test_realized_only_stats(self):
        values = [-6.42, -35.47, -2.0]
        stats = realized_stats(
            [type("R", (), {"realized_pct": v})() for v in values]
        )
        assert stats is not None
        assert stats["n"] == 3
        assert stats["win_rate_pct"] == 0.0
        assert stats["expectancy_pct"] == pytest.approx(-14.63, abs=0.01)
        assert stats["payoff"] is None  # 无亏损组 avg_win 缺失

    def test_realized_map_skips_unmatured(self):
        _, journal = self._world()
        mapping = realized_map_from_journal(journal)
        assert ("20260710", "002317") in mapping
        assert ("20260813", "300534") not in mapping

    def test_summary_and_md_roundtrip(self):
        court_rows, journal = self._world()
        inputs = _inputs(
            court_rows,
            sessions=["20260710", "20260807", "20260813", "20260821"],
            regime={"20260807": "normal", "20260813": "crisis", "20260821": "normal"},
            panel=["20260710", "20260807", "20260813", "20260821"],
        )
        recon = reconcile(journal, inputs)
        payload = summary_payload(recon, court_window=("20250701", "20260830"))
        text = render_md(payload)
        assert "day_excluded_regime_gap" in text
        assert "纯诊断" in text
        assert json.loads(json.dumps(payload))["class_counts"]["matched"] == 2
        # 漂移标注出现在 md
        assert "0.07" in text


class TestClassSet:
    def test_six_classes_declared(self):
        assert set(CLASSES) == {
            "outside_window",
            "day_excluded_regime_gap",
            "day_missing_panel_data",
            "day_missing_from_court",
            "ticker_not_in_court_day",
            "matched",
        }


class TestAlignmentSummary:
    """R118 Op1: canonical 对齐摘要 (操作员宇宙对齐行唯一数据面)."""

    def _world(self):
        court_rows = [
            {"ts_code": "301234.SZ", "signal_date": 20260807, "strength": 0.43, "gross_ret_t10": 0.1002},
            {"ts_code": "601212.SH", "signal_date": 20260821, "strength": 0.655, "gross_ret_t10": None},
        ]
        journal = [
            _journal_buy("20260807", "301234", strength=0.50),
            _journal_buy("20260813", "300534", strength=0.63),
            _journal_buy("20260821", "601212", strength=0.655),
            _journal_exit("20260807", "301234", "-2.00"),
            _journal_exit("20260813", "300534", "3.00"),
            _journal_exit("20260821", "601212", "数据未成熟, 无 realized"),
        ]
        return court_rows, journal

    def test_counts_latest_dates_window_and_realized(self):
        court_rows, journal = self._world()
        inputs = _inputs(
            court_rows,
            sessions=["20260807", "20260813", "20260821"],
            regime={"20260807": "normal", "20260813": "crisis", "20260821": "normal"},
            panel=["20260807", "20260813", "20260821"],
        )
        recon = reconcile(journal, inputs)
        summary = build_alignment_summary(
            recon, court_window=("20250701", "20260901"), summary_date="20260905"
        )
        assert summary["date"] == "20260905"
        assert summary["total_buys"] == 3
        assert summary["class_counts"]["matched"] == 2
        assert summary["class_counts"]["day_missing_from_court"] == 1
        assert summary["latest_matched_signal_date"] == "20260821"
        assert summary["latest_split_signal_date"] == "20260813"
        assert summary["court_window"] == {"start": "20250701", "end": "20260901"}
        assert summary["realized_only"]["n"] == 2

    def test_all_matched_reports_zero_split_with_none_latest(self):
        court_rows, journal = self._world()
        journal = [r for r in journal if r["ticker"] != "300534"]
        journal = [
            r for r in journal
            if not (r["action"] == "EXIT" and r["ticker"] == "300534")
        ]
        inputs = _inputs(
            court_rows,
            sessions=["20260807", "20260813", "20260821"],
            regime={"20260807": "normal", "20260813": "crisis", "20260821": "normal"},
            panel=["20260807", "20260813", "20260821"],
        )
        recon = reconcile(journal, inputs)
        summary = build_alignment_summary(
            recon, court_window=None, summary_date="20260905"
        )
        assert summary["latest_split_signal_date"] is None
        assert summary["class_counts"]["matched"] == 2
        assert "court_window" not in summary

    def test_empty_journal_gives_zero_shape(self):
        inputs = _inputs([], sessions=[], regime={}, panel=[])
        recon = reconcile([], inputs)
        summary = build_alignment_summary(
            recon, court_window=None, summary_date="20260905"
        )
        assert summary["total_buys"] == 0
        assert summary["realized_only"] is None
        assert summary["latest_split_signal_date"] is None
        assert summary["latest_matched_signal_date"] is None
        assert summary["class_counts"] == {c: 0 for c in CLASSES}

    def test_write_alignment_summary_atomic_roundtrip(self, tmp_path):
        target = tmp_path / "nested" / "realized_vs_court_alignment.json"
        summary = build_alignment_summary(
            reconcile([], _inputs([], sessions=[], regime={}, panel=[])),
            court_window=None,
            summary_date="20260905",
        )
        write_alignment_summary(target, summary)
        assert json.loads(target.read_text(encoding="utf-8")) == summary
        assert not list(target.parent.glob(".alignment_*"))
        # 重写 (夜刷逐日覆盖) 收敛同一文件, 无 tmp 残留
        summary2 = dict(summary, date="20260906")
        write_alignment_summary(target, summary2)
        assert json.loads(target.read_text(encoding="utf-8"))["date"] == "20260906"
        assert not list(target.parent.glob(".alignment_*"))
