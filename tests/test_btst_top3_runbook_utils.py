from __future__ import annotations

import json
from pathlib import Path

from scripts import btst_top3_runbook_utils


def test_btst_top3_runbook_utils_build_top3_runbook_writes_expected_bundle(tmp_path, monkeypatch) -> None:
    output_path = tmp_path / "p2_top3_experiment_runbook.json"
    monkeypatch.setattr(btst_top3_runbook_utils, "P2_RUNBOOK_JSON_PATH", output_path)

    runbook = btst_top3_runbook_utils.build_top3_runbook()

    assert output_path.exists()
    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    assert persisted["generated_on"] == "2026-03-30"
    assert len(runbook["top_3_experiments"]) == 3
    assert runbook["top_3_experiments"][0]["execution_bundle"]["release_mode"] == "near_miss_promotion"
    assert runbook["top_3_experiments"][2]["execution_bundle"]["profile_overrides"]["near_miss_threshold"] == 0.42