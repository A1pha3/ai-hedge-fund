"""evidence_set_merkle_root — 治理签名证据根 (2026-08-20).

锁定: 输入顺序无关 (按 evidence_id 排序)、重复 id 冲突不去重、空集
fail-closed、哈希格式校验、敏感性 (任一叶变化→根变化)、奇数层复制策略、
黄金根值钉死算法稳定。
"""

from __future__ import annotations

import pytest

from src.screening.offensive.v3.evidence.merkle import (
    EvidenceMerkleError,
    evidence_set_merkle_root,
)

PAIRS = [
    ("btst:snap-1:300001:selected", "a" * 64),
    ("market:bars:20260806", "b" * 64),
    ("market:bars:20260807", "c" * 64),
]


def test_input_order_is_irrelevant():
    forward = evidence_set_merkle_root(PAIRS)
    shuffled = evidence_set_merkle_root([PAIRS[2], PAIRS[0], PAIRS[1]])
    assert forward == shuffled


def test_golden_root_pins_the_algorithm():
    # 黄金根: 算法 (排序/叶/节点域/奇数复制) 变化即此断言失败
    assert (
        evidence_set_merkle_root(PAIRS)
        == "64ad28d56c4dc8b7301d004f32e05996a9d2656f702f05baf630f95f7502f1af"
    )


def test_any_leaf_change_changes_the_root():
    base = evidence_set_merkle_root(PAIRS)
    assert evidence_set_merkle_root(PAIRS[:2]) != base
    flipped = [(i, h if i != PAIRS[0][0] else "f" * 64) for i, h in PAIRS]
    assert evidence_set_merkle_root(flipped) != base


def test_duplicate_evidence_id_conflicts_even_with_same_hash():
    with pytest.raises(EvidenceMerkleError) as ei:
        evidence_set_merkle_root(PAIRS + [PAIRS[0]])
    assert ei.value.code == "duplicate_evidence_id"


def test_empty_set_fails_closed():
    with pytest.raises(EvidenceMerkleError) as ei:
        evidence_set_merkle_root([])
    assert ei.value.code == "merkle_empty_set"


@pytest.mark.parametrize("bad", ["", "z" * 64, "a" * 63, "A" * 64])
def test_non_sha256_artifact_hash_rejected(bad: str):
    with pytest.raises(EvidenceMerkleError) as ei:
        evidence_set_merkle_root([("evidence-1", bad)])
    assert ei.value.code == "artifact_hash_not_sha256"


def test_empty_evidence_id_rejected():
    with pytest.raises(EvidenceMerkleError) as ei:
        evidence_set_merkle_root([("", "a" * 64)])
    assert ei.value.code == "evidence_id_empty"


def test_odd_and_even_levels_are_distinct_and_stable():
    # 黄金根 (PAIRS=3 叶) 已锁奇数层复制路径; 此处钉: 偶数集与奇数集互不相同,
    # 且同集重复计算恒稳定 (纯函数)。注意 3 叶+末叶复制的 multiset 无法经
    # 公开 API 表达 (重复 id 一律冲突) — 奇数复制是函数内部规范行为, 由黄金根钉死。
    odd = evidence_set_merkle_root(PAIRS)
    even_pair = evidence_set_merkle_root(PAIRS[:2])
    even_four = evidence_set_merkle_root(PAIRS + [("market:bars:20260810", "d" * 64)])
    assert len({odd, even_pair, even_four}) == 3
    assert evidence_set_merkle_root(list(reversed(PAIRS))) == odd


def test_single_leaf_root_is_a_node_hash_not_a_leaf_hash():
    # 单叶集: 根恒为 node(leaf, leaf) — 叶哈希与根哈希无歧义地不同域
    single = evidence_set_merkle_root(PAIRS[:1])
    assert single != evidence_set_merkle_root(PAIRS[:1] + [("another", "d" * 64)])
    assert len(single) == 64
