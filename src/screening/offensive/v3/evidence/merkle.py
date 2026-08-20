"""Evidence-set merkle root — 治理签名 primitive (2026-08-20).

前向 Trial 的冻结共享输入 (``freeze_shared_input``) 需要
``evidence_set_merkle_root`` 把一次决策消费的证据集钉进哈希。此前该参数
只有占位哈希 (shadow_trust 合成 grant / 测试 crib), 没有单一计算源 —
本模块提供唯一的确定性纯函数: 叶子 = (evidence_id, artifact_hash) 按
evidence_id 排序, 奇数层复制末位, 空集 fail-closed, 叶/节点/根域分离。

纯函数、零 I/O: 不读 store、不判证据内容 — 调用方 (未来的特权 worker)
负责传入的正是证据时间轴上 active 的记录。

信任模型 (第二轮对抗审查精修, 2026-08-20): 本函数绑定的是**调用方声明
的集合** — 它不证明集合成员恰好是决策消费的证据。纯 store 侧派生同样
不可行 (store 不知道决策的消费选择)。正确的官方形态是三段式: 特权
worker 声明消费集 → Evidence Store 逐成员背书 (active 修订 +
``available_at <= cutoff``) → 背书集上计算本根。"哪些 evidence_id 构成
一次决策的证据集" (成员规则) 必须在特权 worker 落地前**预注册成文** —
没有成员规则, 根绑定的是一个任意集合。

第三轮修复 (2026-08-20, 遗留项收口时实证): 奇数复制曾只在首轮前做
一次, 集合大小 5/6/9… (首个配对层落奇数) 直接 IndexError — 黄金测试
只取 3 叶未暴露。现复制在**每层**配对前执行, 并以独立第二实现 (递归
参考) 对大小 1..33 逐位交叉验证。同轮把叶数折进根 (根域混入
``leaf_count``): 单叶根与多叶根、不同大小的同拓扑结构从此无结构性
歧义, 不再单靠 SHA256 抗碰撞兜底。
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import ClassVar, Self

from pydantic import model_validator

from src.screening.offensive.v3.contracts.base import CanonicalModel
from src.screening.offensive.v3.trust import canonical_json_bytes

_LEAF_DOMAIN = "ai-hedge-fund.v3.evidence.merkle.leaf.v1"
_NODE_DOMAIN = "ai-hedge-fund.v3.evidence.merkle.node.v1"
_ROOT_DOMAIN = "ai-hedge-fund.v3.evidence.merkle.root.v1"
_HEX = set("0123456789abcdef")


class EvidenceMerkleError(RuntimeError):
    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


def _is_sha256_hex(value: str) -> bool:
    return len(value) == 64 and all(ch in _HEX for ch in value)


def _leaf_hash(evidence_id: str, artifact_hash: str) -> str:
    preimage = canonical_json_bytes(
        {"domain": _LEAF_DOMAIN, "evidence_id": evidence_id, "artifact_hash": artifact_hash}
    )
    return hashlib.sha256(preimage).hexdigest()


def _node_hash(left: str, right: str) -> str:
    preimage = canonical_json_bytes({"domain": _NODE_DOMAIN, "left": left, "right": right})
    return hashlib.sha256(preimage).hexdigest()


def _root_hash(top: str, leaf_count: int) -> str:
    preimage = canonical_json_bytes({"domain": _ROOT_DOMAIN, "top": top, "leaf_count": leaf_count})
    return hashlib.sha256(preimage).hexdigest()


def _collect_leaves(bindings: Iterable[tuple[str, str]]) -> list[str]:
    collected: dict[str, str] = {}
    for evidence_id, artifact_hash in bindings:
        if not evidence_id:
            raise EvidenceMerkleError("evidence_id_empty", "evidence id must be non-empty")
        if not _is_sha256_hex(artifact_hash):
            raise EvidenceMerkleError(
                "artifact_hash_not_sha256",
                "artifact hash must be 64-hex sha256",
                evidence_id=evidence_id,
            )
        if evidence_id in collected:
            raise EvidenceMerkleError(
                "duplicate_evidence_id",
                "the same evidence id appears twice in one evidence set",
                evidence_id=evidence_id,
            )
        collected[evidence_id] = artifact_hash
    if not collected:
        raise EvidenceMerkleError("merkle_empty_set", "cannot root an empty evidence set")
    return [_leaf_hash(evidence_id, collected[evidence_id]) for evidence_id in sorted(collected)]


def evidence_set_merkle_root(bindings: Iterable[tuple[str, str]]) -> str:
    """One deterministic merkle root over the consumed evidence set.

    输入是 ``(evidence_id, artifact_hash)`` 对的任意可迭代。策略全部显式:

    - **排序**: 叶子按 ``evidence_id`` 字典序 — 调用方的输入顺序无关;
    - **去重**: 不去重。任何重复的 ``evidence_id`` (无论哈希是否一致)
      都是 ``duplicate_evidence_id`` 冲突 — 静默去重会掩盖调用方 bug;
    - **奇数层**: **每一层**配对前复制末位节点补偶 (含单叶集: 唯一层
      即为叶层, 根 = fold(leaf, 1));
    - **叶数入根**: 最终根域混入 ``leaf_count`` — 单叶/多叶、不同大小
      的同拓扑结构无结构性歧义;
    - **空集**: ``merkle_empty_set`` fail-closed — 没有消费任何证据的
      决策不铸造证据根 (no-signal 会话的绑定语义由未来的 runner 裁决,
      本函数不替它发明空根)。
    """
    level = _collect_leaves(bindings)
    leaf_count = len(level)
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [_node_hash(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return _root_hash(level[0], leaf_count)


class MerklePathStep(CanonicalModel):
    """一级审计路径: 兄弟哈希及其所在侧。"""

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.evidence.merkle-path-step.v1"

    sibling_hash: str
    sibling_on_right: bool


class MerkleInclusionProof(CanonicalModel):
    """一个叶子的包含证明: 从叶到根的审计路径 + 叶数 (复算奇数复制)。

    兄弟为复制节点 (奇数层末位) 时 ``sibling_hash`` 等于当时节点自身的
    哈希 — 验证方按普通兄弟哈希处理即可, 叶数在根部折入使结构可复算。
    """

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.evidence.merkle-inclusion-proof.v1"

    evidence_id: str
    artifact_hash: str
    leaf_count: int
    path: tuple[MerklePathStep, ...]

    @model_validator(mode="after")
    def validate_proof(self) -> Self:
        if self.leaf_count < 1:
            raise ValueError("leaf_count must be positive")
        if self.leaf_count == 1 and self.path:
            raise ValueError("a single-leaf proof carries an empty path")
        if self.leaf_count > 1 and not self.path:
            raise ValueError("a multi-leaf proof requires a non-empty path")
        return self


def merkle_inclusion_proof(
    bindings: Iterable[tuple[str, str]], evidence_id: str
) -> MerkleInclusionProof:
    """Derive the inclusion proof for one leaf of the declared evidence set.

    与 ``evidence_set_merkle_root`` 共享同一收集与建树逻辑 (单一实现,
    不是第二棵树); 集合校验 (重复 id / 哈希格式 / 空集) 原样生效。
    """
    collected: dict[str, str] = {}
    for bound_id, artifact_hash in bindings:
        if not bound_id:
            raise EvidenceMerkleError("evidence_id_empty", "evidence id must be non-empty")
        if not _is_sha256_hex(artifact_hash):
            raise EvidenceMerkleError(
                "artifact_hash_not_sha256",
                "artifact hash must be 64-hex sha256",
                evidence_id=bound_id,
            )
        if bound_id in collected:
            raise EvidenceMerkleError(
                "duplicate_evidence_id",
                "the same evidence id appears twice in one evidence set",
                evidence_id=bound_id,
            )
        collected[bound_id] = artifact_hash
    if evidence_id not in collected:
        raise EvidenceMerkleError(
            "evidence_id_not_in_set",
            "cannot prove inclusion of an evidence id outside the declared set",
            evidence_id=evidence_id,
        )
    level = [_leaf_hash(bound_id, collected[bound_id]) for bound_id in sorted(collected)]
    leaf_count = len(level)
    index = sorted(collected).index(evidence_id)
    path: list[MerklePathStep] = []
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        sibling_on_right = index % 2 == 0
        sibling_index = index + 1 if sibling_on_right else index - 1
        path.append(
            MerklePathStep(
                sibling_hash=level[sibling_index],
                sibling_on_right=sibling_on_right,
            )
        )
        level = [_node_hash(level[i], level[i + 1]) for i in range(0, len(level), 2)]
        index //= 2
    return MerkleInclusionProof(
        evidence_id=evidence_id,
        artifact_hash=collected[evidence_id],
        leaf_count=leaf_count,
        path=tuple(path),
    )


def verify_merkle_inclusion(root: str, proof: MerkleInclusionProof) -> None:
    """Recompute the root from one proof; any mismatch fails closed.

    验证方不需要原集合 — 只需叶身份、审计路径与叶数。单叶集的路径为
    空时直接以叶哈希折根 (与建树端的单叶语义一致)。
    """
    if not _is_sha256_hex(root):
        raise EvidenceMerkleError("root_not_sha256", "root must be 64-hex sha256")
    node = _leaf_hash(proof.evidence_id, proof.artifact_hash)
    for step in proof.path:
        node = (
            _node_hash(node, step.sibling_hash)
            if step.sibling_on_right
            else _node_hash(step.sibling_hash, node)
        )
    if _root_hash(node, proof.leaf_count) != root:
        raise EvidenceMerkleError(
            "inclusion_proof_mismatch",
            "proof does not recompose the declared root",
            evidence_id=proof.evidence_id,
        )


__all__ = [
    "EvidenceMerkleError",
    "MerkleInclusionProof",
    "MerklePathStep",
    "evidence_set_merkle_root",
    "merkle_inclusion_proof",
    "verify_merkle_inclusion",
]
