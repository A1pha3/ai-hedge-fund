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
