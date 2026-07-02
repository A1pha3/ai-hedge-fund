"""R88 corrupt-snapshot CRASH vector (read/write 闭环): research.artifacts 的
selection_snapshot.json / selection_target_replay_input.json 写必须原子。
R101 守了读 (btst_reporting_utils._load_json 容错), 本测试锁住写端 helper 原子性。
"""

from __future__ import annotations

import json
from pathlib import Path


def test_atomic_write_json_crash_preserves_prior(tmp_path: Path, monkeypatch) -> None:
    """_atomic_write_json: crash mid-write 保留 prior, 不 truncate 最终路径。"""
    from src.research.artifacts import _atomic_write_json

    target = tmp_path / "snap.json"
    target.write_text(json.dumps({"prior": True, "keep": "alive"}), encoding="utf-8")

    _orig = Path.write_text

    def crashing_write_text(self, data, *a, **kw):  # noqa: ANN001
        if self == target:
            open(self, "w").close()  # write_text mode='w' → truncate
            raise OSError("simulated mid-write crash")
        return _orig(self, data, *a, **kw)

    monkeypatch.setattr(Path, "write_text", crashing_write_text)
    try:
        _atomic_write_json(target, {"new": 1})
    except OSError:
        pass

    raw = target.read_text(encoding="utf-8")
    assert raw.strip(), (
        "prior artifact must not be truncated-empty after a crashed write — "
        "non-atomic write_text truncates on open (R88 corrupt-snapshot CRASH vector root cause)"
    )
    json.loads(raw)


def test_atomic_write_json_normal_payload_round_trips(tmp_path: Path) -> None:
    """正常写: 内容正确 (保护 round-trip, 现有 write_for_plan 测试也间接覆盖, 这里独立锁)。"""
    from src.research.artifacts import _atomic_write_json

    target = tmp_path / "out.json"
    payload = {"ticker": "000001", "score": 0.5, "nested": {"k": [1, 2, 3]}}
    _atomic_write_json(target, payload)

    assert json.loads(target.read_text(encoding="utf-8")) == payload
