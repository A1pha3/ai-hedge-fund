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
