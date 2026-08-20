"""Plan 03 Task 1: content-addressed durable blob store."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.screening.offensive.v3.evidence.blob_store import (
    BlobStore,
    BlobStoreError,
)


def test_put_get_round_trip_is_content_addressed(tmp_path: Path) -> None:
    store = BlobStore(tmp_path / "blobs")
    payload = b'{"market": "closed-empty"}'
    digest = store.put_durable(payload)
    assert digest == hashlib.sha256(payload).hexdigest()
    assert store.get(digest) == payload
    assert store.blob_path(digest).exists()


def test_identical_put_converges(tmp_path: Path) -> None:
    store = BlobStore(tmp_path / "blobs")
    payload = b"payload-bytes"
    first = store.put_durable(payload)
    second = store.put_durable(payload)
    assert first == second
    assert store.get(first) == payload


def test_unknown_hash_fails_closed(tmp_path: Path) -> None:
    store = BlobStore(tmp_path / "blobs")
    with pytest.raises(BlobStoreError) as excinfo:
        store.get("f" * 64)
    assert excinfo.value.code == "blob_not_found"


def test_non_regular_blob_path_fails_closed(tmp_path: Path) -> None:
    store = BlobStore(tmp_path / "blobs")
    payload = b"real-payload"
    digest = store.put_durable(payload)
    # Replace the blob file with a directory: reads must fail closed.
    blob = store.blob_path(digest)
    blob.unlink()
    blob.mkdir()
    with pytest.raises(BlobStoreError) as excinfo:
        store.get(digest)
    assert excinfo.value.code == "blob_not_regular"


def test_symlink_root_is_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(BlobStoreError) as excinfo:
        BlobStore(link)
    assert excinfo.value.code == "blob_root_symlink"


# ----------------------------------------------------------------
# 对抗性回归网 (autodev 第四轮迭代 2, 2026-08-21): blob store 是
# Plan 03 证据时间轴 "blob-before-envelope" 的耐久工件地基, 其文件
# 系统面与 trial root 同属 "冷读免 sqlite 即信任" 契约。以下把两个
# 已实锤的 symlink 中间组件穿透钉死为类型化拒绝。


def test_symlinked_parent_of_root_is_rejected(tmp_path: Path) -> None:
    """构造守卫必须覆盖 root 的全部父组件, 不只最终一段。"""
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real)
    with pytest.raises(BlobStoreError) as excinfo:
        BlobStore(alias / "blobs")
    assert excinfo.value.code == "blob_root_rejected"


def test_get_rejects_symlinked_intermediate_directory(tmp_path: Path) -> None:
    """PoC-B: root/<hash[:2]> 是 symlink 时 O_NOFOLLOW 不保护中间组件 —
    get 会把 root 之外的字节当作该 hash 的原始 payload 返回。"""
    payload = b"legit payload stored elsewhere"
    digest = hashlib.sha256(payload).hexdigest()
    real = tmp_path / "real"
    (real / digest[:2] / digest[2:4]).mkdir(parents=True)
    (real / digest[:2] / digest[2:4] / digest).write_bytes(payload)
    root = tmp_path / "blobs"
    root.mkdir()
    (root / digest[:2]).symlink_to(real / digest[:2], target_is_directory=True)
    store = BlobStore(root)
    with pytest.raises(BlobStoreError) as excinfo:
        store.get(digest)
    assert excinfo.value.code == "blob_component_rejected"


def test_put_rejects_symlinked_intermediate_directory(tmp_path: Path) -> None:
    """PoC-C: mkdir(parents=True) 穿过预置 symlink, blob 经 tmp+replace
    写进 root 之外 — 任何字节都不得落盘 victim。"""
    import itertools

    victim = tmp_path / "victim"
    victim.mkdir()
    root = tmp_path / "blobs"
    root.mkdir()
    (root / "ab").symlink_to(victim, target_is_directory=True)
    store = BlobStore(root)
    payload = next(
        f"probe-{i}".encode()
        for i in itertools.count()
        if hashlib.sha256(f"probe-{i}".encode()).hexdigest().startswith("ab")
    )
    with pytest.raises(BlobStoreError) as excinfo:
        store.put_durable(payload)
    assert excinfo.value.code == "blob_component_rejected"
    assert not list(victim.rglob("*")), "任何字节都不得落入 victim"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "xyz" * 21 + "x",  # 64 chars, non-hex
        "../" + "a" * 61,
        "a" * 63,  # 63 chars
        "A" * 64,  # uppercase
        "0" * 63 + "/x",
    ],
)
def test_blob_path_rejects_non_hash_shapes(tmp_path: Path, bad: str) -> None:
    """content_hash 是信封字段 (untrusted-ish): 三段拼接前必须过 64-hex
    形状校验 — 这是纵深, 即使穿越形状未被证明可利用。"""
    store = BlobStore(tmp_path / "blobs")
    with pytest.raises(BlobStoreError) as excinfo:
        store.blob_path(bad)
    assert excinfo.value.code == "blob_hash_invalid"
    with pytest.raises(BlobStoreError):
        store.get(bad)
