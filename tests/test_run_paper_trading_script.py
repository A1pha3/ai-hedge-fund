from __future__ import annotations

import os
from types import SimpleNamespace
from pathlib import Path

import scripts.run_paper_trading as run_paper_trading_script


def test_resolve_selected_analysts_defaults_to_none() -> None:
    assert run_paper_trading_script._resolve_selected_analysts(None, False) is None


def test_resolve_selected_analysts_honors_explicit_subset() -> None:
    assert run_paper_trading_script._resolve_selected_analysts("technical_analyst,fundamentals_analyst", False) == [
        "technical_analyst",
        "fundamentals_analyst",
    ]


def test_resolve_selected_analysts_all_uses_ordered_registry() -> None:
    analysts = run_paper_trading_script._resolve_selected_analysts(None, True)

    assert analysts is not None
    assert analysts[0] == "aswath_damodaran"
    assert "technical_analyst" in analysts


def test_resolve_short_trade_target_overrides_decodes_json_object() -> None:
    assert run_paper_trading_script._resolve_short_trade_target_overrides('{"select_threshold": 0.52, "near_miss_threshold": 0.44}') == {
        "select_threshold": 0.52,
        "near_miss_threshold": 0.44,
    }


def test_resolve_runtime_inputs_uses_btst_precision_v2_default_profile(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        run_paper_trading_script,
        "_derive_shadow_focus_tickers_from_reports",
        lambda _reports_root: {
            "all": [],
            "layer_a_liquidity_corridor": [],
            "post_gate_liquidity_competition": [],
            "release_priority_layer_a_liquidity_corridor": [],
            "release_priority_post_gate_liquidity_competition": [],
            "visibility_gap_all": [],
            "visibility_gap_layer_a_liquidity_corridor": [],
            "visibility_gap_post_gate_liquidity_competition": [],
        },
    )
    args = SimpleNamespace(
        start_date="2026-03-23",
        end_date="2026-03-26",
        tickers="",
        analysts=None,
        analysts_all=False,
        fast_analysts=None,
        short_trade_target_profile=None,
        short_trade_target_overrides=None,
        output_dir=str(tmp_path / "paper"),
    )

    runtime_inputs = run_paper_trading_script._resolve_paper_trading_runtime_inputs(args)

    assert runtime_inputs["short_trade_target_profile"] == run_paper_trading_script.DEFAULT_SHORT_TRADE_TARGET_PROFILE


