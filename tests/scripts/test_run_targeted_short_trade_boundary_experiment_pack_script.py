from __future__ import annotations

import json

from scripts.run_targeted_short_trade_boundary_experiment_pack import run_targeted_short_trade_boundary_experiment_pack


def test_run_targeted_short_trade_boundary_experiment_pack_builds_release_outcome_and_pack(tmp_path, monkeypatch):
    frontier_report = tmp_path / "short_trade_boundary_score_failures_frontier_latest.json"
    frontier_report.write_text(
        json.dumps(
            {
                "report_dir": "/tmp/example-report-dir",
                "minimal_near_miss_rows": [
                    {
                        "trade_date": "2026-03-31",
                        "ticker": "600522",
                        "baseline_score_target": 0.406,
                        "replayed_score_target": 0.4059,
                        "near_miss_threshold": 0.4,
                        "stale_weight": 0.12,
                        "extension_weight": 0.08,
                        "adjustment_cost": 0.06,
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_release(report_dir, *, targets, near_miss_threshold, stale_weight, extension_weight):
        assert report_dir == "/tmp/example-report-dir"
        assert targets == {("2026-03-31", "600522")}
        assert near_miss_threshold == 0.4
        assert stale_weight == 0.12
        assert extension_weight == 0.08
        return {
            "report_dir": report_dir,
            "targets": ["2026-03-31:600522"],
            "changed_case_count": 1,
            "changed_non_target_case_count": 0,
            "decision_transition_counts": {"rejected->near_miss": 1},
            "recommendation": "release-ok",
            "changed_cases": [
                {
                    "trade_date": "2026-03-31",
                    "ticker": "600522",
                    "before_decision": "rejected",
                    "after_decision": "near_miss",
                }
            ],
        }

    def fake_render_release(analysis):
        assert analysis["recommendation"] == "release-ok"
        return "release-md\n"

    def fake_outcome(release_report, *, next_high_hit_threshold):
        assert next_high_hit_threshold == 0.02
        release_payload = json.loads(open(release_report, encoding="utf-8").read())
        assert release_payload["targets"] == ["2026-03-31:600522"]
        return {
            "release_report": release_report,
            "report_dir": "/tmp/example-report-dir",
            "target_case_count": 1,
            "promoted_target_case_count": 1,
            "next_high_return_mean": 0.031,
            "next_close_return_mean": 0.014,
            "next_close_positive_rate": 1.0,
            "recommendation": "outcome-ok",
            "target_cases": [
                {
                    "trade_date": "2026-03-31",
                    "ticker": "600522",
                    "before_decision": "rejected",
                    "after_decision": "near_miss",
                    "release_verdict": "promoted_with_positive_close",
                }
            ],
        }

    def fake_render_outcome(analysis):
        assert analysis["recommendation"] == "outcome-ok"
        return "outcome-md\n"

    monkeypatch.setattr("scripts.run_targeted_short_trade_boundary_experiment_pack.analyze_targeted_short_trade_boundary_release", fake_release)
    monkeypatch.setattr("scripts.run_targeted_short_trade_boundary_experiment_pack.render_targeted_short_trade_boundary_release_markdown", fake_render_release)
    monkeypatch.setattr("scripts.run_targeted_short_trade_boundary_experiment_pack.analyze_targeted_release_outcomes", fake_outcome)
    monkeypatch.setattr("scripts.run_targeted_short_trade_boundary_experiment_pack.render_targeted_release_outcomes_markdown", fake_render_outcome)

    pack = run_targeted_short_trade_boundary_experiment_pack(
        frontier_report=frontier_report,
        output_dir=tmp_path,
        ticker="600522",
    )

    assert pack["ticker"] == "600522"
    assert pack["trade_date"] == "2026-03-31"
    assert pack["recommendation"] == "outcome-ok"
    assert sorted(pack["artifacts"].keys()) == ["outcome_json", "outcome_md", "pack_json", "pack_md", "release_json", "release_md"]
    assert (tmp_path / "targeted_short_trade_boundary_release_600522_20260331.json").exists()
    assert (tmp_path / "targeted_short_trade_boundary_release_outcomes_600522_20260331.md").read_text(encoding="utf-8") == "outcome-md\n"
    pack_payload = json.loads((tmp_path / "targeted_short_trade_boundary_experiment_pack_600522_20260331.json").read_text(encoding="utf-8"))
    assert pack_payload["frontier_case"]["adjustment_cost"] == 0.06
    assert pack_payload["recommendation"] == "outcome-ok"