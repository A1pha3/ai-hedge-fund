"""Evidence-set merkle root — 治理签名 primitive (2026-08-20).

前向 Trial 的冻结共享输入 (``freeze_shared_input``) 需要
``evidence_set_merkle_root`` 把一次决策消费的证据集钉进哈希。此前该参数
只有占位哈希 (shadow_trust 合成 grant / 测试 crib), 没有单一计算源 —
本模块提供唯一的确定性纯函数: 叶子 = (evidence_id, artifact_hash) 按
evidence_id 排序, 奇数节点复制末位, 空集 fail-closed, 叶/节点域分离。

纯函数、零 I/O: 不读 store、不判证据内容 — 调用方 (未来的特权 worker)
负责传入的正是证据时间轴上 active 的记录。

信任模型 (第二轮对抗审查精修, 2026-08-20): 本函数绑定的是**调用方声明
的集合** — 它不证明集合成员恰好是决策消费的证据。纯 store 侧派生同样
不可行 (store 不知道决策的消费选择)。正确的官方形态是三段式: 特权
worker 声明消费集 → Evidence Store 逐成员背书 (active 修订 +
``available_at <= cutoff``) → 背书集上计算本根。"哪些 evidence_id 构成
一次决策的证据集" (成员规则) 必须在特权 worker 落地前**预注册成文** —
没有成员规则, 根绑定的是一个任意集合。
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from src.screening.offensive.v3.trust import canonical_json_bytes

_LEAF_DOMAIN = "ai-hedge-fund.v3.evidence.merkle.leaf.v1"
_NODE_DOMAIN = "ai-hedge-fund.v3.evidence.merkle.node.v1"
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


def evidence_set_merkle_root(bindings: Iterable[tuple[str, str]]) -> str:
    """One deterministic merkle root over the consumed evidence set.

    输入是 ``(evidence_id, artifact_hash)`` 对的任意可迭代。策略全部显式:

    - **排序**: 叶子按 ``evidence_id`` 字典序 — 调用方的输入顺序无关;
    - **去重**: 不去重。任何重复的 ``evidence_id`` (无论哈希是否一致)
      都是 ``duplicate_evidence_id`` 冲突 — 静默去重会掩盖调用方 bug;
    - **奇数层**: 复制末位节点补偶 (含单叶集: 根恒为 node(leaf, leaf),
      叶哈希与根哈希永不存在歧义);
    - **空集**: ``merkle_empty_set`` fail-closed — 没有消费任何证据的
      决策不铸造证据根 (no-signal 会话的绑定语义由未来的 runner 裁决,
      本函数不替它发明空根)。
    """
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
    level = [_leaf_hash(evidence_id, collected[evidence_id]) for evidence_id in sorted(collected)]
    if len(level) % 2 == 1:
        level.append(level[-1])  # 单叶集同样复制补偶: 根恒为节点哈希
    while len(level) > 1:
        level = [_node_hash(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


__all__ = ["EvidenceMerkleError", "evidence_set_merkle_root"]
