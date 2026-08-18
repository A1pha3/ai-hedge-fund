"""Tests for the live BTST setup-output logger (out-of-sample accumulation)."""

from __future__ import annotations

import json
from datetime import date

from src.screening.offensive.daily_action import DailyAction
from src.screening.offensive.setup_output_log import log_setup_outputs


def _action(ticker: str, **kw) -> DailyAction:
    base = dict(
        ticker=ticker,
        setup="btst_breakout",
        action="BUY",
        kelly_pct=0.067,
        entry_price=9.79,
        soft_stop=9.0,
        hard_stop=9.0,
        time_exit="T+10",
        invalidation_condition="",
        distribution_summary="n=133 winrate=68% cv=1.9 E=+8.2%",
        reasoning="",
        trigger_strength=0.62,
    )
    base.update(kw)
    return DailyAction(**base)


def test_log_setup_outputs_writes_structured_records(tmp_path):
    cand = _action(
        "600497",
        metadata={
            "pct_change": 10.0,
            "main_net_inflow": 3000.0,
            "industry_pct": 1.5,
            "pre_5d_runup_pct": 4.2,
        },
    )
    blocked = _action(
        "600362",
        action="SKIP",
        kelly_pct=0.0,
        entry_price=0.0,
        degraded=True,
        block_reason="readiness degraded: fund_flow_history_1d_lt_min_5d",
        trigger_strength=0.0,
    )

    path = log_setup_outputs(
        date(2026, 7, 14), [cand], [blocked], regime="normal", out_dir=tmp_path
    )

    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert len(records) == 2

    rec = next(r for r in records if r["ticker"] == "600497")
    assert rec["schema_version"] == 1
    assert rec["signal_date"] == "20260714"
    assert rec["setup"] == "btst_breakout"
    assert rec["plan_eligible"] is True
    assert rec["degraded"] is False
    assert rec["trigger_strength"] == 0.62
    assert rec["entry_price"] == 9.79
    assert rec["regime"] == "normal"
    assert rec["main_net_inflow"] == 3000.0
    assert rec["pre_5d_runup_pct"] == 4.2
    assert rec["industry_pct"] == 1.5

    blk = next(r for r in records if r["ticker"] == "600362")
    assert blk["plan_eligible"] is False
    assert blk["degraded"] is True
    assert "fund_flow_history" in blk["block_reason"]


def test_log_setup_outputs_is_idempotent_per_signal_date(tmp_path):
    cand = _action("600497", metadata={"pct_change": 10.0})
    for _ in range(3):
        path = log_setup_outputs(
            date(2026, 7, 14), [cand], [], regime="normal", out_dir=tmp_path
        )
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert len(records) == 1  # rerun overwrites the day's file, never duplicates


# --- 信号覆盖断层审计 (对抗审查 BUG-1, 2026-08-17) -------------------------------


def test_audit_signal_log_coverage_detects_missing_sessions(tmp_path):
    from src.screening.offensive.setup_output_log import audit_signal_log_coverage

    # 8-05..8-07 无日志, 8-08 有 (0 字节 = 跑过无信号), 8-09 有内容
    (tmp_path / "20260808.jsonl").touch()
    (tmp_path / "20260809.jsonl").write_text('{"ticker": "x"}\n', encoding="utf-8")

    sessions = ["20260805", "20260806", "20260807", "20260808", "20260809", "20260810"]
    gaps = audit_signal_log_coverage(sessions, before="20260810", log_dir=tmp_path)

    # 0 字节文件 = 已覆盖; 当次处理的信号日 (before) 不算缺口; 无日志的才是缺口
    assert gaps == ["20260805", "20260806", "20260807"]


def test_audit_signal_log_coverage_ignores_malformed_sessions(tmp_path):
    from src.screening.offensive.setup_output_log import audit_signal_log_coverage

    sessions = ["20260805", "", "2026-08-06", "202608 7", 20260808, None, "20260901"]
    gaps = audit_signal_log_coverage(sessions, before="20260902", log_dir=tmp_path)
    # 只有合法 YYYYMMDD 字符串参与审计; 全部缺失 → 只剩 20260805/20260901
    assert gaps == ["20260805", "20260901"]


def test_audit_signal_log_coverage_missing_dir_all_missing(tmp_path):
    from src.screening.offensive.setup_output_log import audit_signal_log_coverage

    # glob 对不存在目录静默返回空 → 全部审计日视为缺失 (从未运行过).
    # 调用方 (warn_missing_signal_log_sessions) 用 lookback 窗口保证告警有界.
    gaps = audit_signal_log_coverage(
        ["20260805", "20260806"], before="20260807", log_dir=tmp_path / "nonexistent"
    )
    assert gaps == ["20260805", "20260806"]


def test_warn_missing_signal_log_sessions_lookback_is_bounded(tmp_path):
    from src.screening.offensive.setup_output_log import (
        warn_missing_signal_log_sessions,
    )

    # 40 个交易日全部无日志; 默认 lookback=30 只审计最近 30 个 → 告警有界.
    sessions = [f"2026{m:02d}{d:02d}" for m in range(1, 3) for d in range(1, 21)]
    sessions = sorted(sessions)[:40]
    calendar = tmp_path / "trade_calendar.json"
    calendar.write_text(json.dumps(sessions), encoding="utf-8")

    gaps = warn_missing_signal_log_sessions(
        before="20261231", calendar_path=calendar, log_dir=tmp_path
    )
    assert gaps == sessions[-30:]


def test_warn_missing_signal_log_sessions_warns_and_returns_gaps(tmp_path, caplog):
    import logging as _logging

    from src.screening.offensive.setup_output_log import (
        warn_missing_signal_log_sessions,
    )

    calendar = tmp_path / "trade_calendar.json"
    calendar.write_text(
        json.dumps(["20260805", "20260806", "20260807"]), encoding="utf-8"
    )
    (tmp_path / "20260806.jsonl").touch()

    with caplog.at_level(_logging.WARNING, logger="src.screening.offensive.setup_output_log"):
        gaps = warn_missing_signal_log_sessions(
            before="20260807", calendar_path=calendar, log_dir=tmp_path
        )

    assert gaps == ["20260805"]
    assert any("信号覆盖断层" in r.message for r in caplog.records)


def test_warn_missing_signal_log_sessions_advisory_on_bad_calendar(tmp_path):
    from src.screening.offensive.setup_output_log import (
        warn_missing_signal_log_sessions,
    )

    # 日历缺失/损坏 → 静默返回 [], 绝不抛 (advisory 契约)
    assert (
        warn_missing_signal_log_sessions(
            before="20260807", calendar_path=tmp_path / "missing.json", log_dir=tmp_path
        )
        == []
    )
    bad = tmp_path / "bad.json"
    bad.write_text("not-json{", encoding="utf-8")
    assert (
        warn_missing_signal_log_sessions(before="20260807", calendar_path=bad, log_dir=tmp_path)
        == []
    )
