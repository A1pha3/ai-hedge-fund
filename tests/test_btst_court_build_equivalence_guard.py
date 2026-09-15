"""btst_court_build 行为等价实证重建门回归 (R229 Op1).

背景 (2026-09-16 夜刷阻断): 防覆盖护栏按文件级 sha256 指纹拒绝重建
(acaa7367 → 974babe4), 唯一漂移源是 R219 Op1 (402b02e6) 的行为逐字节
等价重构 — 文件级指纹无法区分「重构」与「行为变化」, 护栏对非违规误报
(纯注释变更同类早已记录于 test_btst_court_build_rebuild_flag.py 文档串),
build rc=1 每晚级联冻结 reconcile+diagnostics 证据新鲜度链。

本回归网锁三件事:
1. 等价实证 (equivalence_verdict): 候选表与既有表在重叠窗口 canonical
   行级比对 — key 排序/dtype 按先表对齐/None→NaN 归一; 逐值相等才放行;
   重复键/缺表/空重叠/schema 漂移/dtype 对齐失败/行值不等全部类型化拒绝。
2. 三态门 (evaluate_formula_change_gate): 同指纹或无 prior 恒放行无披露
   (现行语义逐字节); force 旁路比对走既有强制披露; mismatch+no-force 才
   走等价实证, 放行时 manifest 带等价披露字段。
3. 拒绝消息与表路径优先级: 拒绝消息含类型化原因 + 双指引; parquet 优先。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from btst_court_build import (  # noqa: E402
    EVENT_KEY_COLUMNS,
    _existing_table_path,
    _formula_change_rejection_message,
    equivalence_verdict,
    evaluate_formula_change_gate,
)

COLS = [
    "ts_code",
    "signal_date",
    "regime",
    "trigger_strength",
    "fillable",
    "industry_name",
    "gross_ret_t10",
]

WINDOW = {"start": 20250701, "end": 20250703}


def _row(ts, date, *, strength=0.6, fillable=True, industry="电力设备", ret=0.03):
    return {
        "ts_code": ts,
        "signal_date": date,
        "regime": "normal",
        "trigger_strength": strength,
        "fillable": fillable,
        "industry_name": industry,
        "gross_ret_t10": ret,
    }


def _prior_rows():
    return [
        _row("000001.SZ", 20250701),
        _row("000002.SZ", 20250702, strength=0.55, ret=-0.01),
        _row("000003.SZ", 20250703, industry=None),
    ]


def _write_prior(tmp_path, rows):
    frame = pd.DataFrame(rows)[COLS]
    path = tmp_path / "event_table_v1.csv.gz"
    frame.to_csv(path, index=False, compression="gzip")
    return path


def _candidate(rows):
    return pd.DataFrame(rows)[COLS]


# ---------- A1: 等价实证放行面 ----------


def test_equivalent_overlap_with_tail_extension_allows(tmp_path):
    prior_path = _write_prior(tmp_path, _prior_rows())
    candidate = _candidate(_prior_rows() + [_row("000004.SZ", 20250704)])
    verdict = equivalence_verdict(prior_path, WINDOW, candidate)
    assert verdict.ok is True
    assert verdict.reason is None
    assert verdict.overlap_events == 3
    assert verdict.overlap_window == {"start": 20250701, "end": 20250703}


def test_row_order_perturbation_zero_effect(tmp_path):
    prior_path = _write_prior(tmp_path, _prior_rows())
    rows = _prior_rows() + [_row("000004.SZ", 20250704)]
    shuffled = _candidate(list(reversed(rows)))
    first = equivalence_verdict(prior_path, WINDOW, shuffled)
    second = equivalence_verdict(prior_path, WINDOW, shuffled)
    assert first.ok and second.ok
    assert first.overlap_events == second.overlap_events


def test_dtype_alignment_int_vs_float_allows(tmp_path):
    rows = [
        {**_row("000001.SZ", 20250701), "exit_session_t10": 10.0},
        {**_row("000002.SZ", 20250702, strength=0.55), "exit_session_t10": 5.0},
    ]
    prior_path = _write_prior(tmp_path, rows)
    cand_rows = [
        {**rows[0], "exit_session_t10": 10},
        {**rows[1], "exit_session_t10": 5},
    ]
    verdict = equivalence_verdict(prior_path, WINDOW, _candidate(cand_rows))
    assert verdict.ok is True, verdict.reason


def test_none_vs_nan_object_column_allows(tmp_path):
    rows = _prior_rows()
    prior_path = _write_prior(tmp_path, rows)
    candidate = _candidate(rows)
    # 候选侧内存帧 industry_name=None; 先表经 csv 往返已是 NaN — 归一后等价
    verdict = equivalence_verdict(prior_path, WINDOW, candidate)
    assert verdict.ok is True, verdict.reason


# ---------- A2: 类型化拒绝面 ----------


def test_overlap_value_mutation_rejects(tmp_path):
    prior_path = _write_prior(tmp_path, _prior_rows())
    mutated = [dict(_prior_rows()[0], trigger_strength=0.9)] + _prior_rows()[1:]
    verdict = equivalence_verdict(prior_path, WINDOW, _candidate(mutated))
    assert verdict.ok is False
    assert verdict.reason == "overlap_mismatch"


def test_extra_overlap_row_in_candidate_rejects(tmp_path):
    prior_path = _write_prior(tmp_path, _prior_rows())
    rows = _prior_rows()
    rows.append(_row("000009.SZ", 20250702))
    verdict = equivalence_verdict(prior_path, WINDOW, _candidate(rows))
    assert verdict.ok is False
    assert verdict.reason == "overlap_mismatch"


def test_missing_overlap_row_in_candidate_rejects(tmp_path):
    prior_path = _write_prior(tmp_path, _prior_rows())
    verdict = equivalence_verdict(prior_path, WINDOW, _candidate(_prior_rows()[1:]))
    assert verdict.ok is False
    assert verdict.reason == "overlap_mismatch"


def test_duplicate_keys_rejected(tmp_path):
    prior_path = _write_prior(tmp_path, _prior_rows())
    rows = _prior_rows() + [_row("000001.SZ", 20250701, strength=0.7)]
    verdict = equivalence_verdict(prior_path, WINDOW, _candidate(rows))
    assert verdict.ok is False
    assert verdict.reason == "duplicate_event_keys"

    dup_dir = tmp_path / "dup"
    dup_dir.mkdir()
    dup_prior = _write_prior(
        dup_dir,
        _prior_rows() + [_row("000002.SZ", 20250702, strength=0.5)],
    )
    verdict = equivalence_verdict(dup_prior, WINDOW, _candidate(_prior_rows()))
    assert verdict.ok is False
    assert verdict.reason == "duplicate_event_keys"


def test_prior_table_missing_rejects(tmp_path):
    candidate = _candidate(_prior_rows())
    verdict = equivalence_verdict(None, WINDOW, candidate)
    assert verdict.ok is False
    assert verdict.reason == "prior_table_missing"
    verdict = equivalence_verdict(tmp_path / "absent.csv.gz", WINDOW, candidate)
    assert verdict.ok is False
    assert verdict.reason == "prior_table_missing"


def test_empty_overlap_rejects(tmp_path):
    outside = [_row("000005.SZ", 20250705), _row("000006.SZ", 20250706)]
    prior_path = _write_prior(tmp_path, outside)
    verdict = equivalence_verdict(prior_path, WINDOW, _candidate(outside))
    assert verdict.ok is False
    assert verdict.reason == "empty_overlap"


def test_schema_mismatch_rejects(tmp_path):
    prior_path = _write_prior(tmp_path, _prior_rows())
    rows = _prior_rows()
    extra_frame = pd.DataFrame([{**r, "new_col": 1} for r in rows])
    verdict = equivalence_verdict(prior_path, WINDOW, extra_frame)
    assert verdict.ok is False
    assert verdict.reason == "schema_mismatch"


def test_dtype_align_failure_typed_reject(tmp_path):
    rows = _prior_rows()
    prior_path = _write_prior(tmp_path, rows)
    broken = [{**r, "trigger_strength": "not-a-number"} for r in rows]
    verdict = equivalence_verdict(prior_path, WINDOW, _candidate(broken))
    assert verdict.ok is False
    assert verdict.reason == "dtype_align_failed"


# ---------- A3: 三态门语义 ----------


def _manifest(fp, window=None):
    return {
        "formula_fingerprint": {"btst_breakout_sha256": fp},
        "window": window or WINDOW,
    }


def test_gate_same_fingerprint_allows_without_disclosure(tmp_path):
    prior_path = _write_prior(tmp_path, _prior_rows())
    gate = evaluate_formula_change_gate(
        _manifest("aa"), prior_path, "aa", _candidate(_prior_rows()), force=False
    )
    assert gate.allowed is True
    assert gate.manifest_fields == {}
    assert gate.rejection_reason is None


def test_gate_missing_prior_allows_without_disclosure(tmp_path):
    gate = evaluate_formula_change_gate(
        None, None, "bb", _candidate(_prior_rows()), force=False
    )
    assert gate.allowed is True
    assert gate.manifest_fields == {}


def test_gate_force_bypasses_comparison_with_forced_disclosure(tmp_path):
    gate = evaluate_formula_change_gate(
        _manifest("aa"), None, "bb", _candidate(_prior_rows()), force=True
    )
    assert gate.allowed is True
    assert gate.manifest_fields == {
        "formula_change_forced": True,
        "prior_formula_fingerprint": "aa",
    }


def test_gate_equivalence_ok_emits_proof_fields(tmp_path):
    prior_path = _write_prior(tmp_path, _prior_rows())
    candidate = _candidate(_prior_rows() + [_row("000004.SZ", 20250704)])
    gate = evaluate_formula_change_gate(
        _manifest("aa"), prior_path, "bb", candidate, force=False
    )
    assert gate.allowed is True
    assert gate.rejection_reason is None
    fields = gate.manifest_fields
    assert fields["formula_change_equivalence_verified"] is True
    assert fields["prior_formula_fingerprint"] == "aa"
    proof = fields["equivalence_proof"]
    assert proof["overlap_events"] == 3
    assert proof["overlap_window"] == {"start": 20250701, "end": 20250703}
    assert proof["key_columns"] == list(EVENT_KEY_COLUMNS)
    assert "formula_change_forced" not in fields


def test_gate_equivalence_failure_rejects(tmp_path):
    prior_path = _write_prior(tmp_path, _prior_rows())
    mutated = [dict(_prior_rows()[0], gross_ret_t10=0.99)] + _prior_rows()[1:]
    gate = evaluate_formula_change_gate(
        _manifest("aa"), prior_path, "bb", _candidate(mutated), force=False
    )
    assert gate.allowed is False
    assert gate.rejection_reason == "overlap_mismatch"
    assert gate.manifest_fields == {}


# ---------- 拒绝消息与表路径 ----------


def test_rejection_message_carries_reason_and_both_guidances():
    message = _formula_change_rejection_message("overlap_mismatch")
    assert "overlap_mismatch" in message
    assert "新版本文件" in message
    assert "--rebuild-force" in message


def test_existing_table_path_prefers_parquet(tmp_path):
    assert _existing_table_path(tmp_path) is None
    csv_path = tmp_path / "event_table_v1.csv.gz"
    csv_path.touch()
    assert _existing_table_path(tmp_path) == csv_path
    parquet_path = tmp_path / "event_table_v1.parquet"
    parquet_path.touch()
    assert _existing_table_path(tmp_path) == parquet_path
