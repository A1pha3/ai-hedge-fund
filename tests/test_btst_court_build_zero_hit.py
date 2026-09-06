"""btst_court_build zero_hit_day_audit — R138 Op2 build 侧整天空洞可见性测试.

纯函数 fixture 测试 (零网络/零 gitignored 资产, R10 slot 自足纪律):
candidates>0 ∧ hits=0 的整天是 court 证据宇宙静默归零的唯一显形面 —
0811/0813 整日空洞曾沉默三周 (6 笔生产买入落入), 本审计让该形态在
构建当刻即以候选数显形。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from btst_court_build import (  # noqa: E402
    record_day_outcome,
    zero_hit_day_audit,
)


def test_empty_audit_returns_empty():
    assert zero_hit_day_audit({}) == []


def test_zero_hit_day_listed_with_candidate_count():
    audit = {"20260811": {"candidates": 78, "hits": 0}}
    assert zero_hit_day_audit(audit) == [{"day": "20260811", "candidates": 78}]


def test_legit_empty_limit_up_day_excluded():
    """candidates=0 是合法空涨停日 (universe_audit.empty_days 会计) — 不混入."""
    audit = {"20260906": {"candidates": 0, "hits": 0}}
    assert zero_hit_day_audit(audit) == []


def test_normal_day_excluded():
    audit = {"20260812": {"candidates": 63, "hits": 8}}
    assert zero_hit_day_audit(audit) == []


def test_multi_day_sorted_ascending():
    audit = {
        "20260813": {"candidates": 80, "hits": 0},
        "20260811": {"candidates": 78, "hits": 0},
        "20260812": {"candidates": 63, "hits": 8},
    }
    assert zero_hit_day_audit(audit) == [
        {"day": "20260811", "candidates": 78},
        {"day": "20260813", "candidates": 80},
    ]


def test_partial_hits_day_not_listed():
    """hits>0 但 <candidates 是正常漏斗 — 只整天全零才显形."""
    audit = {"20260814": {"candidates": 55, "hits": 3}}
    assert zero_hit_day_audit(audit) == []


@pytest.mark.parametrize("bad", [
    {"candidates": -1, "hits": 0},
    {"candidates": 5, "hits": -2},
    {"candidates": True, "hits": 0},
    {"candidates": 5, "hits": None},
    {"hits": 0},
])
def test_malformed_row_typed_reject(bad):
    with pytest.raises(ValueError):
        zero_hit_day_audit({"20260811": bad})


def test_record_day_outcome_accumulates():
    audit: dict = {}
    record_day_outcome(audit, "20260811", 78, 0)
    record_day_outcome(audit, "20260811", 0, 0)
    record_day_outcome(audit, "20260812", 63, 8)
    assert audit == {
        "20260811": {"candidates": 78, "hits": 0},
        "20260812": {"candidates": 63, "hits": 8},
    }


# ---------------------------------------------------------------------------
# R138 Op3 对抗审查: 审计写入/读取面 typed 硬化.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [2.7, 2.0, "3", True, None])
def test_record_day_outcome_rejects_non_int_typed(bad):
    with pytest.raises(TypeError):
        record_day_outcome({}, "20260811", bad, 0)
    with pytest.raises(TypeError):
        record_day_outcome({}, "20260811", 1, bad)


@pytest.mark.parametrize("bad_row", [None, 42, "x", ["candidates", "hits"]])
def test_zero_hit_day_audit_non_mapping_row_typed(bad_row):
    with pytest.raises(ValueError):
        zero_hit_day_audit({"20260811": bad_row})
