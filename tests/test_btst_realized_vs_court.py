"""btst_realized_vs_court — 六类宇宙分裂分类 + 聚合的 fixture 驱动测试.

零网络/零 gitignored 资产: 全部输入在测试内构造 (R10 slot 自足纪律)。
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts.btst_realized_vs_court import (
    CLASSES,
    Reconciliation,
    SignalRecord,
    build_alignment_summary,
    build_classification_inputs,
    classify_buy,
    extract_realized,
    normalize_day,
    realization_gap_summary,
    realized_map_from_journal,
    realized_stats,
    reconcile,
    render_md,
    replay_divergence_diagnosis,
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


# ---------- R121b Op2: v2 台账 union 接入 (时代归属 + 分 store 披露) ----------

from scripts.btst_realized_vs_court import (  # noqa: E402
    STORE_LEDGER_V2,
    STORE_LEGACY_JOURNAL,
    build_alignment_summary as _build_alignment_summary,
    load_ledger_buys,
    stores_block,
)

_LEDGER_DDL = """
CREATE TABLE trades (
    trade_id TEXT PRIMARY KEY, ledger_id TEXT, ticker TEXT, setup TEXT,
    setup_version TEXT, signal_date TEXT, planned_entry_date TEXT,
    planned_weight REAL, priority INTEGER, state TEXT, execution_mode TEXT,
    fill_source TEXT, entry_date TEXT, raw_entry_price REAL, quantity INTEGER,
    entry_commission REAL, entry_tax REAL, entry_slippage REAL,
    exit_trigger_date TEXT, exit_date TEXT, raw_exit_price REAL,
    exit_commission REAL, exit_tax REAL, exit_slippage REAL,
    armed_at TEXT, highest_close REAL, exit_line TEXT,
    last_evaluated_date TEXT, forced_exit_target_date TEXT, provenance_json TEXT
)
"""


def _make_ledger(tmp_path, rows):
    p = tmp_path / "ledger.sqlite3"
    import sqlite3
    conn = sqlite3.connect(p)
    conn.execute(_LEDGER_DDL)
    conn.executemany(
        "INSERT INTO trades (signal_date, ticker, state, raw_entry_price, quantity,"
        " entry_commission, entry_tax, entry_slippage, raw_exit_price,"
        " exit_commission, exit_tax, exit_slippage)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    return p


class TestR187DataWindow:
    """R187 Op1: 对账载荷增发 data_window (事件表 signal_date min/max 数据真相).

    R186 Op1『请求态窗口冒充数据覆盖』家族收口的消费面续 — 本链 summary 的
    court_window 来自 manifest 请求窗 (_court_window_from_manifest), 被宇宙
    对齐行/对账 MD 报告行渲染成 court 证据覆盖 (今日实录 20250701..20260911
    vs 表真相 20250702..20260909)。钉住: 载荷增发 data_window + 消费面优先
    渲染数据真相 + 旧载荷 (键缺席) 形状逐字节不变。
    """

    def _recon(self):
        court_rows = [
            {"ts_code": "301234.SZ", "signal_date": 20260807, "strength": 0.43},
            {"ts_code": "601212.SH", "signal_date": 20260821, "strength": 0.655},
        ]
        journal = [_journal_buy("20260807", "301234", strength=0.50)]
        inputs = _inputs(
            court_rows,
            sessions=["20260807", "20260821"],
            regime={"20260807": "normal", "20260821": "normal"},
            panel=["20260807", "20260821"],
        )
        return reconcile(journal, inputs)

    def test_payload_carries_data_window_when_provided(self):
        payload = summary_payload(
            self._recon(),
            court_window=("20250701", "20260911"),
            data_window=("20250702", "20260909"),
        )
        assert payload["data_window"] == {"start": "20250702", "end": "20260909"}
        # 请求窗字段原样保留 (outside_window 分类窗语义 + 旧消费面兼容)
        assert payload["court_window"] == {"start": "20250701", "end": "20260911"}

    def test_payload_omits_data_window_when_none(self):
        payload = summary_payload(
            self._recon(), court_window=("20250701", "20260911"), data_window=None
        )
        assert "data_window" not in payload

    def test_alignment_summary_carries_data_window_when_provided(self):
        summary = build_alignment_summary(
            self._recon(),
            court_window=("20250701", "20260911"),
            data_window=("20250702", "20260909"),
            summary_date="20260912",
        )
        assert summary["data_window"] == {"start": "20250702", "end": "20260909"}
        assert summary["court_window"] == {"start": "20250701", "end": "20260911"}

    def test_alignment_summary_omits_data_window_when_none(self):
        summary = build_alignment_summary(
            self._recon(),
            court_window=None,
            data_window=None,
            summary_date="20260912",
        )
        assert "data_window" not in summary
        assert "court_window" not in summary

    def test_render_md_prefers_data_window(self):
        payload = summary_payload(
            self._recon(),
            court_window=("20250701", "20260911"),
            data_window=("20250702", "20260909"),
        )
        text = render_md(payload)
        assert "court 窗口: 20250702..20260909" in text
        assert "20260911" not in text

    def test_render_md_falls_back_to_court_window(self):
        payload = summary_payload(
            self._recon(), court_window=("20250701", "20260911"), data_window=None
        )
        assert "court 窗口: 20250701..20260911" in render_md(payload)

    def test_render_md_omits_window_line_when_both_absent(self):
        payload = summary_payload(self._recon(), court_window=None, data_window=None)
        # 『窗口行』形态是 "court 窗口: s..e"; 分类图例 "T0 不在 court 窗口内"
        # 含同词, 不能作全文断言。
        assert "court 窗口: " not in render_md(payload)

    def test_data_window_emitted_without_court_window(self):
        # R187 Op2 P11 钉住: data_window 增发不依赖 court_window 在场 —
        # 生产上 manifest 窗缺席即 fail-closed (两者并存恒成立), 但组合语义
        # 不应被隐式耦合 (增发嵌套进 court_window 检查下 = 键名漂移盲区)。
        payload = summary_payload(
            self._recon(), court_window=None, data_window=("20250702", "20260909")
        )
        assert payload["data_window"] == {"start": "20250702", "end": "20260909"}
        assert "court_window" not in payload
        summary = build_alignment_summary(
            self._recon(),
            court_window=None,
            data_window=("20250702", "20260909"),
            summary_date="20260912",
        )
        assert summary["data_window"] == {"start": "20250702", "end": "20260909"}
        assert "court_window" not in summary
        assert "court 窗口: 20250702..20260909" in render_md(payload)


class TestR187Op2RenderMdMalformedDataWindow:
    """R187 Op2: render_md 面 data_window 形状守卫钉住。

    Op1 只钉了对齐行消费面的畸形回退 (参数化); render_md 面的 has_data_window
    守卫此前无值钉住 — P04' 变异 (end 检查改 True) 实跑无牙实证: 畸形
    data_window 会把非 str 值直拼进窗口行。守卫契约: 非 dict / 任一端非
    非空 str / 任一端非数字串 → 整块弃用, 落 court_window 现行分支。
    """

    def _recon(self):
        court_rows = [
            {"ts_code": "301234.SZ", "signal_date": 20260807, "strength": 0.43},
        ]
        journal = [_journal_buy("20260807", "301234", strength=0.50)]
        inputs = _inputs(
            court_rows,
            sessions=["20260807"],
            regime={"20260807": "normal"},
            panel=["20260807"],
        )
        return reconcile(journal, inputs)

    @pytest.mark.parametrize(
        "poison",
        [
            "not-a-dict",
            20260909,
            True,
            {"start": "20250702", "end": 20260909},
            {"start": 20250702, "end": "20260909"},
            {"start": "20250702", "end": ""},
        ],
    )
    def test_render_md_malformed_data_window_falls_back(self, poison):
        """守卫契约 = isinstance dict + 两端非空 str (8 位形状由生产者
        court_window_from_events + 消费面对齐行面 _DATE_8_RE 守卫, render_md
        面不重复); 类型毒化 → 整块弃用落 court_window 现行分支逐字节。"""
        payload = {
            "class_counts": dict.fromkeys(CLASSES, 0),
            "total_buys": 1,
            "court_window": {"start": "20250701", "end": "20260904"},
            "data_window": poison,
        }
        assert "court 窗口: 20250701..20260904" in render_md(payload)
        assert "data_window" in payload  # 载荷原样 (渲染面不裁剪)


class TestLedgerUnion:
    def test_load_ledger_buys_normalizes_and_nets_realized(self, tmp_path):
        p = _make_ledger(tmp_path, [
            # 净额口径: basis=100*10+0+0+0=1000, proceeds=110*10-0-5-0=1095 → +9.5%
            ("2026-08-14", "600487", "closed", 100.0, 10, 0.0, 0.0, 0.0, 110.0, 0.0, 5.0, 0.0),
            # open 仓 → realized None (未平仓不冒充已兑现)
            ("2026-08-31", "002757", "open", 17.74, 100, 0.0, 0.0, 0.0, None, None, None, None),
        ])
        buys = load_ledger_buys(p)
        assert len(buys) == 2
        first, second = buys
        assert first["date"] == "20260814" and first["ticker"] == "600487"
        assert first["store"] == STORE_LEDGER_V2
        assert first["horizon"] == 10
        assert first["realized_pct"] == pytest.approx(9.5)
        assert second["realized_pct"] is None

    def test_load_ledger_corrupt_ticker_fails_closed(self, tmp_path):
        p = _make_ledger(tmp_path, [
            ("2026-08-14", "600487.SZ", "closed", 10.0, 10, 0, 0, 0, 11.0, 0, 0, 0),
        ])
        with pytest.raises(ValueError):
            load_ledger_buys(p)

    def test_reconcile_union_store_attribution(self):
        # 独立最小世界: 一天 court 两票, journal 一票 + 台账一票 (互不重叠)
        inputs = _inputs(
            [{"ts_code": "000001.SZ", "signal_date": 20260821},
             {"ts_code": "600487.SH", "signal_date": 20260821}],
            sessions=["20260821"], regime={"20260821": "normal"}, panel=["20260821"],
        )
        journal = [_journal_buy("20260821", "000001", strength=0.7),
                   _journal_exit("20260821", "000001", "+8.0")]
        ledger_buys = [{"date": "20260821", "ticker": "600487", "horizon": 10,
                        "trigger_strength": None, "realized_pct": -8.93,
                        "store": STORE_LEDGER_V2}]
        recon = reconcile(journal, inputs, extra_buys=ledger_buys)
        assert len(recon.records) == 2
        stores_seen = {r.store for r in recon.records}
        assert stores_seen == {STORE_LEGACY_JOURNAL, STORE_LEDGER_V2}
        ledger_rec = next(r for r in recon.records if r.store == STORE_LEDGER_V2)
        assert ledger_rec.classification == "matched"
        # 台账无信号强度 → 不以 0.0 冒充, 漂移置 None
        assert ledger_rec.paper_strength is None and ledger_rec.strength_drift is None
        assert ledger_rec.realized_pct == pytest.approx(-8.93)

    def test_reconcile_cross_store_duplicate_counted(self):
        inputs = _inputs(
            [{"ts_code": "000001.SZ", "signal_date": 20260821}],
            sessions=["20260821"], regime={"20260821": "normal"}, panel=["20260821"],
        )
        journal = [_journal_buy("20260821", "000001")]
        ledger_buys = [{"date": "20260821", "ticker": "000001", "horizon": 10,
                        "trigger_strength": None, "realized_pct": None,
                        "store": STORE_LEDGER_V2}]
        recon = reconcile(journal, inputs, extra_buys=ledger_buys)
        # journal 先史 precedence: 保留 journal 记录, 台账重键计数显形
        assert len(recon.records) == 1
        assert recon.records[0].store == STORE_LEGACY_JOURNAL
        assert recon.duplicate_buys_skipped == 1

    def test_stores_block_and_alignment_summary(self):
        inputs = _inputs(
            [{"ts_code": "000001.SZ", "signal_date": 20260821},
             {"ts_code": "600487.SH", "signal_date": 20260821}],
            sessions=["20260821"], regime={"20260821": "normal"}, panel=["20260821"],
        )
        journal = [_journal_buy("20260821", "000001"),
                   _journal_exit("20260821", "000001", "-5.0"),
                   # journal 僵尸 open (有 BUY 无 EXIT)
                   _journal_buy("20260821", "999999")]
        ledger_buys = [{"date": "20260821", "ticker": "600487", "horizon": 10,
                        "trigger_strength": None, "realized_pct": -8.93,
                        "store": STORE_LEDGER_V2}]
        recon = reconcile(journal, inputs, extra_buys=ledger_buys)
        stores = stores_block(recon)
        assert stores[STORE_LEGACY_JOURNAL]["buys"] == 2
        assert stores[STORE_LEGACY_JOURNAL]["open_buys"] == 1
        assert stores[STORE_LEDGER_V2]["buys"] == 1
        assert stores[STORE_LEDGER_V2]["open_buys"] == 0
        assert stores[STORE_LEDGER_V2]["realized_only"]["n"] == 1
        summary = build_alignment_summary(recon, court_window=None, summary_date="20260905")
        assert summary["stores"] == stores
        assert summary["total_buys"] == 3

    def test_render_md_shows_store_era_table(self):
        inputs = _inputs(
            [{"ts_code": "000001.SZ", "signal_date": 20260821}],
            sessions=["20260821"], regime={"20260821": "normal"}, panel=["20260821"],
        )
        recon = reconcile([_journal_buy("20260821", "000001")], inputs,
                          extra_buys=[{"date": "20260821", "ticker": "600487",
                                       "horizon": 10, "trigger_strength": None,
                                       "realized_pct": -8.93,
                                       "store": STORE_LEDGER_V2}])
        payload = summary_payload(recon, court_window=("20250701", "20260901"))
        text = render_md(payload)
        assert "ledger_v2" in text and "legacy_journal" in text
        assert json.loads(json.dumps(payload))["stores"][STORE_LEDGER_V2]["buys"] == 1


class TestR121cRework:
    def test_ledger_null_cost_fails_closed(self, tmp_path):
        """F1 (修复前 RED: realized 10.0% 虚高产出) — NULL 成本列 = 损坏, fail-closed."""
        p = _make_ledger(tmp_path, [
            ("2026-08-14", "600487", "closed", 100.0, 10, 0.0, 0.0, 0.0, 110.0, 0.0, None, 0.0),
        ])
        with pytest.raises(ValueError, match="NULL cost"):
            load_ledger_buys(p)

    def test_post_ledger_start_buys_derived_count(self):
        """F2: journal BUY ≥ 台账首信号日 = 时代重叠, 纯派生不硬编码日期."""
        inputs = _inputs(
            [{"ts_code": "000001.SZ", "signal_date": 20260821}],
            sessions=["20260821"], regime={"20260821": "normal"}, panel=["20260821"],
        )
        journal = [
            _journal_buy("20260810", "000001"),  # 台账前纪元
            _journal_buy("20260821", "000002"),  # ≥ 台账首日 → 结构异常笔
        ]
        ledger_buys = [{"date": "20260814", "ticker": "600487", "horizon": 10,
                        "trigger_strength": None, "realized_pct": None,
                        "store": STORE_LEDGER_V2}]
        recon = reconcile(journal, inputs, extra_buys=ledger_buys)
        stores = stores_block(recon)
        assert stores[STORE_LEGACY_JOURNAL]["post_ledger_start_buys"] == 1

    def test_post_ledger_count_absent_without_ledger(self):
        """台账缺席 → 不判定 (键不存在, legacy-only 渲染不受影响)."""
        inputs = _inputs(
            [{"ts_code": "000001.SZ", "signal_date": 20260821}],
            sessions=["20260821"], regime={"20260821": "normal"}, panel=["20260821"],
        )
        recon = reconcile([_journal_buy("20260821", "000001")], inputs)
        stores = stores_block(recon)
        assert "post_ledger_start_buys" not in stores[STORE_LEGACY_JOURNAL]


class TestR122RealizationGap:
    """实现缺口归因 (R122 Op1): 恒等分解 E[realized]=E[court|matched]+E[realized−court]."""

    @staticmethod
    def _record(realized, court, agree=True, horizon=10):
        return SignalRecord(
            signal_date="20260821",
            ticker="000001",
            horizon=horizon,
            paper_strength=0.6,
            classification="matched",
            realized_pct=realized,
            court_gross_ret_horizon=court,
            direction_agree=agree,
            store=STORE_LEDGER_V2,
        )

    def test_identity_holds_end_to_end(self):
        records = [
            self._record(-8.0, -10.0),
            self._record(1.0, 0.0),
            self._record(12.0, 10.0, agree=False),
        ]
        gap = realization_gap_summary(records)
        assert gap is not None
        assert gap["n"] == 3
        assert gap["court_conditional_expectancy_pct"] == pytest.approx(0.0, abs=1e-6)
        assert gap["realized_expectancy_pct"] == pytest.approx(5.0 / 3.0, abs=1e-3)
        # 恒等式: court 同票假想 + 逐笔实现差 == realized (无残差)
        assert (
            gap["court_conditional_expectancy_pct"] + gap["realization_gap_pp"]
            == pytest.approx(gap["realized_expectancy_pct"], abs=1e-3)
        )
        assert gap["direction_agree_n"] == 2 and gap["direction_disagree_n"] == 1
        assert gap["horizons"] == {"10": 3}

    def test_malformed_and_open_records_excluded(self):
        """两端点不齐备/畸形 (None/bool/str/NaN/inf) 全部排除; 全排除 → None."""
        records = [
            self._record(None, -5.0),          # 未平仓 → realized 端缺失
            self._record(3.0, None),           # court 缺值
            self._record(True, -5.0),          # bool 显式排除 (True 当 1.0 是形状欺骗)
            self._record("3.0", -5.0),         # str
            self._record(float("nan"), -5.0),  # NaN
            self._record(float("inf"), -5.0),  # inf
        ]
        assert realization_gap_summary(records) is None

    def test_empty_gives_none(self):
        assert realization_gap_summary([]) is None
        assert realization_gap_summary([self._record(None, None)]) is None

    def test_horizon_composition_mixed(self):
        records = [
            self._record(-8.0, -10.0, horizon=8),
            self._record(1.0, 0.0, horizon=10),
        ]
        gap = realization_gap_summary(records)
        assert gap is not None
        assert gap["horizons"] == {"8": 1, "10": 1}

    def test_selection_dominates_real_data_shape(self):
        """真实数据形态回归锚: selection 项量级 ≫ 实现差 (20260905 实证 -8.34% vs +0.48pp)."""
        court = [-8.91, 1.52, -4.85, -35.43, -7.09, 10.02, 11.29, -10.61,
                 -13.74, -7.62, 1.24, -4.71]
        realized = [-6.42, 6.62, -4.41, -35.47, -8.56, 16.07, 10.56, -11.19,
                    -14.29, -8.22, 0.58, -5.33]
        records = [
            self._record(r, c, agree=(r >= 0) == (c >= 0),
                         horizon=8 if i < 5 else 10)
            for i, (r, c) in enumerate(zip(realized, court))
        ]
        gap = realization_gap_summary(records)
        assert gap is not None
        assert abs(gap["court_conditional_expectancy_pct"]) > abs(
            gap["realization_gap_pp"]
        )

    def test_alignment_summary_carries_block(self):
        inputs = _inputs(
            [{"ts_code": "000001.SZ", "signal_date": 20260821,
              "strength": 0.6, "gross_ret_t10": -0.0989}],
            sessions=["20260821"], regime={"20260821": "normal"}, panel=["20260821"],
        )
        journal = [
            _journal_buy("20260821", "000001"),
            _journal_exit("20260821", "000001", "-6.42"),
        ]
        recon = reconcile(journal, inputs)
        summary = build_alignment_summary(
            recon, court_window=("20250701", "20260901"), summary_date="20260905"
        )
        gap = summary.get("realization_gap")
        assert isinstance(gap, dict)
        assert gap["n"] == 1
        assert gap["court_conditional_expectancy_pct"] == pytest.approx(-9.89, abs=1e-3)
        assert gap["realized_expectancy_pct"] == pytest.approx(-6.42, abs=1e-3)

    def test_alignment_summary_omits_key_when_no_closed_matched(self):
        """全部 matched 未平仓 → realization_gap 键省略 (旧消费者按缺键回退)."""
        inputs = _inputs(
            [{"ts_code": "000001.SZ", "signal_date": 20260821,
              "strength": 0.6, "gross_ret_t10": -0.0989}],
            sessions=["20260821"], regime={"20260821": "normal"}, panel=["20260821"],
        )
        recon = reconcile([_journal_buy("20260821", "000001")], inputs)
        summary = build_alignment_summary(
            recon, court_window=None, summary_date="20260905"
        )
        assert "realization_gap" not in summary

    def test_render_md_attribution_section(self):
        inputs = _inputs(
            [{"ts_code": "000001.SZ", "signal_date": 20260821,
              "strength": 0.6, "gross_ret_t10": -0.0989}],
            sessions=["20260821"], regime={"20260821": "normal"}, panel=["20260821"],
        )
        journal = [
            _journal_buy("20260821", "000001"),
            _journal_exit("20260821", "000001", "-6.42"),
        ]
        recon = reconcile(journal, inputs)
        payload = summary_payload(recon, court_window=None)
        text = render_md(payload)
        assert "实现缺口归因" in text
        assert "court 同票假想期望" in text and "逐笔实现差" in text
        # 键省略 (全 open) → 段落省略
        recon_open = reconcile([_journal_buy("20260821", "000001")], inputs)
        assert "实现缺口归因" not in render_md(
            summary_payload(recon_open, court_window=None)
        )

    def test_render_md_count_contradiction_section_omitted(self):
        """R122b 对抗收口: 块 n > class_counts.matched = 工件损坏 → 整段省略."""
        inputs = _inputs(
            [{"ts_code": "000001.SZ", "signal_date": 20260821,
              "strength": 0.6, "gross_ret_t10": -0.0989}],
            sessions=["20260821"], regime={"20260821": "normal"}, panel=["20260821"],
        )
        journal = [
            _journal_buy("20260821", "000001"),
            _journal_exit("20260821", "000001", "-6.42"),
        ]
        recon = reconcile(journal, inputs)
        payload = summary_payload(recon, court_window=None)
        payload["realization_gap"] = {**payload["realization_gap"], "n": 999}
        text = render_md(payload)
        assert "实现缺口归因" not in text

    def test_render_md_direction_line_and_sample_note(self):
        """R122c: MD 归因段方向行 (含 court 缺向计数) + 样本不足尾注."""
        inputs = _inputs(
            [{"ts_code": "000001.SZ", "signal_date": 20260821,
              "strength": 0.6, "gross_ret_t10": -0.0989}],
            sessions=["20260821"], regime={"20260821": "normal"}, panel=["20260821"],
        )
        journal = [
            _journal_buy("20260821", "000001"),
            _journal_exit("20260821", "000001", "-6.42"),
        ]
        recon = reconcile(journal, inputs)
        payload = summary_payload(recon, court_window=None)
        payload["realization_gap"] = {
            **payload["realization_gap"],
            "direction_agree_n": 0, "direction_disagree_n": 0,
        }
        text = render_md(payload)
        assert "方向对照" in text and "court 缺向 1" in text
        assert "样本不足" in text and "只披露不判定" in text

    def test_render_md_direction_malformed_omits_line_only(self):
        """方向计数畸形 (agree+disagree>n) → 方向行省略, 归因段保留."""
        inputs = _inputs(
            [{"ts_code": "000001.SZ", "signal_date": 20260821,
              "strength": 0.6, "gross_ret_t10": -0.0989}],
            sessions=["20260821"], regime={"20260821": "normal"}, panel=["20260821"],
        )
        journal = [
            _journal_buy("20260821", "000001"),
            _journal_exit("20260821", "000001", "-6.42"),
        ]
        recon = reconcile(journal, inputs)
        payload = summary_payload(recon, court_window=None)
        payload["realization_gap"] = {
            **payload["realization_gap"],
            "direction_agree_n": 5, "direction_disagree_n": 0,
        }
        text = render_md(payload)
        assert "实现缺口归因" in text
        # 文档头注固有『双锚点方向对照』字样 — 用渲染行的唯一前缀断言
        assert "方向对照: 一致" not in text


# ---------------------------------------------------------------------------
# R138 Op1: 重放分歧 typed 诊断 — 未匹配 BUY 经现行公式重放, 根因自解释.
# 纯注入 (replay_fn) fixture: 零网络/零 gitignored 资产 (R10 slot 自足纪律).
# ---------------------------------------------------------------------------


def _divergent_rec(cls: str, day: str = "20260811", ticker: str = "603284") -> SignalRecord:
    return SignalRecord(
        signal_date=day, ticker=ticker, horizon=10, paper_strength=0.83,
        classification=cls,
    )


def _replay_outcome(hit: bool, miss_stage: str | None, strength: float = 0.0):
    return {"hit": hit, "miss_stage": miss_stage, "trigger_strength": strength}


class TestClassifyReplayDivergence:
    """重放结局 → typed 根因 (优先级: error > hit > stage 前缀)."""

    def test_six_outcomes_map_to_typed_classes(self):
        from scripts.btst_realized_vs_court import classify_replay_divergence

        assert classify_replay_divergence(hit=True, miss_stage=None, error=None) == "replay_hit_now"
        assert classify_replay_divergence(hit=False, miss_stage="c2_flow_below_mean", error=None) == "flow_input_divergence"
        assert classify_replay_divergence(hit=False, miss_stage="c2_flow_missing", error=None) == "flow_input_divergence"
        assert classify_replay_divergence(hit=False, miss_stage="c3_industry_weak", error=None) == "industry_condition_divergence"
        assert classify_replay_divergence(hit=False, miss_stage="c0_trigger_row_missing", error=None) == "universe_panel_divergence"
        assert classify_replay_divergence(hit=False, miss_stage="c1_limit_up_pct", error=None) == "universe_panel_divergence"
        assert classify_replay_divergence(hit=False, miss_stage="c5_bonus_insufficient", error=None) == "condition_divergence"
        assert classify_replay_divergence(hit=False, miss_stage=None, error="ValueError: boom") == "replay_error"


class TestReplayDivergenceDiagnosis:
    def test_no_divergent_records_returns_none(self):
        records = [
            _divergent_rec("matched"),
            _divergent_rec("outside_window", day="20250101"),
        ]
        assert replay_divergence_diagnosis(
            records, lambda t, d: _replay_outcome(False, "c3_industry_weak")
        ) is None

    def test_six_divergent_records_typed_and_deterministic(self):
        outcomes = {
            "20260811": _replay_outcome(False, "c3_industry_weak"),
            "20260813": _replay_outcome(False, "c2_flow_below_mean"),
            "20260814": _replay_outcome(True, None, strength=0.72),
            "20260815": _replay_outcome(False, "c0_trigger_row_missing"),
            "20260817": _replay_outcome(False, "c4_insufficient_history"),
        }

        def fn(ticker: str, day: str):
            return outcomes[day]

        records = [
            _divergent_rec("day_missing_from_court", day="20260811", ticker="603284"),
            _divergent_rec("day_missing_from_court", day="20260813", ticker="002066"),
            _divergent_rec("ticker_not_in_court_day", day="20260814", ticker="600487"),
            _divergent_rec("ticker_not_in_court_day", day="20260815", ticker="600488"),
            _divergent_rec("day_missing_from_court", day="20260817", ticker="600489"),
            _divergent_rec("matched", day="20260820", ticker="600491"),
        ]
        payload = replay_divergence_diagnosis(records, fn)
        assert payload is not None
        assert payload["diagnosable"] == 5
        assert payload["by_class"]["industry_condition_divergence"] == 1
        assert payload["by_class"]["flow_input_divergence"] == 1
        assert payload["by_class"]["replay_hit_now"] == 1
        assert payload["by_class"]["universe_panel_divergence"] == 1
        assert payload["by_class"]["condition_divergence"] == 1
        assert payload["by_class"]["replay_error"] == 0
        # matched 不进诊断面
        assert all(d["ticker"] != "600491" for d in payload["details"])
        # 确定性: details 按 (signal_date, ticker) 排序
        keys = [(d["signal_date"], d["ticker"]) for d in payload["details"]]
        assert keys == sorted(keys)
        hit_row = next(
            d for d in payload["details"] if d["classification"] == "replay_hit_now"
        )
        assert hit_row["replay_trigger_strength"] == pytest.approx(0.72)
        assert hit_row["miss_stage"] is None

    def test_replay_exception_typed_not_swallowed(self):
        def fn(ticker: str, day: str):
            raise RuntimeError("flow store corrupt")

        payload = replay_divergence_diagnosis(
            [_divergent_rec("day_missing_from_court")], fn
        )
        assert payload is not None
        assert payload["by_class"]["replay_error"] == 1
        detail = payload["details"][0]
        assert detail["classification"] == "replay_error"
        assert "RuntimeError" in detail["error"]

    def test_replay_none_outcome_typed(self):
        payload = replay_divergence_diagnosis(
            [_divergent_rec("day_missing_from_court")], lambda t, d: None
        )
        assert payload is not None
        assert payload["by_class"]["replay_error"] == 1
        assert "no_outcome" in payload["details"][0]["error"]


class TestRenderDivergenceDiagnosis:
    def _payload_with_divergents(self) -> dict:
        records = [
            _divergent_rec("day_missing_from_court", day="20260811", ticker="603284"),
            _divergent_rec("matched", day="20260820", ticker="600491"),
        ]

        def fn(ticker: str, day: str):
            return _replay_outcome(False, "c3_industry_weak")

        payload = summary_payload(
            Reconciliation(
                records=records,
                matched_records=[records[1]],
                class_counts={c: 0 for c in CLASSES}
                | {"day_missing_from_court": 1, "matched": 1},
            ),
            court_window=None,
        )
        payload["divergence_diagnosis"] = replay_divergence_diagnosis(records, fn)
        return payload

    def test_without_diagnosis_key_render_unchanged(self):
        """缺诊断键 → 无新节 (fail-open noop, 旧形态逐字保留)."""
        inputs = _inputs(
            [{"ts_code": "000001.SZ", "signal_date": 20260821,
              "strength": 0.6, "gross_ret_t10": -0.0989}],
            sessions=["20260821"], regime={"20260821": "normal"}, panel=["20260821"],
        )
        recon = reconcile([_journal_buy("20260821", "000001")], inputs)
        text = render_md(summary_payload(recon, court_window=None))
        assert "重放分歧诊断" not in text
        assert "diagnosis_unavailable" not in text

    def test_with_diagnosis_key_renders_typed_section(self):
        text = render_md(self._payload_with_divergents())
        assert "## 重放分歧诊断" in text
        assert "industry_condition_divergence" in text
        assert "603284" in text and "20260811" in text
        assert "不构成任何行为授权" in text

    def test_unavailable_key_renders_single_disclosure_line(self):
        inputs = _inputs(
            [{"ts_code": "000001.SZ", "signal_date": 20260821,
              "strength": 0.6, "gross_ret_t10": -0.0989}],
            sessions=["20260821"], regime={"20260821": "normal"}, panel=["20260821"],
        )
        recon = reconcile([_journal_buy("20260821", "000001")], inputs)
        payload = summary_payload(recon, court_window=None)
        payload["divergence_diagnosis_unavailable"] = "OSError: panel missing"
        text = render_md(payload)
        assert "诊断不可用" in text and "OSError: panel missing" in text
        assert "## 重放分歧诊断" not in text


# ---------------------------------------------------------------------------
# R138 Op3 对抗审查: 畸形重放结局 typed 化 + SystemExit 逃逸收口.
# ---------------------------------------------------------------------------


class TestReplayBadOutcomeContract:
    """重放结局严格契约: hit 必须恰为 bool, 畸形形态 typed replay_error 不冒充分类."""

    def test_missing_hit_key_does_not_masquerade_as_miss(self):
        records = [_divergent_rec("day_missing_from_court")]
        outcome = {"miss_stage": "c3_industry_weak", "trigger_strength": 0.0}
        payload = replay_divergence_diagnosis(records, lambda t, d: outcome)
        assert payload["by_class"]["replay_error"] == 1
        assert "replay_bad_outcome" in payload["details"][0]["error"]

    def test_non_bool_hit_does_not_masquerade_as_hit_now(self):
        records = [_divergent_rec("day_missing_from_court")]
        outcome = {"hit": "no", "miss_stage": None, "trigger_strength": 0.0}
        payload = replay_divergence_diagnosis(records, lambda t, d: outcome)
        assert payload["by_class"]["replay_error"] == 1
        assert "replay_bad_outcome" in payload["details"][0]["error"]

    def test_well_formed_outcome_still_classified(self):
        records = [_divergent_rec("day_missing_from_court")]
        outcome = {"hit": True, "miss_stage": None, "trigger_strength": 0.9}
        payload = replay_divergence_diagnosis(records, lambda t, d: outcome)
        assert payload["by_class"]["replay_hit_now"] == 1


class TestAttachDivergenceDiagnosisWiring:
    """main 接线: 构造器 fail-loud (含 SystemExit) → typed 单行, 六类报告不受损."""

    def test_systemexit_from_load_panel_typed_unavailable(self, tmp_path):
        from scripts.btst_realized_vs_court import (
            attach_divergence_diagnosis,
        )

        # 空 court 表 → BUY 分类为 day_missing_from_court (诊断面的触发形态)
        inputs = _inputs(
            [],
            sessions=["20260811"], regime={"20260811": "normal"}, panel=["20260811"],
        )
        recon = reconcile([_journal_buy("20260811", "000001")], inputs)
        assert recon.class_counts["day_missing_from_court"] == 1
        payload = summary_payload(recon, court_window=None)
        # 空目录 → load_panel SystemExit('panel empty') — 非 Exception 子类
        (tmp_path / "daily").mkdir()
        attach_divergence_diagnosis(
            payload, recon, raw_dir=tmp_path, regime_labels={"20260811": "normal"}
        )
        assert "divergence_diagnosis_unavailable" in payload
        assert "SystemExit" in payload["divergence_diagnosis_unavailable"]
        assert "divergence_diagnosis" not in payload
        # 六类报告面不受损
        assert payload["class_counts"]["day_missing_from_court"] == 1
