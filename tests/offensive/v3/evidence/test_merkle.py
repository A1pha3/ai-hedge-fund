"""evidence_set_merkle_root — 治理签名证据根 (2026-08-20).

锁定: 输入顺序无关 (按 evidence_id 排序)、重复 id 冲突不去重、空集
fail-closed、哈希格式校验、敏感性 (任一叶变化→根变化)、**每层**奇数复制
(大小 5/6/9… 的越界回归钉死)、叶数入根 (同拓扑不同大小无歧义)、黄金根
值钉死算法稳定、独立第二实现 (递归参考) 逐位交叉验证、包含证明全sizes
往返 + 篡改面。
"""

from __future__ import annotations

import json

import pytest

from src.screening.offensive.v3.evidence.merkle import (
    EvidenceMerkleError,
    MerkleInclusionProof,
    MerklePathStep,
    evidence_set_merkle_root,
    merkle_inclusion_proof,
    verify_merkle_inclusion,
)

PAIRS = [
    ("btst:snap-1:300001:selected", "a" * 64),
    ("market:bars:20260806", "b" * 64),
    ("market:bars:20260807", "c" * 64),
]


def _sized_pairs(n: int) -> list[tuple[str, str]]:
    return [(f"ev-{i:03d}", format(i, "064x")) for i in range(n)]


def _reference_root(bindings: list[tuple[str, str]]) -> str:
    """独立第二实现: 递归形状 (非逐层循环), 与生产实现逐位交叉验证。

    与生产实现的策略差异仅是算法形状 — 排序/去重前置、奇数层复制末位、
    叶数入根三条策略相同, 由断言而非复制保证。
    """
    import hashlib
    from collections import OrderedDict

    from src.screening.offensive.v3.trust import canonical_json_bytes

    def h(domain: str, payload: dict) -> str:
        return hashlib.sha256(
            canonical_json_bytes({"domain": domain, **payload})
        ).hexdigest()

    seen: OrderedDict[str, str] = OrderedDict()
    for evidence_id, artifact_hash in bindings:
        assert evidence_id not in seen
        seen[evidence_id] = artifact_hash
    leaves = [
        h(
            "ai-hedge-fund.v3.evidence.merkle.leaf.v1",
            {"evidence_id": i, "artifact_hash": seen[i]},
        )
        for i in sorted(seen)
    ]

    def rec(level: list[str]) -> str:
        if len(level) == 1:
            return level[0]
        if len(level) % 2 == 1:
            level = [*level, level[-1]]
        return rec(
            [
                h(
                    "ai-hedge-fund.v3.evidence.merkle.node.v1",
                    {"left": level[i], "right": level[i + 1]},
                )
                for i in range(0, len(level), 2)
            ]
        )

    return h(
        "ai-hedge-fund.v3.evidence.merkle.root.v1",
        {"top": rec(leaves), "leaf_count": len(leaves)},
    )


def test_input_order_is_irrelevant():
    forward = evidence_set_merkle_root(PAIRS)
    shuffled = evidence_set_merkle_root([PAIRS[2], PAIRS[0], PAIRS[1]])
    assert forward == shuffled


def test_golden_root_pins_the_algorithm():
    # 黄金根: 算法 (排序/叶/节点/根域+叶数折入/奇数复制) 变化即此断言失败
    assert (
        evidence_set_merkle_root(PAIRS)
        == "7f70936a257280a431f747df6d61a93fbb91d0681073286e6b26ee55b3484d06"
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


def test_odd_level_duplication_happens_at_every_level():
    """回归钉死: 大小 5/6/9 (首个配对层落奇数) 曾 IndexError。"""
    for n in (5, 6, 9, 10, 11, 12, 13):
        assert len(evidence_set_merkle_root(_sized_pairs(n))) == 64


def test_leaf_count_is_folded_into_the_root():
    # 同拓扑结构、不同叶数 → 不同根 (结构性歧义封死)
    two = evidence_set_merkle_root(PAIRS[:2])
    three = evidence_set_merkle_root(PAIRS)
    four = evidence_set_merkle_root(PAIRS + [("another:1", "d" * 64)])
    assert len({two, three, four}) == 3
    assert evidence_set_merkle_root(list(reversed(PAIRS))) == three


def test_independent_reference_implementation_agrees_bit_for_bit():
    """独立递归参考实现 vs 生产逐层实现: 大小 1..33 逐位一致。"""
    for n in range(1, 34):
        pairs = _sized_pairs(n)
        assert evidence_set_merkle_root(pairs) == _reference_root(pairs), n


@pytest.mark.parametrize("n", list(range(1, 10)))
def test_inclusion_proof_round_trips_for_every_leaf(n: int):
    pairs = _sized_pairs(n)
    root = evidence_set_merkle_root(pairs)
    for evidence_id, artifact_hash in pairs:
        proof = merkle_inclusion_proof(pairs, evidence_id)
        assert proof.artifact_hash == artifact_hash
        assert proof.leaf_count == n
        verify_merkle_inclusion(root, proof)  # 不抛即通过
        rebuilt = MerkleInclusionProof.model_validate_json(
            proof.model_dump_json(), strict=True
        )
        assert rebuilt == proof
        verify_merkle_inclusion(root, rebuilt)


def test_inclusion_proof_tamper_faces():
    pairs = _sized_pairs(6)  # 含奇数层的多级树
    root = evidence_set_merkle_root(pairs)
    proof = merkle_inclusion_proof(pairs, "ev-002")

    forged_hash = proof.model_dump_json().replace(proof.artifact_hash, "f" * 64)
    with pytest.raises(EvidenceMerkleError) as ei:
        verify_merkle_inclusion(
            root, MerkleInclusionProof.model_validate_json(forged_hash, strict=True)
        )
    assert ei.value.code == "inclusion_proof_mismatch"

    # 截断路径: 过模型校验 (叶数>1 且路径非空), 但验证面复算必拒
    dropped = json.loads(proof.model_dump_json())
    dropped["path"] = dropped["path"][:-1]
    truncated = MerkleInclusionProof.model_validate_json(
        json.dumps(dropped), strict=True
    )
    with pytest.raises(EvidenceMerkleError):
        verify_merkle_inclusion(root, truncated)

    other_root = evidence_set_merkle_root(_sized_pairs(5))
    with pytest.raises(EvidenceMerkleError):
        verify_merkle_inclusion(other_root, proof)

    with pytest.raises(EvidenceMerkleError) as ei:
        merkle_inclusion_proof(pairs, "ev-not-in-set")
    assert ei.value.code == "evidence_id_not_in_set"


def test_single_leaf_proof_is_empty_path():
    pairs = _sized_pairs(1)
    root = evidence_set_merkle_root(pairs)
    proof = merkle_inclusion_proof(pairs, "ev-000")
    assert proof.path == () and proof.leaf_count == 1
    verify_merkle_inclusion(root, proof)
    # 多叶证明不允许空路径 / 单叶证明不允许非空路径
    with pytest.raises(Exception):
        MerkleInclusionProof(
            evidence_id="ev-000", artifact_hash="a" * 64, leaf_count=2, path=()
        )
    with pytest.raises(Exception):
        MerkleInclusionProof(
            evidence_id="ev-000",
            artifact_hash="a" * 64,
            leaf_count=1,
            path=(MerklePathStep(sibling_hash="b" * 64, sibling_on_right=True),),
        )
