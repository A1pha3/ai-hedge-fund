from __future__ import annotations

from scripts.analyze_btst_carryover_peer_quality_review import (
    analyze_btst_carryover_peer_quality_review,
    render_btst_carryover_peer_quality_review_markdown,
)


def test_analyze_btst_carryover_peer_quality_review_flags_missing_strong_peer(tmp_path):
    anchor_probe_path = tmp_path / "anchor_probe.json"
    anchor_probe_path.write_text(
        """
{
  "ticker": "002001",
  "probes": [
    {
      "same_family_source_rows": [
        {"trade_date": "2026-04-08", "ticker": "300408", "score_target": 0.3088, "next_high_return": 0.0156, "next_close_return": 0.0033, "t_plus_2_close_return": null, "scope": "same_family_source"},
        {"trade_date": "2026-04-09", "ticker": "600989", "score_target": 0.3705, "next_high_return": null, "next_close_return": null, "t_plus_2_close_return": null, "scope": "same_family_source"}
      ],
      "same_family_source_score_catalyst_rows": [
        {"trade_date": "2026-04-09", "ticker": "600989", "score_target": 0.3705, "next_high_return": null, "next_close_return": null, "t_plus_2_close_return": null, "scope": "same_family_source_score_catalyst"}
      ]
    }
  ]
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_btst_carryover_peer_quality_review(anchor_probe_path)
    markdown = render_btst_carryover_peer_quality_review_markdown(analysis)

    assert analysis["peer_count"] == 2
    assert analysis["peer_entries"][0]["ticker"] == "300408"
    assert analysis["peer_entries"][0]["surface_summary"]["next_high_hit_rate_at_threshold"] == 0.0
    assert "暂不支持扩容" in analysis["recommendation"]
    assert "300408" in markdown
