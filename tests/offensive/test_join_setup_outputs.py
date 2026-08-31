"""Tests for the setup-output ↔ forward-return join."""

from __future__ import annotations

import pandas as pd

from scripts.join_setup_outputs_with_returns import compute_forward_returns, join_records


def _series() -> pd.DataFrame:
    # idx0 = signal day; entry at idx1 open, exit at idx N close.
    rows = []
    dates = ["20260101"] + [f"202601{d:02d}" for d in range(2, 13)]  # 12 sessions
    for i, d in enumerate(dates):
        close = 10.0 + i * 0.5  # rises 0.5/session
        prev_close = 10.0 + (i - 1) * 0.5 if i > 0 else close
        pct = (close / prev_close - 1) * 100 if prev_close else 0.0
        rows.append({"compact": d, "open": 10.0, "high": 12.0, "low": 8.0, "close": close, "pct_change": pct})
    return pd.DataFrame(rows)


def test_compute_forward_returns_entry_next_open_exit_close():
    df = _series()
    rets = compute_forward_returns(df, "20260101")
    # T+1: entry idx1 open=10, exit idx1 close=10.5 → +5%
    assert round(rets[1], 2) == 5.0
    # T+10: exit idx10 close=15.0 → (15-10)/10 = +50%
    assert round(rets[10], 2) == 50.0


def test_compute_forward_returns_none_when_future_missing():
    df = _series().iloc[:3]  # only signal + 2 forward bars
    rets = compute_forward_returns(df, "20260101")
    assert rets[1] is not None
    assert rets[10] is None  # not enough forward bars yet


def test_compute_forward_returns_none_when_signal_absent():
    df = _series()
    rets = compute_forward_returns(df, "20259999")
    assert all(v is None for v in rets.values())


def test_join_records_attaches_returns_and_realized_flag():
    df = _series()
    records = [
        {"ticker": "000001", "signal_date": "20260101", "plan_eligible": True},
        {"ticker": "999999", "signal_date": "20260101", "plan_eligible": False},
    ]
    joined = join_records(records, {"000001": df})
    a = next(j for j in joined if j["ticker"] == "000001")
    assert a["realized"] is True
    assert round(a["return_t1"], 2) == 5.0
    b = next(j for j in joined if j["ticker"] == "999999")
    assert b["realized"] is False  # no price series for this ticker
    assert b["return_t10"] is None


# ---------------------------------------------------------------------------
# R80 Op1: 计划层容量拦截标注 (capacity_blocked) — R79 Op3 工件的消费端
# ---------------------------------------------------------------------------

from pathlib import Path  # noqa: E402

from scripts.join_setup_outputs_with_returns import (  # noqa: E402
    load_capacity_index,
    load_logged_records,
)


def _records() -> list[dict]:
    return [
        {"ticker": "000001", "signal_date": "20260101", "plan_eligible": True},
        {"ticker": "000002", "signal_date": "20260101", "plan_eligible": True},
    ]


def test_join_records_annotates_capacity_blocks():
    df = _series()
    index = {"20260101": {"000001": "portfolio_cap"}}
    joined = join_records(_records(), {"000001": df, "000002": df}, index)
    a = next(j for j in joined if j["ticker"] == "000001")
    assert a["capacity_blocked"] is True
    assert a["capacity_block_reason"] == "portfolio_cap"
    b = next(j for j in joined if j["ticker"] == "000002")
    assert b["capacity_blocked"] is False
    assert b["capacity_block_reason"] == ""


def test_join_records_without_index_matches_legacy_behavior():
    """capacity_index 缺省 = 旧行为逐位兼容 (False/空串), gross/net 列不变。"""
    df = _series()
    with_index = join_records(_records(), {"000001": df, "000002": df},
                              {"20260101": {"000001": "portfolio_cap"}})
    without = join_records(_records(), {"000001": df, "000002": df})
    assert [j["capacity_blocked"] for j in without] == [False, False]
    for a, b in zip(with_index, without):
        assert a["return_t10"] == b["return_t10"]
        assert a["return_t10_net"] == b["return_t10_net"]


