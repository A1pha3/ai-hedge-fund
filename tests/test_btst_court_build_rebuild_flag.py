"""btst_court_build --rebuild-force 逃生门回归 — 护栏提示与 argparse 实现一致性.

背景 (2026-08-19 autodev op-c312bf11): 防覆盖护栏在指纹不一致时提示
"如确要覆盖用 --rebuild-force", 但 argparse 从未注册该 flag — 指引指向一扇
不存在的门, 同行为重建 (如纯注释变更导致的文件级 sha 假阳性) 无法走通。
本回归网锁两件事:
1. CLI 契约: flag 已注册, 缺省 False, dest=rebuild_force;
2. 护栏语义: 指纹不一致缺省拒绝, 仅 force 时放行 (同指纹/prior 缺失恒放行);
   放行且指纹变化时 manifest 必须诚实披露 formula_change_forced + prior 指纹。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from btst_court_build import (  # noqa: E402
    _manifest_forced_overwrite_fields,
    _parse_args,
    overwrite_allowed,
)


# ---------- CLI 契约 ----------


def test_flag_registered_with_default_false():
    args = _parse_args([])
    assert args.rebuild_force is False
    assert args.end is None


def test_flag_parses_long_form():
    args = _parse_args(["--rebuild-force", "--end", "20260818"])
    assert args.rebuild_force is True
    assert args.end == "20260818"


# ---------- 护栏判定 (纯函数) ----------


def test_guard_same_fingerprint_allows_without_force():
    assert overwrite_allowed("ae33eb8a", "ae33eb8a", force=False) is True


def test_guard_missing_prior_allows():
    assert overwrite_allowed(None, "6cb38b0c", force=False) is True
    assert overwrite_allowed("", "6cb38b0c", force=False) is True


def test_guard_mismatch_blocks_without_force():
    assert overwrite_allowed("ae33eb8a", "6cb38b0c", force=False) is False


def test_guard_mismatch_force_allows():
    assert overwrite_allowed("ae33eb8a", "6cb38b0c", force=True) is True


# ---------- manifest 诚实披露 ----------


def test_forced_manifest_fields_present_only_on_formula_change():
    fields = _manifest_forced_overwrite_fields("ae33eb8a", "6cb38b0c")
    assert fields == {
        "formula_change_forced": True,
        "prior_formula_fingerprint": "ae33eb8a",
    }


def test_forced_manifest_fields_empty_on_same_fingerprint():
    assert _manifest_forced_overwrite_fields("6cb38b0c", "6cb38b0c") == {}
    assert _manifest_forced_overwrite_fields(None, "6cb38b0c") == {}
