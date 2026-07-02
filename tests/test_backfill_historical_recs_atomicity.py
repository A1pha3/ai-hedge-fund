"""R88 corrupt-report CRASH vector + c292 pipeline 锁复用:
backfill_one_date 写 auto_screening_{trade_date}.json 必须原子, 且整个 backfill
必须持 c292 pipeline 锁 (防与 --auto 并发写报告 / tracking_history)。

c293 _save_json_report 守了 --auto 的报告写, 但 backfill 脚本绕过它直接 write_text
(同族不同路径残留, R83/R122/R130 模式)。本测试锁住原子性 + 锁复用。
"""

from __future__ import annotations

import json
from pathlib import Path


def _patch_backfill_deps(monkeypatch, report_dir: Path, lock_path: Path, lock_acquired: list):
    """patch backfill_one_date 函数内 import 的依赖 (函数内 import → patch 源模块)。"""
    import src.screening.consecutive_recommendation as consec
    import src.main as main_mod
    import src.screening.recommendation_tracker as tracker

    monkeypatch.setattr(consec, "resolve_report_dir", lambda: report_dir)
    monkeypatch.setattr(main_mod, "compute_auto_screening_results",
                        lambda td, top_n=300: {"date": td, "recommendations": []})
    monkeypatch.setattr(tracker, "update_tracking_history", lambda **kw: 0)

    # patch c292 锁 helper (backfill 从 src.main import)
    real_lock = main_mod._try_acquire_pipeline_lock

    def _spy_lock(path):
        fd = real_lock(path)
        if fd is not None:
            lock_acquired.append(path)
        return fd

    monkeypatch.setattr(main_mod, "_try_acquire_pipeline_lock", _spy_lock)
    monkeypatch.setattr(main_mod, "_AUTO_PIPELINE_LOCK_PATH", lock_path)


def test_backfill_one_date_writes_report_atomically(tmp_path: Path, monkeypatch) -> None:
    from scripts import _backfill_historical_recs as mod

    _patch_backfill_deps(monkeypatch, tmp_path, tmp_path / ".lock", [])

    trade_date = "20260615"
    report_path = tmp_path / f"auto_screening_{trade_date}.json"
    report_path.write_text(json.dumps({"prior": True, "keep": "alive"}), encoding="utf-8")

    _orig = Path.write_text

    def crashing_write_text(self, data, *a, **kw):  # noqa: ANN001
        if self == report_path:
            open(self, "w").close()
            raise OSError("simulated mid-write crash on backfill report")
        return _orig(self, data, *a, **kw)

    monkeypatch.setattr(Path, "write_text", crashing_write_text)
    try:
        mod.backfill_one_date(trade_date, top_n=10)
    except OSError:
        pass

    raw = report_path.read_text(encoding="utf-8")
    assert raw.strip(), (
        "prior backfill report must not be truncated-empty after a crashed write — "
        "non-atomic write_text truncates on open (R88 corrupt-report CRASH vector, "
        "backfill 路径绕过 c293 _save_json_report 的同族残留)"
    )
    json.loads(raw)


def test_backfill_one_date_acquires_pipeline_lock(tmp_path: Path, monkeypatch) -> None:
    from scripts import _backfill_historical_recs as mod

    lock_path = tmp_path / ".auto_pipeline.lock"
    lock_acquired: list[Path] = []
    _patch_backfill_deps(monkeypatch, tmp_path, lock_path, lock_acquired)

    mod.backfill_one_date("20260615", top_n=10)
    assert len(lock_acquired) == 1, "backfill_one_date 必须获取 c292 pipeline 锁"
    assert lock_acquired[0] == lock_path
