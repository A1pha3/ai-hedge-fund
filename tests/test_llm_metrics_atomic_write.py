"""R88 corrupt-summary CRASH vector: monitoring._write_summary 必须原子写,
crash 落在 open('w') truncate 之后会留下空/半截 LLM 指标汇总。
"""

from __future__ import annotations

import json
from pathlib import Path


def test_write_summary_atomic_crash_preserves_prior(tmp_path: Path, monkeypatch) -> None:
    import src.monitoring.llm_metrics as mod

    summary_path = tmp_path / "llm_metrics_summary.json"
    summary_path.write_text(json.dumps({"prior": True, "keep": "alive"}), encoding="utf-8")
    monkeypatch.setattr(mod, "_SUMMARY_PATH", summary_path)
    monkeypatch.setattr(mod, "_SUMMARY", {"session_id": "test", "totals": {"attempts": 0, "total_duration_ms": 0.0}, "buckets": {}})

    # 当前实现: with _SUMMARY_PATH.open('w') → 已 truncate; json.dump crash → 文件空
    from unittest.mock import patch

    with patch("src.monitoring.llm_metrics.json.dump", side_effect=RuntimeError("simulated crash")):
        try:
            mod._write_summary()
        except RuntimeError:
            pass

    raw = summary_path.read_text(encoding="utf-8")
    assert raw.strip(), "prior LLM 指标汇总 must not be truncated-empty after a crashed write — " "non-atomic open('w') truncates immediately (R88 corrupt-summary CRASH vector root cause)"
    json.loads(raw)  # must parse cleanly
