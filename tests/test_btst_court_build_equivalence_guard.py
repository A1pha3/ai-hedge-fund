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

import btst_court_build as btst_court_build_module  # noqa: E402
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


# ---------- Op2 对抗收口补钉 (R229 探针运动 SURVIVOR 定谳) ----------


def _main_source() -> str:
    path = Path(btst_court_build_module.__file__)
    return path.read_text(encoding="utf-8")


def test_main_wiring_gate_call_and_rejection_pinned():
    """P15 盲区钉: main() 必须经三态门, 拒绝必须 SystemExit 带类型化原因消息.

    既有钉全部锚在纯函数面, main() 接线无任何测试执行 — 探针实证把 main 的
    gate 调用整体旁路 (退回旧单态语义) 时 21 钉全绿。AST 结构钉按仓库守卫
    家族先例锁定接线形状, 不执行 main。
    """
    import ast

    source = _main_source()
    tree = ast.parse(source)
    mains = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    ]
    assert len(mains) == 1
    fn = mains[0]
    gate_calls = [
        node
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "evaluate_formula_change_gate"
    ]
    assert gate_calls, "main 必须经 evaluate_formula_change_gate 三态门 (P15)"
    rejection_raises = [
        node
        for node in ast.walk(fn)
        if isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call)
        and getattr(node.exc.func, "id", "") == "SystemExit"
        and node.exc.args
        and isinstance(node.exc.args[0], ast.Call)
        and getattr(node.exc.args[0].func, "id", "")
        == "_formula_change_rejection_message"
    ]
    assert rejection_raises, "拒绝必须 SystemExit(_formula_change_rejection_message(reason))"


def test_main_manifest_must_merge_gate_disclosure_fields():
    """P16 盲区钉: manifest 构造必须并入 gate.manifest_fields (含 **gate 展开)."""
    import ast

    fn = [
        node
        for node in ast.walk(ast.parse(_main_source()))
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    ][0]
    merged = any(
        key is None
        and isinstance(value, ast.Attribute)
        and value.attr == "manifest_fields"
        for node in ast.walk(fn)
        if isinstance(node, ast.Dict)
        for key, value in zip(node.keys, node.values)
    )
    assert merged, "manifest 必须并入 gate.manifest_fields (P16)"


def test_main_rebuild_count_lineage_semantics_pinned():
    """P17 盲区钉: rebuild_count 沿袭递增语义锚定 (词法钉, 仓库 token 守卫先例)."""
    source = _main_source()
    assert 'prior_data.get("rebuild_count", 0)' in source
    assert "rebuild_count = int(" in source


def test_verdict_does_not_mutate_caller_inputs(tmp_path):
    """P18 盲区钉: equivalence_verdict 对调用方候选帧零突变 (纯函数契约)."""
    rows = _prior_rows() + [_row("000004.SZ", 20250704)]
    candidate = _candidate(rows)
    snapshot = candidate.copy(deep=True)
    prior_path = _write_prior(tmp_path, _prior_rows())
    verdict = equivalence_verdict(prior_path, WINDOW, candidate)
    assert verdict.ok is True
    pd.testing.assert_frame_equal(candidate, snapshot)


def test_prior_window_invalid_typed_reject(tmp_path):
    """P19 盲区钉: manifest window 形状非法 → prior_window_invalid 类型化拒绝,
    绝不泄漏裸 int() 异常。"""
    prior_path = _write_prior(tmp_path, _prior_rows())
    bad_windows = (
        {},
        {"start": "garbage", "end": 20250703},
        {"start": 20250701},
        {"start": None, "end": None},
    )
    for bad in bad_windows:
        verdict = equivalence_verdict(prior_path, bad, _candidate(_prior_rows()))
        assert verdict.ok is False, bad
        assert verdict.reason == "prior_window_invalid", bad


# ---------- A4: 多键指纹门 (R230 Op1 泛化面 — ob_court_build 双指纹复用) ----------
# dict 形态 new_fp + fingerprint_keys; 单键标量形态 (上方 A3) 行为逐字节不变。


def _multi_manifest(fps, window=None):
    return {"formula_fingerprint": dict(fps), "window": window or WINDOW}


OB_FP_KEYS = ("oversold_bounce_sha256", "price_returns_sha256")


def test_multi_key_same_fingerprints_allow_without_disclosure(tmp_path):
    prior_path = _write_prior(tmp_path, _prior_rows())
    fps = {"oversold_bounce_sha256": "aa", "price_returns_sha256": "cc"}
    gate = evaluate_formula_change_gate(
        _multi_manifest(fps),
        prior_path,
        dict(fps),
        _candidate(_prior_rows()),
        force=False,
        fingerprint_keys=OB_FP_KEYS,
    )
    assert gate.allowed is True
    assert gate.manifest_fields == {}
    assert gate.rejection_reason is None


