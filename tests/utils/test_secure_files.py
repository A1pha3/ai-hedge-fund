"""Tests for security-hardened file reading."""

import os
from pathlib import Path

import pytest

from src.utils.secure_files import SecureReadError, read_regular_bytes


def _write_file(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path


class TestRegularFileRead:
    def test_reads_regular_file(self, tmp_path):
        f = _write_file(tmp_path / "data.json", b'{"key": "value"}')
        assert read_regular_bytes(f, max_bytes=1024) == b'{"key": "value"}'

    def test_empty_file(self, tmp_path):
        f = _write_file(tmp_path / "empty.txt", b"")
        assert read_regular_bytes(f, max_bytes=1024) == b""

    def test_respects_max_bytes(self, tmp_path):
        f = _write_file(tmp_path / "big.txt", b"x" * 2048)
        with pytest.raises(SecureReadError, match="exceeds max_bytes"):
            read_regular_bytes(f, max_bytes=1024)

    def test_exact_max_bytes_allowed(self, tmp_path):
        content = b"x" * 100
        f = _write_file(tmp_path / "exact.txt", content)
        assert read_regular_bytes(f, max_bytes=100) == content

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_regular_bytes(tmp_path / "nonexistent", max_bytes=1024)


class TestSymlinkRejection:
    def test_rejects_symlink(self, tmp_path):
        target = _write_file(tmp_path / "real.txt", b"data")
        link = tmp_path / "link.txt"
        os.symlink(target, link)
        with pytest.raises(SecureReadError, match="symlink"):
            read_regular_bytes(link, max_bytes=1024)


class TestNonRegularRejection:
    def test_rejects_directory(self, tmp_path):
        with pytest.raises(SecureReadError, match="directory"):
            read_regular_bytes(tmp_path, max_bytes=1024)

    def test_rejects_fifo(self, tmp_path):
        fifo = tmp_path / "fifo"
        os.mkfifo(fifo)
        with pytest.raises(SecureReadError, match="not a regular file"):
            read_regular_bytes(fifo, max_bytes=1024)


class TestLargeFileRejection:
    def test_rejects_oversize_before_read(self, tmp_path):
        f = _write_file(tmp_path / "large.bin", b"0" * 10000)
        with pytest.raises(SecureReadError, match="exceeds max_bytes"):
            read_regular_bytes(f, max_bytes=100)


class TestAncestorSymlinkRejection:
    def test_read_regular_bytes_rejects_ancestor_symlink(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        (real / "manifest.json").write_text("{}", encoding="utf-8")
        linked = tmp_path / "linked"
        linked.symlink_to(real, target_is_directory=True)
        with pytest.raises(SecureReadError):
            read_regular_bytes(linked / "manifest.json", max_bytes=1024)

    def test_reads_through_real_directory_chain(self, tmp_path):
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        target = nested / "data.json"
        target.write_text('{"ok": true}', encoding="utf-8")
        assert read_regular_bytes(target, max_bytes=1024) == b'{"ok": true}'

