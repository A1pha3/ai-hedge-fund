from __future__ import annotations

from scripts.analyze_btst_carryover_peer_expansion import (
    analyze_btst_carryover_peer_expansion,
    render_btst_carryover_peer_expansion_markdown,
)


def test_analyze_btst_carryover_peer_expansion_separates_priority_queue_from_history_risk(tmp_path):
    harvest_path = tmp_path / "harvest.json"
    multiday_audit_path = tmp_path / "multiday_audit.json"
    harvest_path.write_text(
        """
{
  "ticker": "002001",
  "harvest_entries": [
    {
      "ticker": "300408",
      "harvest_status": "next_day_watch",
      "latest_trade_date": "2026-04-08",
      "latest_scope": "same_family_source",
      "latest_score_target": 0.3088,
      "occurrence_count": 1,
      "scope_counts": {"same_family_source": 1},
      "next_day_available_count": 1,
      "closed_cycle_count": 0
    },
    {
      "ticker": "301396",
      "harvest_status": "fresh_open_cycle",
      "latest_trade_date": "2026-04-09",
      "latest_scope": "same_family_source_score_catalyst",
      "latest_score_target": 0.4395,
      "occurrence_count": 2,
      "scope_counts": {"same_family_source_score_catalyst": 2},
      "next_day_available_count": 0,
      "closed_cycle_count": 0
    },
    {
      "ticker": "688498",
      "harvest_status": "fresh_open_cycle",
      "latest_trade_date": "2026-04-09",
      "latest_scope": "same_family_source_score_catalyst",
      "latest_score_target": 0.4341,
      "occurrence_count": 1,
      "scope_counts": {"same_family_source_score_catalyst": 1},
      "next_day_available_count": 0,
      "closed_cycle_count": 0
    }
  ]
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    multiday_audit_path.write_text(
        """
{
  "selected_ticker": "002001",
  "policy_checks": {
    "selected_path_t2_bias_only": true,
    "broad_family_only_multiday_unsupported": true
  },
  "supportive_cohort_rows": [
    {
      "trade_date": "2026-03-30",
      "ticker": "688498",
      "next_close_return": -0.0533,
      "t_plus_2_close_return": -0.0019,
      "cycle_status": "t_plus_4_closed",
      "peer_evidence_status": "broad_family_only"
    }
  ]
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_btst_carryover_peer_expansion(harvest_path, multiday_audit_path)
    markdown = render_btst_carryover_peer_expansion_markdown(analysis)

    assert analysis["focus_ticker"] == "300408"
    assert analysis["focus_status"] == "next_day_watch_priority"
    assert analysis["priority_expansion_tickers"] == ["300408", "301396"]
    assert analysis["watch_with_risk_tickers"] == ["688498"]
    assert analysis["entries"][2]["expansion_status"] == "open_cycle_with_history_risk"
    assert "688498" in analysis["recommendation"]
    assert "watch-with-risk" in analysis["recommendation"]
    assert "300408" in markdown


def test_analyze_btst_carryover_peer_expansion_threads_sorted_entries(monkeypatch, tmp_path):
    harvest = {
        "ticker": "002001",
        "harvest_entries": [
            {"ticker": "301396", "harvest_status": "fresh_open_cycle", "latest_trade_date": "2026-04-09", "latest_scope": "same_family_source_score_catalyst", "latest_score_target": 0.4395, "occurrence_count": 2, "scope_counts": {"same_family_source_score_catalyst": 2}, "next_day_available_count": 0, "closed_cycle_count": 0},
            {"ticker": "688498", "harvest_status": "fresh_open_cycle", "latest_trade_date": "2026-04-09", "latest_scope": "same_family_source_score_catalyst", "latest_score_target": 0.4341, "occurrence_count": 1, "scope_counts": {"same_family_source_score_catalyst": 1}, "next_day_available_count": 0, "closed_cycle_count": 0},
        ],
    }
    multiday = {
        "selected_ticker": "002001",
        "policy_checks": {"selected_path_t2_bias_only": True, "broad_family_only_multiday_unsupported": True},
    }

    def _fake_load_json(path):
        return harvest if str(path).endswith("harvest.json") else multiday

    monkeypatch.setattr("scripts.analyze_btst_carryover_peer_expansion._load_json", _fake_load_json)
    monkeypatch.setattr(
        "scripts.analyze_btst_carryover_peer_expansion._build_historical_concerns",
        lambda audit: {"688498": {"concern_tags": ["broad_family_only_history"], "trade_date": "2026-03-30", "cycle_status": "t_plus_4_closed", "next_close_return": -0.0533, "t_plus_2_close_return": -0.0019}},
    )

    analysis = analyze_btst_carryover_peer_expansion(tmp_path / "harvest.json", tmp_path / "multiday.json")

    assert analysis["selected_ticker"] == "002001"
    assert analysis["peer_count"] == 2
    assert analysis["priority_expansion_tickers"] == ["301396"]
    assert analysis["watch_with_risk_tickers"] == ["688498"]
    assert [entry["ticker"] for entry in analysis["entries"]] == ["301396", "688498"]
