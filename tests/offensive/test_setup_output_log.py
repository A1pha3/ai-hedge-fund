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


# ===========================================================================
# 台账↔日志对账写守卫 (2026-08-23 对抗审查 R1-R3 收敛, 真实事件回归)
#
# 事件回放 (2026-08-20 晚): 18:09 运行检出 300009 并创建台账计划; 22:47
# 重跑时 300009 因当晚数据状态未被检出, 幂等覆盖写把它的 plan_eligible 行
# 从当日日志中抹掉 — panel 样本外证据被"最后写者"静默污染, 且该票已有
# 真实仓位. 守卫语义: 日志真相只累积, 台账计划-backed 行不可消失.
# ===========================================================================


def test_log_guard_preserves_plan_backed_row_on_rerun(tmp_path):
    """8-20 事件主回归: 后续运行的覆盖写不得抹掉台账计划-backed 行."""
    # 18:09 运行: 300009 检出且可计划
    log_setup_outputs(
        date(2026, 8, 20),
        [_action("300009", metadata={"pct_change": 19.98})],
        [],
        regime="normal",
        out_dir=tmp_path,
    )

    # 22:47 重跑: 300009 未检出 (只剩另两只被拦票), 但台账已有其计划
    log_setup_outputs(
        date(2026, 8, 20),
        [],
        [
            _action("300363", trigger_strength=0.43, entry_price=90.0),
            _action("002172", trigger_strength=0.27, entry_price=4.4),
        ],
        regime="normal",
        out_dir=tmp_path,
        plan_backed_tickers={"300009"},
    )

    records = _read_log(tmp_path, "20260820")
    by_ticker = {r["ticker"]: r for r in records}
    # 守卫: 300009 的 plan_eligible 行必须存活, 新运行的行照常写入
    assert by_ticker["300009"]["plan_eligible"] is True
    assert by_ticker["300363"]["plan_eligible"] is False
    assert by_ticker["002172"]["plan_eligible"] is False


def test_log_guard_preserves_blocked_row_upgraded_to_eligible(tmp_path):
    """合并规则: 同票早运行被拦、晚运行可计划 → eligible 优先存活."""
    log_setup_outputs(
        date(2026, 8, 20),
        [],
        [_action("300363", trigger_strength=0.43)],
        regime="normal",
        out_dir=tmp_path,
    )
    log_setup_outputs(
        date(2026, 8, 20),
        [_action("300363", metadata={"pct_change": 20.0})],
        [],
        regime="normal",
        out_dir=tmp_path,
    )
    (rec,) = _read_log(tmp_path, "20260820")
    assert rec["ticker"] == "300363" and rec["plan_eligible"] is True


def test_log_merge_latest_run_wins_on_equal_eligibility(tmp_path):
    """合并规则: 同资格 (均不可计划) 时晚运行覆盖 (最新数据), 输出按票排序."""
    log_setup_outputs(
        date(2026, 8, 20),
        [],
        [_action("000001", trigger_strength=0.30), _action("600000", trigger_strength=0.31)],
        regime="normal",
        out_dir=tmp_path,
    )
    log_setup_outputs(
        date(2026, 8, 20),
        [],
        [_action("000001", trigger_strength=0.35)],
        regime="normal",
        out_dir=tmp_path,
    )
    records = _read_log(tmp_path, "20260820")
    assert [r["ticker"] for r in records] == ["000001", "600000"]
    assert next(r for r in records if r["ticker"] == "000001")["trigger_strength"] == 0.35


def test_log_guard_warns_when_plan_backed_row_unrecoverable(tmp_path, caplog):
    """守卫告警: 计划-backed 票在既有文件与新扫描里都不存在 (如首跑日志写失败)."""
    import logging as _logging

    with caplog.at_level(_logging.WARNING, logger="src.screening.offensive.setup_output_log"):
        log_setup_outputs(
            date(2026, 8, 20),
            [],
            [_action("300363", trigger_strength=0.43)],
            regime="normal",
            out_dir=tmp_path,
            plan_backed_tickers={"300009"},
        )

    # 覆盖语义仍写盘 (当日覆盖哨点依赖文件存在), 但守卫必须告警
    assert _read_log(tmp_path, "20260820")
    assert any("300009" in r.message and ("台账" in r.message or "对账" in r.message) for r in caplog.records)


