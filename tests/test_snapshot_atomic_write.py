"""R88 corrupt-snapshot CRASH vector: ``DataSnapshotExporter._write_json`` must
write atomically so a crash mid-write leaves the prior snapshot intact, not truncated.

同名坑修复: snapshot._write_json 此前非原子 (write_text), 与 c294 的原子
btst_reporting_utils._write_json 同名不同义, 易误用。本测试锁定其原子性 +
default=str 行为 (payload 含 datetime, 需要 default=str 序列化)。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def test_write_json_atomic_crash_preserves_prior(tmp_path: Path, monkeypatch) -> None:
    """非原子 write_text 在 open(mode='w') 时立即 truncate; crash 落在 truncate
    之后留下空/半截文件。原子写 (tempfile + os.replace) 永不 truncate 最终路径,
    直到完整 payload 提交。"""
    from src.data.snapshot import DataSnapshotExporter

    target = tmp_path / "snap.json"
    target.write_text(json.dumps({"prior": True, "keep": "alive"}), encoding="utf-8")

    _orig = Path.write_text

    def crashing_write_text(self, data, *a, **kw):  # noqa: ANN001
        if self == target:
            open(self, "w").close()  # write_text opens mode='w' → truncates
            raise OSError("simulated mid-write crash on snapshot")
        return _orig(self, data, *a, **kw)

    monkeypatch.setattr(Path, "write_text", crashing_write_text)
    try:
        DataSnapshotExporter._write_json(target, {"new": 1})
    except OSError:
        pass  # acceptable: 写失败; 我们关心的是文件状态

    raw = target.read_text(encoding="utf-8")
    assert raw.strip(), (
        "prior snapshot must not be truncated-empty after a crashed write — "
        "non-atomic write_text truncates on open (R88 corrupt-snapshot CRASH vector root cause)"
    )
    json.loads(raw)  # must parse cleanly — no half-written corrupt file


def test_write_json_preserves_default_str_for_datetime(tmp_path: Path) -> None:
    """default=str 必须保留 (payload 含 datetime 等非 JSON 原生类型, 依赖 default=str 序列化)。"""
    from src.data.snapshot import DataSnapshotExporter

    target = tmp_path / "dt.json"
    DataSnapshotExporter._write_json(target, {"ts": datetime(2026, 7, 2, 12, 0, 0), "n": 1})

    raw = target.read_text(encoding="utf-8")
    assert "2026" in raw, "datetime must be serialized via default=str (not crash, not NaN)"
    assert json.loads(raw)["n"] == 1
