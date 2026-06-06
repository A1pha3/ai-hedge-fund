from __future__ import annotations

from scripts.analyze_btst_carryover_aligned_peer_harvest import (
    analyze_btst_carryover_aligned_peer_harvest,
    render_btst_carryover_aligned_peer_harvest_markdown,
)


def test_analyze_btst_carryover_aligned_peer_harvest_prioritizes_open_cycle_score_catalyst_peer(tmp_path):
    anchor_probe_path = tmp_path / "anchor_probe.json"
    anchor_probe_path.write_text(
        """
{
  "ticker": "002001",
  "probes": [
    {
      "same_family_source_rows": [
        {"trade_date": "2026-04-08", "ticker": "300408", "score_target": 0.3088, "next_high_return": 0.0156, "next_close_return": 0.0033, "t_plus_2_close_return": null},
        {"trade_date": "2026-04-09", "ticker": "001309", "score_target": 0.4482, "next_high_return": null, "next_close_return": null, "t_plus_2_close_return": null}
      ],
      "same_family_source_score_catalyst_rows": [
        {"trade_date": "2026-04-09", "ticker": "600989", "score_target": 0.3705, "next_high_return": null, "next_close_return": null, "t_plus_2_close_return": null}
      ],
      "same_source_score_rows": [
        {"trade_date": "2026-04-09", "ticker": "600989", "score_target": 0.3705, "next_high_return": null, "next_close_return": null, "t_plus_2_close_return": null}
      ]
    }
  ]
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_btst_carryover_aligned_peer_harvest(anchor_probe_path)
    markdown = render_btst_carryover_aligned_peer_harvest_markdown(analysis)

    assert analysis["focus_ticker"] == "300408"
    assert analysis["focus_status"] == "next_day_watch"
    assert analysis["status_counts"]["fresh_open_cycle"] == 2
    assert analysis["status_counts"]["next_day_watch"] == 1
    assert analysis["harvest_entries"][1]["latest_scope"] == "same_family_source_score_catalyst"
    assert "单票证据" in analysis["recommendation"]
    assert "300408" in markdown