def test_log_directory_chain_rejects_symlink(tmp_path):
    """目录加固: 日志目录链上的 symlink 组件 fail-closed (写入前拒绝)."""
    import os

    from src.screening.offensive.setup_output_log import SetupOutputLogError

    real = tmp_path / "real_logs"
    real.mkdir()
    linked = tmp_path / "linked_logs"
    os.symlink(real, linked)

    try:
        log_setup_outputs(
            date(2026, 8, 20), [_action("300009")], [], regime="normal", out_dir=linked
        )
    except SetupOutputLogError:
        return
    raise AssertionError("symlinked log dir must be rejected before write")


def _read_log(out_dir, compact: str) -> list[dict]:
    path = out_dir / f"{compact}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---- R79 Op3: 容量拦截持久证据 (计划层『为什么没变成交易』的历史可重建性) ----


class _Skip:
    """duck-type CapacitySkip (ticker/reason/industry/detail)。"""

    def __init__(self, ticker: str, reason: str, industry: str, detail: str):
        self.ticker = ticker
        self.reason = reason
        self.industry = industry
        self.detail = detail


def test_log_capacity_skips_writes_structured_rows(tmp_path):
    from src.screening.offensive.setup_output_log import (
        log_capacity_skips,
        load_capacity_skips,
    )

    skips = [
        _Skip("002396", "portfolio_cap", "电力", "组合敞口 59% + 本票 8% > 60% 上限"),
        _Skip("688790", "portfolio_cap", "半导体", "组合敞口 59% + 本票 5% > 60% 上限"),
    ]
    log_capacity_skips(date(2026, 8, 27), skips, out_dir=tmp_path)
    path = tmp_path / "20260827.capacity.jsonl"
    assert path.exists()
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    assert len(rows) == 2
    assert rows[0]["schema_version"] == 1
    assert rows[0]["signal_date"] == "20260827"
    assert {r["ticker"] for r in rows} == {"002396", "688790"}
    assert all(r["reason"] == "portfolio_cap" for r in rows)
    assert "detail" in rows[0] and "logged_at" in rows[0]
    # 只读回读
    loaded = load_capacity_skips(date(2026, 8, 27), out_dir=tmp_path)
    assert len(loaded) == 2


def test_log_capacity_skips_rerun_merge_same_key_overrides(tmp_path):
    """重跑合并: 同 (ticker, reason) 晚运行覆盖 detail, 异 reason 共存。"""
    from src.screening.offensive.setup_output_log import (
        log_capacity_skips,
        load_capacity_skips,
    )

    log_capacity_skips(
        date(2026, 8, 27), [_Skip("002396", "portfolio_cap", "电力", "d1")],
        out_dir=tmp_path,
    )
    log_capacity_skips(
        date(2026, 8, 27),
        [_Skip("002396", "portfolio_cap", "电力", "d2-later-run"),
         _Skip("600108", "industry_concentration", "电力", "行业已 2 仓")],
        out_dir=tmp_path,
    )
    loaded = load_capacity_skips(date(2026, 8, 27), out_dir=tmp_path)
    by_key = {(r["ticker"], r["reason"]): r for r in loaded}
    assert len(loaded) == 2  # 同键覆盖, 不重复
    assert by_key[("002396", "portfolio_cap")]["detail"] == "d2-later-run"
    assert ("600108", "industry_concentration") in by_key


def test_load_capacity_skips_missing_file_returns_empty(tmp_path):
    from src.screening.offensive.setup_output_log import load_capacity_skips

    assert load_capacity_skips(date(2026, 8, 28), out_dir=tmp_path) == []


def test_capacity_file_breaks_no_coverage_audit(tmp_path):
    """audit_signal_log_coverage 对 .capacity.jsonl 兄弟文件无假缺失/假会话。"""
    from src.screening.offensive.setup_output_log import (
        audit_signal_log_coverage,
        log_capacity_skips,
        log_setup_outputs,
    )

    calendar = tmp_path / "trade_calendar.json"
    calendar.write_text(json.dumps({"sessions": ["20260827"]}))
    log_setup_outputs(
        date(2026, 8, 27), [], [], regime="normal", out_dir=tmp_path
    )
    log_capacity_skips(
        date(2026, 8, 27), [_Skip("002396", "portfolio_cap", "电力", "d")],
        out_dir=tmp_path,
    )
    gaps = audit_signal_log_coverage(
        ["20260827"], before="20260828", log_dir=tmp_path
    )
    assert gaps == []  # 兄弟文件不产生假缺失