def test_load_logged_records_excludes_capacity_sibling_files(tmp_path: Path):
    """``YYYYMMDD.capacity.jsonl`` 兄弟工件是计划层拦截证据, 混入 join 会以
    缺字段行污染 panel — glob 必须排除 (R79 Op3 工件出现当日即触发)。"""
    log_dir = tmp_path / "setup_output_log"
    log_dir.mkdir()
    (log_dir / "20260101.jsonl").write_text(
        '{"ticker": "000001", "signal_date": "20260101", "plan_eligible": true}\n',
        encoding="utf-8",
    )
    (log_dir / "20260101.capacity.jsonl").write_text(
        '{"schema_version": 1, "signal_date": "20260101", "ticker": "000002", '
        '"reason": "portfolio_cap"}\n',
        encoding="utf-8",
    )
    records = load_logged_records(log_dir)
    assert [r["ticker"] for r in records] == ["000001"]


def test_load_capacity_index_missing_artifact_all_clear(tmp_path: Path):
    records = _records()
    index = load_capacity_index({r["signal_date"] for r in records}, log_dir=tmp_path)
    assert index == {"20260101": {}}
    joined = join_records(records, {}, index)
    assert all(j["capacity_blocked"] is False for j in joined)


def test_load_capacity_index_reads_and_normalizes(tmp_path: Path):
    """合法行读入 + ticker 归一化 split(".")[0] + 无 ticker 行跳过。"""
    log_dir = tmp_path / "setup_output_log"
    log_dir.mkdir()
    (log_dir / "20260101.capacity.jsonl").write_text(
        '{"signal_date": "20260101", "ticker": "000001.SZ", "reason": "portfolio_cap"}\n'
        '{"signal_date": "20260101", "ticker": "", "reason": "portfolio_cap"}\n'
        "not-json-at-all\n",
        encoding="utf-8",
    )
    index = load_capacity_index(["20260101"], log_dir=log_dir)
    assert index["20260101"] == {"000001": "portfolio_cap"}


def test_load_capacity_index_malformed_signal_date_degrades_to_empty(tmp_path: Path):
    """畸形 signal_date 不阻塞 join — advisory 语义 (无工件降级为 False)。"""
    index = load_capacity_index(["not-a-date"], log_dir=tmp_path)
    assert index == {"not-a-date": {}}


# ---------------------------------------------------------------------------
# R81 Op1: 容量拦集合差重建 — live 工件缺席日期, eligible − ledger 计划。
# 0814 纪元以来最大容量自然实验 (0817/0821/0826/0827 共 25 只未获计划) 发生在
# *.capacity.jsonl 存在之前, 永远以 capacity_blocked=False 污染 review 通过组;
# 集合差对『未获计划』是精确事实, 台账 daily_valuations.drawdown 机械排除
# drawdown 熔断通道。
# ---------------------------------------------------------------------------

import sqlite3  # noqa: E402

from scripts.join_setup_outputs_with_returns import (  # noqa: E402
    reconstruct_capacity_index,
)


def _eligible(date: str, tickers: list[str]) -> list[dict]:
    return [
        {"ticker": t, "signal_date": date, "plan_eligible": True} for t in tickers
    ]


def _ledger(tmp_path: Path, trades=(), valuations=()) -> Path:
    """最小台账夹具: reconstruction 只读 trades(ticker, signal_date) 与
    daily_valuations(trade_date, drawdown)。"""
    path = tmp_path / "ledger.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE trades (ticker TEXT, signal_date TEXT)")
    conn.executemany("INSERT INTO trades VALUES (?, ?)", list(trades))
    conn.execute("CREATE TABLE daily_valuations (trade_date TEXT, drawdown REAL)")
    conn.executemany("INSERT INTO daily_valuations VALUES (?, ?)", list(valuations))
    conn.commit()
    conn.close()
    return path


