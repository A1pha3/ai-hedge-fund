import json
import os
import stat
from pathlib import Path

import pandas as pd
import pytest

import src.utils.atomic_files as atomic_files
from src.utils.atomic_files import atomic_write_csv, atomic_write_json


def test_json_failure_preserves_previous_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "report.json"
    target.write_text('{"version": 1}', encoding="utf-8")
    monkeypatch.setattr(json, "dump", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        atomic_write_json(target, {"version": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 1}
    assert list(tmp_path.glob(".*.tmp")) == []


def test_csv_round_trip_replaces_complete_file(tmp_path: Path) -> None:
    target = tmp_path / "prices.csv"
    atomic_write_csv(target, pd.DataFrame([{"date": "20260710", "close": 10.0}]))
    assert pd.read_csv(target, dtype={"date": str}).to_dict("records") == [
        {"date": "20260710", "close": 10.0}
    ]


def test_json_sanitizes_nonfinite_values_nested_in_tuple(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    atomic_write_json(target, {"values": (1.0, (float("nan"), float("inf")))})
    assert json.loads(target.read_text(encoding="utf-8")) == {"values": [1.0, [None, None]]}


@pytest.mark.parametrize("mode", [0o640, 0o644])
def test_replacement_preserves_existing_target_mode(tmp_path: Path, mode: int) -> None:
    target = tmp_path / "report.json"
    target.write_text("{}", encoding="utf-8")
    target.chmod(mode)
    atomic_write_json(target, {"ok": True})
    assert stat.S_IMODE(target.stat().st_mode) == mode


def test_new_file_uses_ordinary_umask_derived_mode(tmp_path: Path) -> None:
    ordinary = tmp_path / "ordinary.json"
    ordinary.write_text("{}", encoding="utf-8")
    target = tmp_path / "atomic.json"
    atomic_write_json(target, {"ok": True})
    assert stat.S_IMODE(target.stat().st_mode) == stat.S_IMODE(ordinary.stat().st_mode)
    assert target.stat().st_mode & stat.S_IRUSR


def test_file_fsync_failure_preserves_old_target_and_cleans_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "report.json"
    target.write_text('{"version": 1}', encoding="utf-8")
    monkeypatch.setattr(os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("fsync failed")))
    with pytest.raises(OSError, match="fsync failed"):
        atomic_write_json(target, {"version": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 1}
    assert list(tmp_path.glob(".*.tmp")) == []


def test_replace_failure_preserves_old_target_and_cleans_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "report.json"
    target.write_text('{"version": 1}', encoding="utf-8")
    monkeypatch.setattr(os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("replace failed")))
    with pytest.raises(OSError, match="replace failed"):
        atomic_write_json(target, {"version": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 1}
    assert list(tmp_path.glob(".*.tmp")) == []


def test_csv_serialization_failure_preserves_old_target_and_cleans_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "prices.csv"
    target.write_text("date,close\n20260709,9.0\n", encoding="utf-8")
    monkeypatch.setattr(pd.DataFrame, "to_csv", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("write failed")))
    with pytest.raises(OSError, match="write failed"):
        atomic_write_csv(target, pd.DataFrame([{"date": "20260710", "close": 10.0}]))
    assert target.read_text(encoding="utf-8") == "date,close\n20260709,9.0\n"
    assert list(tmp_path.glob(".*.tmp")) == []


def test_fdopen_failure_closes_raw_fd_and_cleans_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "report.json"
    target.write_text("{}", encoding="utf-8")
    closed: list[int] = []
    real_close = os.close

    def observe_close(fd: int) -> None:
        closed.append(fd)
        real_close(fd)

    monkeypatch.setattr(atomic_files.os, "close", observe_close)
    monkeypatch.setattr(atomic_files.os, "fdopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("fdopen failed")))
    with pytest.raises(OSError, match="fdopen failed"):
        atomic_write_json(target, {})
    assert len(closed) == 1
    assert list(tmp_path.glob(".*.tmp")) == []


def test_directory_fsync_failure_after_replace_is_best_effort(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_fsync = os.fsync

    def fail_for_directory(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("directory fsync unsupported")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_for_directory)
    target = tmp_path / "report.json"
    atomic_write_json(target, {"ok": True})
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}


def test_directory_close_failure_after_replace_is_best_effort(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_close = os.close

    def fail_after_close(fd: int) -> None:
        is_directory = stat.S_ISDIR(os.fstat(fd).st_mode)
        real_close(fd)
        if is_directory:
            raise OSError("directory close failed")

    monkeypatch.setattr(atomic_files.os, "close", fail_after_close)
    target = tmp_path / "report.json"
    atomic_write_json(target, {"ok": True})
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}