def test_capacity_skips_symlink_dir_rejected(tmp_path):
    """目录链守卫复用: symlink 目录 fail-closed (镜像主日志纪律)。"""
    import os
    from src.screening.offensive.setup_output_log import (
        SetupOutputLogError,
        log_capacity_skips,
    )

    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked_logs"
    os.symlink(real, linked)
    try:
        log_capacity_skips(
            date(2026, 8, 20), [_Skip("300009", "portfolio_cap", "x", "d")],
            out_dir=linked,
        )
    except SetupOutputLogError:
        return
    raise AssertionError("symlinked log dir must be rejected before write")


# ---------------------------------------------------------------------------
# R80 Op2: 扫描漏斗持久工件 (YYYYMMDD.funnel.json) — 零命中日自解释的地基
# ---------------------------------------------------------------------------

class _Funnel:
    """duck-type ScanFunnel (聚合标量)。"""

    def __init__(self, **kw):
        self.universe = kw.get("universe")
        self.verify_blocked = kw.get("verify_blocked", 0)
        self.excluded_permanent = kw.get("excluded_permanent", 0)
        self.data_rejected = kw.get("data_rejected", 0)
        self.scannable = kw.get("scannable", 0)
        self.prefilter_passed = kw.get("prefilter_passed", 0)
        self.hits = kw.get("hits", 0)
        self.detect_miss_stages = kw.get("detect_miss_stages")


def test_scan_funnel_roundtrip_and_idempotent_overwrite(tmp_path):
    from src.screening.offensive.setup_output_log import (
        load_scan_funnel,
        log_scan_funnel,
    )

    funnel = _Funnel(
        universe=1840, verify_blocked=65, excluded_permanent=7, data_rejected=3,
        scannable=85, prefilter_passed=85, hits=0,
        detect_miss_stages={"c2_flow_below_mean": 66, "c3_industry_weak": 16, "c1_limit_up_pct": 3},
    )
    target = log_scan_funnel(date(2026, 8, 28), funnel, out_dir=tmp_path)
    assert target.name == "20260828.funnel.json"
    row = load_scan_funnel(date(2026, 8, 28), out_dir=tmp_path)
    assert row["hits"] == 0 and row["prefilter_passed"] == 85
    assert row["detect_miss_stages"] == {
        "c2_flow_below_mean": 66, "c3_industry_weak": 16, "c1_limit_up_pct": 3,
    }
    # 重跑覆盖 = 幂等 (聚合标量, 晚运行即真相)
    log_scan_funnel(date(2026, 8, 28), funnel, out_dir=tmp_path)
    again = load_scan_funnel(date(2026, 8, 28), out_dir=tmp_path)
    assert again == row


def test_scan_funnel_zero_buckets_dropped_and_missing_artifact_none(tmp_path):
    from src.screening.offensive.setup_output_log import (
        load_scan_funnel,
        log_scan_funnel,
    )

    log_scan_funnel(
        date(2026, 8, 28),
        _Funnel(universe=10, scannable=5, prefilter_passed=2, hits=2, detect_miss_stages={"c1_limit_up_pct": 0}),
        out_dir=tmp_path,
    )
    row = load_scan_funnel(date(2026, 8, 28), out_dir=tmp_path)
    assert row["detect_miss_stages"] == {}  # 非零桶才落 — 0 值桶是噪声
    assert load_scan_funnel(date(2026, 9, 1), out_dir=tmp_path) is None  # 缺失 → None


def test_scan_funnel_corrupt_artifact_reads_as_none(tmp_path):
    from src.screening.offensive.setup_output_log import load_scan_funnel

    (tmp_path / "20260828.funnel.json").write_text("not-json{{", encoding="utf-8")
    assert load_scan_funnel(date(2026, 8, 28), out_dir=tmp_path) is None


def test_scan_funnel_symlink_dir_rejected(tmp_path):
    """目录链守卫复用: symlink 目录 fail-closed (与主日志/容量工件同纪律)。"""
    import os
    from src.screening.offensive.setup_output_log import (
        SetupOutputLogError,
        log_scan_funnel,
    )

    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked_logs"
    os.symlink(real, linked)
    try:
        log_scan_funnel(date(2026, 8, 28), _Funnel(scannable=1), out_dir=linked)
    except SetupOutputLogError:
        return
    raise AssertionError("symlinked log dir must be rejected before write")