def test_reconstruct_capacity_index_set_difference(tmp_path: Path):
    """0817 形态: 12 eligible − 6 计划 = 6 只未获计划 → capacity 标注。"""
    records = _eligible("20260817", [f"0000{i:02d}" for i in range(1, 13)])
    planned = [(f"0000{i:02d}", "2026-08-17") for i in range(1, 7)]
    ledger = _ledger(
        tmp_path,
        trades=planned,
        valuations=[("2026-08-17", -0.04)],
    )
    index, unclassified, meta = reconstruct_capacity_index(records, ledger_path=ledger)
    assert meta["ledger_available"] is True
    assert set(index["20260817"]) == {f"0000{i:02d}" for i in range(7, 13)}
    assert all(r == "reconstructed_not_planned" for r in index["20260817"].values())
    assert unclassified == {}
    # 已获计划的 6 只不标注
    assert "000001" not in index["20260817"]


def test_reconstruct_requires_plan_eligible_rows(tmp_path: Path):
    """plan_eligible=False 的行不是 eligible — gate 拦截已有归属, 不进集合差。"""
    records = [
        {"ticker": "000001", "signal_date": "20260817", "plan_eligible": False},
        {"ticker": "000002", "signal_date": "20260817", "plan_eligible": True},
    ]
    ledger = _ledger(tmp_path, valuations=[("2026-08-17", -0.04)])
    index, _, _ = reconstruct_capacity_index(records, ledger_path=ledger)
    assert index["20260817"] == {"000002": "reconstructed_not_planned"}


def test_reconstruct_epoch_guard(tmp_path: Path):
    """signal_date < 2026-08-14 (台账新档纪元) 的行永不重建 — 前-纪元计划
    事实在归档台账, 跨纪元集合差会假阳性。"""
    records = _eligible("20260714", ["000001", "000002"])
    ledger = _ledger(tmp_path, valuations=[("2026-07-14", 0.0)])
    index, _, meta = reconstruct_capacity_index(records, ledger_path=ledger)
    assert index == {}
    assert "20260714" not in str(meta.get("dates_considered", []))


def test_reconstruct_live_artifact_precedence(tmp_path: Path):
    """live 工件存在的日期不做重建 — log_capacity_skips 每次成功运行都写文件
    (空拦截也写), 文件存在 = 当日 live 正证据, 集合差只填 live 静默日。"""
    log_dir = tmp_path / "setup_output_log"
    log_dir.mkdir()
    records = _eligible("20260817", ["000001", "000002"])
    (log_dir / "20260817.capacity.jsonl").write_text(
        '{"signal_date": "20260817", "ticker": "000009", "reason": "portfolio_cap"}\n',
        encoding="utf-8",
    )
    ledger = _ledger(tmp_path, valuations=[("2026-08-17", -0.04)])
    index, _, _ = reconstruct_capacity_index(
        records, ledger_path=ledger, log_dir=log_dir
    )
    assert index == {}


def test_reconstruct_drawdown_guard(tmp_path: Path):
    """drawdown ≤ -15% (回撤减半/熔断窗口) 或估值行缺失 → 不冒充容量拦,
    落 not_planned_unclassified 诚实披露 (当前台账实证为 0)。"""
    records = _eligible(
        "20260817", ["000001", "000002", "000003", "000004"]
    )
    ledger = _ledger(
        tmp_path,
        valuations=[
            ("2026-08-17", -0.20),  # 回撤熔断窗口
            ("2026-08-21", -0.16),  # 减半窗口 (另一日期)
        ],
    )
    r2 = _eligible("20260821", ["000010"])
    index, unclassified, _ = reconstruct_capacity_index(
        records + r2, ledger_path=ledger
    )
    # 000001: drawdown=-0.20 ≤ -0.15 → unclassified
    assert "000001" not in index.get("20260817", {})
    assert set(unclassified["20260817"]) == {"000001", "000002", "000003", "000004"}
    assert "drawdown" in unclassified["20260817"]["000001"]
    # 000003 无估值行 (20260825 缺失) → valuation_missing 分支
    r3 = _eligible("20260825", ["000003", "000004"])
    index3, unclass3, _ = reconstruct_capacity_index(
        records + r2 + r3, ledger_path=ledger
    )
    assert "000003" not in index3.get("20260825", {})
    assert "valuation_missing" in unclass3["20260825"]["000003"]
    # 000004 同日也 unclassified (同日期一个估值事实)
    assert set(unclass3.get("20260825", {})) == {"000003", "000004"}