def test_derive_shadow_focus_tickers_from_reports_picks_continuation_followup(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    (reports_root / "btst_tplus2_candidate_dossier_300720_latest.json").write_text(
        """
        {
          "candidate_ticker": "300720",
          "governance_followup": {
            "priority_handoff": "layer_a_liquidity_corridor",
            "latest_followup_decision": "near_miss",
            "downstream_followup_status": "continuation_confirm_then_review"
          },
          "current_plan_visibility_summary": {
            "current_plan_visibility_gap_trade_date_count": 0
          },
          "governance_recent_followup_rows": [
            {
              "ticker": "300720",
              "decision": "near_miss",
              "candidate_pool_lane": "post_gate_liquidity_competition"
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )
    (reports_root / "btst_tplus2_candidate_dossier_003036_latest.json").write_text(
        """
        {
          "candidate_ticker": "003036",
          "governance_followup": {
            "priority_handoff": "layer_a_liquidity_corridor",
            "latest_followup_decision": "rejected",
            "downstream_followup_status": "shadow_profitability_diagnostics"
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    derived = run_paper_trading_script._derive_shadow_focus_tickers_from_reports(reports_root)

    assert derived == {
        "all": ["300720"],
        "layer_a_liquidity_corridor": ["300720"],
        "post_gate_liquidity_competition": ["300720"],
        "release_priority_layer_a_liquidity_corridor": [],
        "release_priority_post_gate_liquidity_competition": [],
        "visibility_gap_all": [],
        "visibility_gap_layer_a_liquidity_corridor": [],
        "visibility_gap_post_gate_liquidity_competition": [],
    }


def test_derive_shadow_focus_tickers_from_reports_keeps_selected_continuation_followup(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    (reports_root / "btst_tplus2_candidate_dossier_300720_latest.json").write_text(
        """
        {
          "candidate_ticker": "300720",
          "governance_followup": {
            "priority_handoff": "layer_a_liquidity_corridor",
            "latest_followup_decision": "selected",
            "downstream_followup_status": "continuation_only_confirm_then_review"
          },
          "current_plan_visibility_summary": {
            "current_plan_visibility_gap_trade_date_count": 2
          },
          "governance_recent_followup_rows": [
            {
              "ticker": "300720",
              "decision": "selected",
              "candidate_pool_lane": "post_gate_liquidity_competition"
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    derived = run_paper_trading_script._derive_shadow_focus_tickers_from_reports(reports_root)

    assert derived == {
        "all": ["300720"],
        "layer_a_liquidity_corridor": ["300720"],
        "post_gate_liquidity_competition": ["300720"],
        "release_priority_layer_a_liquidity_corridor": [],
        "release_priority_post_gate_liquidity_competition": [],
        "visibility_gap_all": ["300720"],
        "visibility_gap_layer_a_liquidity_corridor": ["300720"],
        "visibility_gap_post_gate_liquidity_competition": ["300720"],
    }


def test_derive_shadow_focus_tickers_from_reports_includes_high_signal_candidate_pool_recall_rebucket_focus(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    (reports_root / "btst_candidate_pool_recall_dossier_latest.json").write_text(
        """
        {
          "priority_ticker_dossiers": [
            {
              "ticker": "300720",
              "strict_btst_goal_case_count": 2,
              "closest_pre_truncation_gap": 797,
              "truncation_liquidity_profile": {
                "priority_handoff": "post_gate_liquidity_competition",
                "avg_amount_share_of_min_gate_mean": 6.9694
              }
            },
            {
              "ticker": "003036",
              "strict_btst_goal_case_count": 6,
              "closest_pre_truncation_gap": 2031,
              "truncation_liquidity_profile": {
                "priority_handoff": "layer_a_liquidity_corridor",
                "avg_amount_share_of_min_gate_mean": 3.5786
              }
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    derived = run_paper_trading_script._derive_shadow_focus_tickers_from_reports(reports_root)

    assert derived == {
        "all": ["300720"],
        "layer_a_liquidity_corridor": [],
        "post_gate_liquidity_competition": ["300720"],
        "release_priority_layer_a_liquidity_corridor": [],
        "release_priority_post_gate_liquidity_competition": [],
        "visibility_gap_all": [],
        "visibility_gap_layer_a_liquidity_corridor": [],
        "visibility_gap_post_gate_liquidity_competition": [],
    }


def test_derive_shadow_focus_tickers_from_reports_includes_high_signal_candidate_pool_recall_corridor_focus(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    (reports_root / "btst_candidate_pool_recall_dossier_latest.json").write_text(
        """
        {
          "priority_ticker_dossiers": [
            {
                "ticker": "301188",
                "strict_btst_goal_case_count": 2,
                "closest_pre_truncation_gap": null,
                "truncation_liquidity_profile": {
                  "priority_handoff": "layer_a_liquidity_corridor",
                  "avg_amount_share_of_min_gate_mean": 2.3434,
                  "avg_amount_share_of_cutoff_mean": 0.0709
                }
              }
            ]
          }
        """.strip(),
        encoding="utf-8",
    )

    derived = run_paper_trading_script._derive_shadow_focus_tickers_from_reports(reports_root)

    assert derived == {
        "all": ["301188"],
        "layer_a_liquidity_corridor": ["301188"],
        "post_gate_liquidity_competition": [],
        "release_priority_layer_a_liquidity_corridor": [],
        "release_priority_post_gate_liquidity_competition": [],
        "visibility_gap_all": [],
        "visibility_gap_layer_a_liquidity_corridor": [],
        "visibility_gap_post_gate_liquidity_competition": [],
    }


def test_derive_shadow_focus_tickers_from_reports_excludes_thicker_low_gate_corridor_tail(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    (reports_root / "btst_candidate_pool_recall_dossier_latest.json").write_text(
        """
        {
          "priority_ticker_dossiers": [
            {
              "ticker": "688796",
              "strict_btst_goal_case_count": 7,
              "closest_pre_truncation_gap": 1187,
              "truncation_liquidity_profile": {
                "priority_handoff": "layer_a_liquidity_corridor",
                "avg_amount_share_of_min_gate_mean": 2.6142,
                "avg_amount_share_of_cutoff_mean": 0.0789
              }
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    derived = run_paper_trading_script._derive_shadow_focus_tickers_from_reports(reports_root)

    assert derived == {
        "all": [],
        "layer_a_liquidity_corridor": [],
        "post_gate_liquidity_competition": [],
        "release_priority_layer_a_liquidity_corridor": [],
        "release_priority_post_gate_liquidity_competition": [],
        "visibility_gap_all": [],
        "visibility_gap_layer_a_liquidity_corridor": [],
        "visibility_gap_post_gate_liquidity_competition": [],
    }


def test_derive_shadow_focus_tickers_from_reports_includes_near_threshold_corridor_focus(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    (reports_root / "btst_candidate_pool_recall_dossier_latest.json").write_text(
        """
        {
          "priority_ticker_dossiers": [
            {
              "ticker": "300683",
              "strict_btst_goal_case_count": 7,
              "closest_pre_truncation_gap": 1599,
              "truncation_liquidity_profile": {
                "priority_handoff": "layer_a_liquidity_corridor",
                "avg_amount_share_of_min_gate_mean": 5.0386,
                "avg_amount_share_of_cutoff_mean": 0.1519
              }
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    derived = run_paper_trading_script._derive_shadow_focus_tickers_from_reports(reports_root)

    assert derived == {
        "all": ["300683"],
        "layer_a_liquidity_corridor": ["300683"],
        "post_gate_liquidity_competition": [],
        "release_priority_layer_a_liquidity_corridor": [],
        "release_priority_post_gate_liquidity_competition": [],
        "visibility_gap_all": [],
        "visibility_gap_layer_a_liquidity_corridor": [],
        "visibility_gap_post_gate_liquidity_competition": [],
    }


def test_derive_shadow_focus_tickers_from_reports_skips_negative_recent_followup_history(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    (reports_root / "btst_tplus2_candidate_dossier_300720_latest.json").write_text(
        """
        {
          "candidate_ticker": "300720",
          "governance_followup": {
            "priority_handoff": "layer_a_liquidity_corridor",
            "latest_followup_decision": "selected",
            "downstream_followup_status": "continuation_only_confirm_then_review",
            "latest_followup_historical_next_close_positive_rate": 0.0
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    derived = run_paper_trading_script._derive_shadow_focus_tickers_from_reports(reports_root)

    assert derived == {
        "all": [],
        "layer_a_liquidity_corridor": [],
        "post_gate_liquidity_competition": [],
        "release_priority_layer_a_liquidity_corridor": [],
        "release_priority_post_gate_liquidity_competition": [],
        "visibility_gap_all": [],
        "visibility_gap_layer_a_liquidity_corridor": [],
        "visibility_gap_post_gate_liquidity_competition": [],
    }


def test_derive_shadow_focus_tickers_from_reports_recall_addition_respects_negative_recent_followup_history(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    (reports_root / "btst_tplus2_candidate_dossier_300720_latest.json").write_text(
        """
        {
          "candidate_ticker": "300720",
          "governance_followup": {
            "priority_handoff": "layer_a_liquidity_corridor",
            "latest_followup_decision": "selected",
            "downstream_followup_status": "continuation_only_confirm_then_review",
            "latest_followup_historical_next_close_positive_rate": 0.0
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    (reports_root / "btst_candidate_pool_recall_dossier_latest.json").write_text(
        """
        {
          "priority_ticker_dossiers": [
            {
              "ticker": "300720",
              "strict_btst_goal_case_count": 2,
              "closest_pre_truncation_gap": 797,
              "truncation_liquidity_profile": {
                "priority_handoff": "post_gate_liquidity_competition",
                "avg_amount_share_of_min_gate_mean": 6.9694
              }
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    derived = run_paper_trading_script._derive_shadow_focus_tickers_from_reports(reports_root)

    assert derived == {
        "all": [],
        "layer_a_liquidity_corridor": [],
        "post_gate_liquidity_competition": [],
        "release_priority_layer_a_liquidity_corridor": [],
        "release_priority_post_gate_liquidity_competition": [],
        "visibility_gap_all": [],
        "visibility_gap_layer_a_liquidity_corridor": [],
        "visibility_gap_post_gate_liquidity_competition": [],
    }


def test_derive_shadow_focus_tickers_from_reports_corridor_recall_addition_respects_negative_recent_followup_history(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    (reports_root / "btst_tplus2_candidate_dossier_301188_latest.json").write_text(
        """
        {
          "candidate_ticker": "301188",
          "governance_followup": {
            "priority_handoff": "layer_a_liquidity_corridor",
            "latest_followup_decision": "selected",
            "downstream_followup_status": "continuation_only_confirm_then_review",
            "latest_followup_historical_next_close_positive_rate": 0.0
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    (reports_root / "btst_candidate_pool_recall_dossier_latest.json").write_text(
        """
        {
          "priority_ticker_dossiers": [
            {
              "ticker": "301188",
              "strict_btst_goal_case_count": 2,
              "closest_pre_truncation_gap": null,
              "truncation_liquidity_profile": {
                "priority_handoff": "layer_a_liquidity_corridor",
                "avg_amount_share_of_min_gate_mean": 2.3434,
                "avg_amount_share_of_cutoff_mean": 0.0875
              }
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    derived = run_paper_trading_script._derive_shadow_focus_tickers_from_reports(reports_root)

    assert derived == {
        "all": [],
        "layer_a_liquidity_corridor": [],
        "post_gate_liquidity_competition": [],
        "release_priority_layer_a_liquidity_corridor": [],
        "release_priority_post_gate_liquidity_competition": [],
        "visibility_gap_all": [],
        "visibility_gap_layer_a_liquidity_corridor": [],
        "visibility_gap_post_gate_liquidity_competition": [],
    }


def test_derive_shadow_focus_tickers_from_reports_includes_manifest_corridor_shadow_pack_ready_tickers(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    (reports_root / "report_manifest_latest.json").write_text(
        """
        {
          "candidate_pool_corridor_shadow_pack_status": "ready_for_primary_shadow_replay",
          "candidate_pool_corridor_shadow_pack_summary": {
            "shadow_status": "ready_for_primary_shadow_replay",
            "primary_shadow_replay": "300683",
            "parallel_watch_tickers": ["301188"]
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    derived = run_paper_trading_script._derive_shadow_focus_tickers_from_reports(reports_root)

    assert derived == {
        "all": ["300683", "301188"],
        "layer_a_liquidity_corridor": ["300683", "301188"],
        "post_gate_liquidity_competition": [],
        "release_priority_layer_a_liquidity_corridor": ["300683", "301188"],
        "release_priority_post_gate_liquidity_competition": [],
        "visibility_gap_all": [],
        "visibility_gap_layer_a_liquidity_corridor": [],
        "visibility_gap_post_gate_liquidity_competition": [],
    }


def test_derive_shadow_focus_tickers_from_reports_manifest_corridor_shadow_pack_respects_negative_followup_history(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    (reports_root / "report_manifest_latest.json").write_text(
        """
        {
          "candidate_pool_corridor_shadow_pack_status": "ready_for_primary_shadow_replay",
          "candidate_pool_corridor_shadow_pack_summary": {
            "shadow_status": "ready_for_primary_shadow_replay",
            "primary_shadow_replay": {"ticker": "300683"},
            "parallel_watch_tickers": ["301188"]
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    (reports_root / "btst_tplus2_candidate_dossier_301188_latest.json").write_text(
        """
        {
          "candidate_ticker": "301188",
          "governance_followup": {
            "priority_handoff": "layer_a_liquidity_corridor",
            "latest_followup_decision": "selected",
            "downstream_followup_status": "continuation_only_confirm_then_review",
            "latest_followup_historical_next_close_positive_rate": 0.0
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    derived = run_paper_trading_script._derive_shadow_focus_tickers_from_reports(reports_root)

    assert derived == {
        "all": ["300683"],
        "layer_a_liquidity_corridor": ["300683"],
        "post_gate_liquidity_competition": [],
        "release_priority_layer_a_liquidity_corridor": ["300683"],
        "release_priority_post_gate_liquidity_competition": [],
        "visibility_gap_all": [],
        "visibility_gap_layer_a_liquidity_corridor": [],
        "visibility_gap_post_gate_liquidity_competition": [],
    }


def test_derive_shadow_focus_tickers_from_reports_manifest_excludes_low_gate_tail_tickers(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    (reports_root / "btst_tplus2_candidate_dossier_688796_latest.json").write_text(
        """
        {
          "candidate_ticker": "688796",
          "governance_followup": {
            "priority_handoff": "layer_a_liquidity_corridor",
            "latest_followup_decision": "near_miss",
            "downstream_followup_status": "continuation_confirm_then_review"
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    (reports_root / "report_manifest_latest.json").write_text(
        """
        {
          "candidate_pool_corridor_shadow_pack_status": "ready_for_primary_shadow_replay",
          "candidate_pool_corridor_shadow_pack_summary": {
            "shadow_status": "ready_for_primary_shadow_replay",
            "primary_shadow_replay": "300683",
            "parallel_watch_tickers": ["688796"],
            "excluded_low_gate_tail_tickers": ["688796"]
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    derived = run_paper_trading_script._derive_shadow_focus_tickers_from_reports(reports_root)

    assert derived == {
        "all": ["300683"],
        "layer_a_liquidity_corridor": ["300683"],
        "post_gate_liquidity_competition": [],
        "release_priority_layer_a_liquidity_corridor": ["300683"],
        "release_priority_post_gate_liquidity_competition": [],
        "visibility_gap_all": [],
        "visibility_gap_layer_a_liquidity_corridor": [],
        "visibility_gap_post_gate_liquidity_competition": [],
    }


def test_main_passes_selected_analysts_and_concurrency_limit(monkeypatch, capsys) -> None:
    captured: dict = {}

    monkeypatch.setattr(
        run_paper_trading_script,
        "parse_args",
        lambda: SimpleNamespace(
            start_date="2026-03-23",
            end_date="2026-03-26",
            tickers="",
            initial_capital=100000.0,
            model_name=None,
            model_provider=None,
            selection_target="research_only",
            output_dir="data/reports/test_paper_trading",
            frozen_plan_source=None,
            cache_benchmark=False,
            cache_benchmark_ticker=None,
            cache_benchmark_clear_first=False,
            analysts="technical_analyst,fundamentals_analyst",
            fast_analysts="technical_analyst",
            short_trade_target_profile="aggressive",
            short_trade_target_overrides='{"select_threshold": 0.52, "near_miss_threshold": 0.44}',
            analysts_all=False,
            analyst_concurrency_limit=1,
            disable_data_snapshots=True,
            candidate_pool_shadow_focus_tickers=None,
            candidate_pool_shadow_corridor_focus_tickers=None,
            candidate_pool_shadow_rebucket_focus_tickers=None,
            upstream_shadow_release_liquidity_corridor_score_min=None,
            upstream_shadow_release_post_gate_rebucket_score_min=None,
        ),
    )
    monkeypatch.setattr(run_paper_trading_script, "_resolve_model_route", lambda model_name, model_provider: ("test-model", "test-provider"))
    monkeypatch.setattr(
        run_paper_trading_script,
        "_derive_shadow_focus_tickers_from_reports",
        lambda reports_root: {
            "all": ["300720"],
            "layer_a_liquidity_corridor": ["300720"],
            "post_gate_liquidity_competition": ["300720"],
            "release_priority_layer_a_liquidity_corridor": ["300720"],
            "release_priority_post_gate_liquidity_competition": [],
            "visibility_gap_all": ["300720"],
            "visibility_gap_layer_a_liquidity_corridor": ["300720"],
            "visibility_gap_post_gate_liquidity_competition": ["300720"],
        },
    )

    def _fake_run_paper_trading_session(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            output_dir="data/reports/test_paper_trading",
            daily_events_path="data/reports/test_paper_trading/daily_events.jsonl",
            timing_log_path="data/reports/test_paper_trading/pipeline_timings.jsonl",
            summary_path="data/reports/test_paper_trading/session_summary.json",
        )

    monkeypatch.setattr(run_paper_trading_script, "_run_paper_trading_session", _fake_run_paper_trading_session)
    monkeypatch.delenv("ANALYST_CONCURRENCY_LIMIT", raising=False)

    run_paper_trading_script.main()

    assert captured["selected_analysts"] == ["technical_analyst", "fundamentals_analyst"]
    assert captured["fast_selected_analysts"] == ["technical_analyst"]
    assert captured["short_trade_target_profile_name"] == "aggressive"
    assert captured["short_trade_target_profile_overrides"] == {"select_threshold": 0.52, "near_miss_threshold": 0.44}
    assert captured["selection_target"] == "research_only"
    assert captured["model_name"] == "test-model"
    assert captured["model_provider"] == "test-provider"
    assert captured["output_dir"].name == "test_paper_trading"
    assert captured["disable_data_snapshots"] is True
    assert os.getenv("ANALYST_CONCURRENCY_LIMIT") == "1"
    assert os.getenv("DATA_SNAPSHOT_ENABLED") == "false"
    assert os.getenv("CANDIDATE_POOL_SHADOW_FOCUS_TICKERS") == "300720"
    assert os.getenv("CANDIDATE_POOL_SHADOW_FOCUS_LIQUIDITY_CORRIDOR_TICKERS") == "300720"
    assert os.getenv("CANDIDATE_POOL_SHADOW_FOCUS_REBUCKET_TICKERS") == "300720"
    assert os.getenv("DAILY_PIPELINE_UPSTREAM_SHADOW_RELEASE_PRIORITY_LIQUIDITY_CORRIDOR_TICKERS") == "300720"
    assert os.getenv("CANDIDATE_POOL_SHADOW_VISIBILITY_GAP_TICKERS") == "300720"
    assert os.getenv("CANDIDATE_POOL_SHADOW_VISIBILITY_GAP_LIQUIDITY_CORRIDOR_TICKERS") == "300720"
    assert os.getenv("CANDIDATE_POOL_SHADOW_VISIBILITY_GAP_REBUCKET_TICKERS") == "300720"

    stdout = capsys.readouterr().out
    assert "paper_trading_selected_analysts=technical_analyst,fundamentals_analyst" in stdout
    assert "paper_trading_fast_selected_analysts=technical_analyst" in stdout
    assert "paper_trading_short_trade_target_profile=aggressive" in stdout
    assert 'paper_trading_short_trade_target_overrides={"near_miss_threshold": 0.44, "select_threshold": 0.52}' in stdout
    assert (
        'paper_trading_auto_shadow_focus={"all": ["300720"], "layer_a_liquidity_corridor": ["300720"], '
        '"post_gate_liquidity_competition": ["300720"], "release_priority_layer_a_liquidity_corridor": ["300720"], '
        '"release_priority_post_gate_liquidity_competition": [], "visibility_gap_all": ["300720"], '
        '"visibility_gap_layer_a_liquidity_corridor": ["300720"], "visibility_gap_post_gate_liquidity_competition": ["300720"]}'
    ) in stdout
    assert "paper_trading_shadow_focus_tickers=300720" in stdout
    assert "paper_trading_shadow_corridor_focus_tickers=300720" in stdout
    assert "paper_trading_shadow_rebucket_focus_tickers=300720" in stdout
    assert "paper_trading_shadow_release_priority_corridor_tickers=300720" in stdout
    assert "paper_trading_shadow_visibility_gap_tickers=300720" in stdout
    assert "paper_trading_shadow_visibility_gap_corridor_tickers=300720" in stdout
    assert "paper_trading_shadow_visibility_gap_rebucket_tickers=300720" in stdout
    assert "paper_trading_analyst_concurrency_limit=1" in stdout
    assert "paper_trading_data_snapshots=disabled" in stdout