def test_multi_key_missing_prior_allows_without_disclosure(tmp_path):
    fps = {"oversold_bounce_sha256": "aa", "price_returns_sha256": "cc"}
    gate = evaluate_formula_change_gate(
        None,
        None,
        dict(fps),
        _candidate(_prior_rows()),
        force=False,
        fingerprint_keys=OB_FP_KEYS,
    )
    assert gate.allowed is True
    assert gate.manifest_fields == {}


def test_multi_key_price_returns_only_drift_triggers_gate(tmp_path):
    # R230 Observe 实锤缺口的门面: price_returns_sha256 单独漂移必须触发门,
    # 不再静默放行 (旧 OB main() 只比对 oversold_bounce_sha256)。
    prior_path = _write_prior(tmp_path, _prior_rows())
    prior_fps = {"oversold_bounce_sha256": "aa", "price_returns_sha256": "cc"}
    new_fps = {"oversold_bounce_sha256": "aa", "price_returns_sha256": "dd"}
    gate = evaluate_formula_change_gate(
        _multi_manifest(prior_fps),
        prior_path,
        new_fps,
        _candidate(_prior_rows()),
        force=False,
        fingerprint_keys=OB_FP_KEYS,
    )
    assert gate.allowed is True
    assert gate.rejection_reason is None
    fields = gate.manifest_fields
    assert fields["formula_change_equivalence_verified"] is True
    assert fields["prior_formula_fingerprint"] == prior_fps
    assert fields["equivalence_proof"]["overlap_events"] == 3


def test_multi_key_oversold_only_drift_triggers_gate(tmp_path):
    prior_path = _write_prior(tmp_path, _prior_rows())
    prior_fps = {"oversold_bounce_sha256": "aa", "price_returns_sha256": "cc"}
    new_fps = {"oversold_bounce_sha256": "bb", "price_returns_sha256": "cc"}
    gate = evaluate_formula_change_gate(
        _multi_manifest(prior_fps),
        prior_path,
        new_fps,
        _candidate(_prior_rows()),
        force=False,
        fingerprint_keys=OB_FP_KEYS,
    )
    assert gate.allowed is True
    assert gate.rejection_reason is None
    assert gate.manifest_fields["formula_change_equivalence_verified"] is True


def test_multi_key_value_mutation_rejects_typed(tmp_path):
    prior_path = _write_prior(tmp_path, _prior_rows())
    prior_fps = {"oversold_bounce_sha256": "aa", "price_returns_sha256": "cc"}
    new_fps = {"oversold_bounce_sha256": "aa", "price_returns_sha256": "dd"}
    mutated = [dict(_prior_rows()[0], trigger_strength=0.9)] + _prior_rows()[1:]
    gate = evaluate_formula_change_gate(
        _multi_manifest(prior_fps),
        prior_path,
        new_fps,
        _candidate(mutated),
        force=False,
        fingerprint_keys=OB_FP_KEYS,
    )
    assert gate.allowed is False
    assert gate.rejection_reason == "overlap_mismatch"


def test_multi_key_force_discloses_prior_dict_and_drift_keys(tmp_path):
    prior_fps = {"oversold_bounce_sha256": "aa", "price_returns_sha256": "cc"}
    new_fps = {"oversold_bounce_sha256": "aa", "price_returns_sha256": "dd"}
    gate = evaluate_formula_change_gate(
        _multi_manifest(prior_fps),
        None,
        new_fps,
        _candidate(_prior_rows()),
        force=True,
        fingerprint_keys=OB_FP_KEYS,
    )
    assert gate.allowed is True
    assert gate.manifest_fields == {
        "formula_change_forced": True,
        "prior_formula_fingerprint": prior_fps,
        "formula_drift_keys": ["price_returns_sha256"],
    }


def test_multi_key_dual_drift_force_lists_both_keys(tmp_path):
    prior_fps = {"oversold_bounce_sha256": "aa", "price_returns_sha256": "cc"}
    new_fps = {"oversold_bounce_sha256": "bb", "price_returns_sha256": "dd"}
    gate = evaluate_formula_change_gate(
        _multi_manifest(prior_fps),
        None,
        new_fps,
        _candidate(_prior_rows()),
        force=True,
        fingerprint_keys=OB_FP_KEYS,
    )
    assert gate.allowed is True
    assert gate.manifest_fields["formula_drift_keys"] == [
        "oversold_bounce_sha256",
        "price_returns_sha256",
    ]


def test_multi_key_unrecorded_prior_component_not_gate_falsely(tmp_path):
    # 先验 manifest 只记录过单组件 (形态早于双指纹扩充) 时不对新组件误报 —
    # 「无 prior 恒放行」按已记录组件逐键适用, 防护栏不对缺失历史假阳性。
    prior_path = _write_prior(tmp_path, _prior_rows())
    gate = evaluate_formula_change_gate(
        _multi_manifest({"oversold_bounce_sha256": "aa"}),
        prior_path,
        {"oversold_bounce_sha256": "aa", "price_returns_sha256": "cc"},
        _candidate(_prior_rows()),
        force=False,
        fingerprint_keys=OB_FP_KEYS,
    )
    assert gate.allowed is True
    assert gate.manifest_fields == {}