def test_reconstruct_ledger_missing_advisory(tmp_path: Path):
    """台账缺失 → advisory 降级零标注不崩 (与 live 工件缺失同语义)。"""
    records = _eligible("20260817", ["000001"])
    index, unclassified, meta = reconstruct_capacity_index(
        records, ledger_path=tmp_path / "missing.sqlite3"
    )
    assert index == {}
    assert unclassified == {}
    assert meta["ledger_available"] is False


def test_reconstruct_coverage_gap_disclosed(tmp_path: Path):
    """计划存在但检测日志无 eligible 行 (0814 覆盖缺口形态) → meta 披露, 不标注。"""
    records = _eligible("20260817", ["000001"])
    ledger = _ledger(
        tmp_path,
        trades=[("000001", "2026-08-17"), ("009999", "2026-08-17")],
        valuations=[("2026-08-17", -0.04)],
    )
    index, _, meta = reconstruct_capacity_index(records, ledger_path=ledger)
    assert index == {}  # 000001 有计划 → 不在集合差
    assert ("20260817", "009999") in set(meta["coverage_gaps"])


def test_join_records_reconstructed_annotation():
    """reconstructed_index 进 join → capacity_blocked=True + source=reconstructed;
    live 优先于重建; 缺席行 source 空串 (新增列, 旧行为逐位兼容)。"""
    df = _series()
    records = _eligible("20260101", ["000001", "000002", "000003"])
    joined = join_records(
        records,
        {"000001": df, "000002": df, "000003": df},
        {"20260101": {"000001": "portfolio_cap"}},
        reconstructed_index={"20260101": {"000002": "reconstructed_not_planned"}},
    )
    by = {j["ticker"]: j for j in joined}
    assert by["000001"]["capacity_block_source"] == "live"
    assert by["000001"]["capacity_blocked"] is True
    assert by["000002"]["capacity_block_source"] == "reconstructed"
    assert by["000002"]["capacity_blocked"] is True
    assert by["000002"]["capacity_block_reason"] == "reconstructed_not_planned"
    assert by["000003"]["capacity_block_source"] == ""
    assert by["000003"]["capacity_blocked"] is False
    assert by["000003"]["not_planned_unclassified"] is False


def test_join_records_unclassified_flag():
    df = _series()
    records = _eligible("20260101", ["000001"])
    joined = join_records(
        records, {"000001": df}, unclassified_index={"20260101": {"000001": "drawdown_window"}}
    )
    row = joined[0]
    assert row["capacity_blocked"] is False
    assert row["not_planned_unclassified"] is True


def test_load_logged_records_excludes_scan_run_sibling_files(tmp_path: Path):
    """``YYYYMMDD.scan_runs.jsonl`` 逐刷新诊断快照 (R82) 不进检测日志 join —
    与 .capacity.jsonl 同族排除 (R80 Op1 污染家族回归)。"""
    from scripts.join_setup_outputs_with_returns import load_logged_records

    log_dir = tmp_path / "setup_output_log"
    log_dir.mkdir()
    (log_dir / "20260101.jsonl").write_text(
        '{"ticker": "000001", "signal_date": "20260101", "plan_eligible": true}\n',
        encoding="utf-8",
    )
    (log_dir / "20260101.scan_runs.jsonl").write_text(
        '{"record_kind": "scan_run", "candidates": []}\n',
        encoding="utf-8",
    )
    records = load_logged_records(log_dir)
    assert [r["ticker"] for r in records] == ["000001"]
