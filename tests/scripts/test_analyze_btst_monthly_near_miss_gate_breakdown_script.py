from __future__ import annotations

import json
from pathlib import Path

import scripts.analyze_btst_monthly_near_miss_gate_breakdown as nm


def test_analyze_btst_monthly_near_miss_gate_breakdown_counts_gates(tmp_path: Path) -> None:
    reports_dir = tmp_path / "data" / "reports"
    reports_dir.mkdir(parents=True)

    plan_dir = reports_dir / "paper_trading_20260506_20260506_live_test_short_trade_only_20260506_plan"
    plan_dir.mkdir(parents=True)

    (plan_dir / "btst_next_day_trade_brief_latest.json").write_text(
        json.dumps(
            {
                "trade_date": "20260506",
                "near_miss_entries": [
                    {
                        "ticker": "000001",
                        "score_target": 0.49,
                        "gate_status": {"execution": "proxy_only", "committee": "shadow_only", "score": "near_miss"},
                        "execution_blocked": False,
                        "execution_blocked_flags": ["p2_regime_gate"],
                        "historical_prior": {
                            "prior_evidence_count": 30,
                            "effective_next_close_positive_rate": 0.9,
                            "effective_next_high_hit_rate_at_threshold": 0.8,
                            "btst_regime_gate": "halt",
                        },
                    },
                    {
                        "ticker": "000002",
                        "score_target": 0.2,
                        "gate_status": {"execution": "pass", "committee": "pass", "score": "near_miss"},
                        "execution_blocked": True,
                        "execution_blocked_flags": [],
                        "historical_prior": {"prior_evidence_count": 1, "effective_next_close_positive_rate": 0.4},
                    },
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = nm.analyze_btst_monthly_near_miss_gate_breakdown(month="202605", reports_dir=reports_dir)
    overall = analysis["overall"]

    assert overall["near_miss_row_count"] == 2
    assert overall["by_gate_execution"]["proxy_only"] == 1
    assert overall["by_gate_committee"]["shadow_only"] == 1
    assert overall["by_execution_blocked_flag"]["p2_regime_gate"] == 1

    # High potential should include only the first row (prior_evidence_count=30 and close_pos_rate=0.9)
    assert overall["high_potential_row_count"] == 1
    assert overall["high_potential_by_gate_committee"]["shadow_only"] == 1

    md = nm.render_btst_monthly_near_miss_gate_breakdown_markdown(analysis)
    assert "BTST Monthly Near-miss Gate Breakdown 202605" in md
    assert "Gate: committee" in md