# ---- R82 Op1: 逐刷新扫描快照 (跨刷新翻转可测量 + 刷新分歧可重建) ----


def test_log_scan_run_appends_per_refresh(tmp_path):
    """append-only: 重跑追加新行, 既有字节是结果文件的严格前缀 (合并语义的对面)."""
    from src.screening.offensive.setup_output_log import (
        load_scan_runs,
        log_scan_run,
    )

    day = date(2026, 8, 20)
    path = log_scan_run(
        day, [_action("300009", trigger_strength=0.595)], [], regime="normal", out_dir=tmp_path
    )
    first_bytes = path.read_bytes()
    path = log_scan_run(
        day,
        [],
        [
            _action(
                "300009",
                action="SKIP",
                kelly_pct=0.0,
                entry_price=0.0,
                trigger_strength=0.42,
                block_reason="strength_below_threshold",
            )
        ],
        regime="normal",
        out_dir=tmp_path,
    )
    later_bytes = path.read_bytes()
    assert later_bytes.startswith(first_bytes), "append-only: 既有行永不被改写"

    runs = load_scan_runs(day, out_dir=tmp_path)
    assert len(runs) == 2
    assert runs[0]["record_kind"] == "scan_run"
    assert runs[0]["candidates"][0]["plan_eligible"] is True
    assert runs[0]["candidates"][0]["trigger_strength"] == 0.595
    assert runs[1]["candidates"][0]["plan_eligible"] is False
    assert runs[1]["candidates"][0]["trigger_strength"] == 0.42
    assert runs[1]["candidates"][0]["block_reason"] == "strength_below_threshold"


def test_log_scan_run_records_funnel_and_snapshot(tmp_path):
    from src.screening.offensive.daily_action import ScanFunnel
    from src.screening.offensive.setup_output_log import log_scan_run

    funnel = ScanFunnel(
        scannable=85,
        prefilter_passed=85,
        hits=0,
        universe=1733,
        detect_miss_stages={"c2_flow_below_mean": 66, "c3_industry_weak": 16},
    )
    path = log_scan_run(
        date(2026, 8, 28),
        [],
        [],
        regime="normal",
        funnel=funnel,
        snapshot_id="snap-1",
        out_dir=tmp_path,
    )
    row = json.loads(path.read_text().splitlines()[0])
    assert row["funnel"]["hits"] == 0
    assert row["funnel"]["universe"] == 1733
    assert row["funnel"]["detect_miss_stages"] == {
        "c2_flow_below_mean": 66,
        "c3_industry_weak": 16,
    }
    assert row["snapshot_id"] == "snap-1"
    assert row["regime"] == "normal"
    assert row["signal_date"] == "20260828"


def test_load_scan_runs_missing_file_returns_empty(tmp_path):
    from src.screening.offensive.setup_output_log import load_scan_runs

    assert load_scan_runs(date(2026, 1, 1), out_dir=tmp_path) == []


def test_load_scan_runs_skips_corrupt_lines(tmp_path, caplog):
    """损坏行跳过告警 (advisory 消费面, 宁缺毋抛), 合法行照常回读."""
    import logging

    from src.screening.offensive.setup_output_log import (
        load_scan_runs,
        log_scan_run,
    )

    day = date(2026, 8, 20)
    log_scan_run(day, [_action("300009")], [], regime="normal", out_dir=tmp_path)
    path = tmp_path / "20260820.scan_runs.jsonl"
    path.write_text("{corrupt json\n" + path.read_text(), encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        runs = load_scan_runs(day, out_dir=tmp_path)
    assert len(runs) == 1
    assert any("scan_run" in r.message or "损坏" in r.message for r in caplog.records)


def test_log_scan_run_symlink_dir_rejected(tmp_path):
    """目录加固与主日志同源: 链上 symlink 组件 fail-closed (写入前拒绝)."""
    import os

    from src.screening.offensive.setup_output_log import (
        SetupOutputLogError,
        log_scan_run,
    )

    real = tmp_path / "real_logs"
    real.mkdir()
    linked = tmp_path / "linked_logs"
    os.symlink(real, linked)

    try:
        log_scan_run(date(2026, 8, 20), [], [], regime="normal", out_dir=linked)
    except SetupOutputLogError:
        return
    raise AssertionError("symlinked log dir must be rejected before write")


def test_refresh_flip_summary_detects_cross_refresh_flip():
    """300009 事件型翻转: run1 eligible 0.595 → run2 blocked 0.42, 可测量."""
    from src.screening.offensive.setup_output_log import refresh_flip_summary

    runs = [
        {
            "candidates": [
                {"ticker": "300009", "setup": "btst_breakout", "plan_eligible": True,
                 "trigger_strength": 0.595},
                {"ticker": "600497", "setup": "btst_breakout", "plan_eligible": True,
                 "trigger_strength": 0.71},
            ]
        },
        {
            "candidates": [
                {"ticker": "300009", "setup": "btst_breakout", "plan_eligible": False,
                 "trigger_strength": 0.42},
                {"ticker": "600497", "setup": "btst_breakout", "plan_eligible": True,
                 "trigger_strength": 0.69},
            ]
        },
    ]
    summary = refresh_flip_summary(runs)
    assert summary["runs"] == 2
    assert summary["candidates_seen"] == 2
    assert summary["flipped_candidates"] == 1
    entry = next(e for e in summary["per_candidate"] if e["ticker"] == "300009")
    assert entry["flipped"] is True
    assert entry["eligible_runs"] == 1
    assert entry["runs_seen"] == 2
    assert entry["strength_min"] == 0.42
    assert entry["strength_max"] == 0.595
    # 并集 admission − 末刷新支持 = 300009 (早刷新纳入、末刷新不再支持的噪声进入量)
    assert summary["union_minus_last_refresh"] == [{"ticker": "300009", "setup": "btst_breakout"}]


def test_refresh_flip_summary_single_run_has_no_flips():
    from src.screening.offensive.setup_output_log import refresh_flip_summary

    runs = [
        {"candidates": [
            {"ticker": "600497", "setup": "btst_breakout", "plan_eligible": True,
             "trigger_strength": 0.62},
        ]}
    ]
    summary = refresh_flip_summary(runs)
    assert summary["runs"] == 1
    assert summary["flipped_candidates"] == 0
    assert summary["union_minus_last_refresh"] == []


def test_refresh_flip_summary_empty_runs_zeroed():
    from src.screening.offensive.setup_output_log import refresh_flip_summary

    summary = refresh_flip_summary([])
    assert summary == {
        "runs": 0,
        "candidates_seen": 0,
        "flipped_candidates": 0,
        "union_minus_last_refresh": [],
        "per_candidate": [],
    }


# ---- R82 Op2: Op1 交付面对抗审查修复 (D1 部分写撕裂 / D2 SecureReadError 裸逃逸) ----


def test_log_scan_row_survives_partial_os_write(tmp_path, monkeypatch):
    """D1: 底层 os.write 部分写时行仍必须完整落盘 — 单次 os.write 的撕裂残行
    会连带损坏下一次 append (行拼接在残行上), 全写语义是 append-only 的前提。"""
    import os as _os

    from src.screening.offensive.setup_output_log import (
        load_scan_runs,
        log_scan_run,
    )

    real_write = _os.write
    state = {"calls": 0}

    def flaky_write(fd, data):
        state["calls"] += 1
        # 模拟内核部分写: 奇数次调用只写前一半, 由上层重试补齐剩余
        if len(data) > 1 and state["calls"] % 2 == 1:
            return real_write(fd, data[: len(data) // 2])
        return real_write(fd, data)

    monkeypatch.setattr(_os, "write", flaky_write)

    day = date(2026, 8, 20)
    log_scan_run(day, [_action("300009", trigger_strength=0.595)], [], regime="normal", out_dir=tmp_path)
    monkeypatch.undo()
    runs = load_scan_runs(day, out_dir=tmp_path)
    assert len(runs) == 1
    assert runs[0]["candidates"][0]["ticker"] == "300009"
    assert runs[0]["candidates"][0]["trigger_strength"] == 0.595


def test_load_scan_runs_secure_read_error_degrades_to_missing(tmp_path, monkeypatch, caplog):
    """D2: read_regular_bytes 的 SecureReadError (超界/symlink-TOCTOU) 必须类型化
    降级为按缺失处理 — advisory 消费面裸抛会让整个 --daily-action 尾部告警链断裂。"""
    import logging

    import src.screening.offensive.setup_output_log as sol

    day = date(2026, 8, 20)
    log_scan_run = sol.log_scan_run
    path = log_scan_run(day, [_action("300009")], [], regime="normal", out_dir=tmp_path)
    assert path.stat().st_size > 10

    monkeypatch.setattr(sol, "_MAX_LOG_FILE_BYTES", 10)
    with caplog.at_level(logging.WARNING):
        runs = sol.load_scan_runs(day, out_dir=tmp_path)
    assert runs == []
    assert caplog.records, "降级必须留告警, 不静默假装没有"


def test_log_scan_run_write_failure_terminates_torn_line(tmp_path, monkeypatch):
    """写中途异常 (半行后抛, 区别于可重试的部分写): 残行必须被换行终止, 使
    下一次 append 的记录仍可独立解析 — 失败的写不得降低后续记录的可解析性
    (残行+后续行拼接成一条非法物理行会连带损失两条记录)。

    注入层是 os.fdopen (返回半写后抛异常的代理 writer) — C 层 FileIO 直连
    syscall, Python 级 os.write 补丁拦截不到 fdopen 路径。"""
    import os as _os

    from src.screening.offensive.setup_output_log import (
        load_scan_runs,
        log_scan_run,
    )

    real_fdopen = _os.fdopen

    class _HalfThenRaise:
        def __init__(self, fh):
            self._fh = fh
            self._raised = False

        def write(self, data):
            if not self._raised:
                self._raised = True
                self._fh.write(data[: len(data) // 2])
                raise OSError(28, "simulated ENOSPC mid-write")
            return self._fh.write(data)

        def flush(self):
            return self._fh.flush()

        def fileno(self):
            return self._fh.fileno()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return self._fh.__exit__(*exc)

    def failing_fdopen(fd, mode):
        return _HalfThenRaise(real_fdopen(fd, mode))

    monkeypatch.setattr(_os, "fdopen", failing_fdopen)
    day = date(2026, 8, 20)
    try:
        log_scan_run(day, [_action("300009", trigger_strength=0.595)], [], regime="normal", out_dir=tmp_path)
    except OSError:
        pass
    else:
        raise AssertionError("注入的写异常应向上传播 (fail-open 由调用方 WARNING)")
    finally:
        monkeypatch.undo()

    raw = (tmp_path / "20260820.scan_runs.jsonl").read_bytes()
    assert raw.endswith(b"\n"), "残行必须被换行终止"

    log_scan_run(day, [_action("600497", trigger_strength=0.71)], [], regime="normal", out_dir=tmp_path)
    runs = load_scan_runs(day, out_dir=tmp_path)
    assert len(runs) == 1, "残行被 loader 跳过, 后续记录必须完整存活"
    assert runs[0]["candidates"][0]["ticker"] == "600497"


# ---------- R86: 写函数 out_dir 懒默认 (CLI fixture 重定向契约) ----------

def test_writer_out_dir_late_bound_redirect(monkeypatch, tmp_path):
    """R86: patch 模块 _DEFAULT_DIR 后, 四写函数不传 out_dir 全部落重定向目录。

    def 时烘焙默认下此 patch 无效 — CLI fixture 的『一切写入尊重重定向』
    契约 (test_cli_test_fixture_never_writes_workspace_reports) 自 R79-R82
    被四个无注入点写函数打破, sweep 实证。只读加载函数保持烘焙默认
    (无目录创建面)。
    """
    from datetime import date as _date
    from types import SimpleNamespace

    from src.screening.offensive import setup_output_log as sol

    sandbox = tmp_path / "redirected"
    monkeypatch.setattr(sol, "_DEFAULT_DIR", sandbox)
    day = _date(2026, 8, 31)

    paths = [
        sol.log_setup_outputs(day, (), (), regime="normal"),
        sol.log_capacity_skips(day, ()),
        sol.log_scan_funnel(day, SimpleNamespace()),
        sol.log_scan_run(day, (), (), regime="normal"),
    ]
    for path in paths:
        assert sandbox in path.parents, path
    assert not (tmp_path / "data").exists()  # 未触未重定向路径


def test_writer_explicit_out_dir_still_wins(monkeypatch, tmp_path):
    """显式 out_dir 优先于模块默认 — 既有调用面 (dispatcher 显式传/测试 tmp) 语义不变。"""
    from datetime import date as _date

    from src.screening.offensive import setup_output_log as sol

    monkeypatch.setattr(sol, "_DEFAULT_DIR", tmp_path / "module-default")
    explicit = tmp_path / "explicit"
    path = sol.log_scan_run(_date(2026, 8, 31), (), (), regime="normal", out_dir=explicit)
    assert explicit in path.parents
    assert not (tmp_path / "module-default").exists()
