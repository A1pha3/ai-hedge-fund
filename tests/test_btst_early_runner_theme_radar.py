from __future__ import annotations

from src.targets.early_runner_theme_radar import (
    build_industry_radar_summary,
    build_theme_radar_context_by_ticker,
    build_theme_radar_summary,
)


def test_build_theme_radar_summary_does_not_mark_single_isolated_leader_as_hot_board() -> None:
    """A single isolated leader should not be promoted into a hot theme board."""
    summary = build_theme_radar_summary(
        trade_date="2026-03-30",
        catalyst_theme_candidates=[
            {
                "ticker": "300001",
                "theme_name": "AI Agent",
                "theme_category": "application",
                "candidate_source": "catalyst_theme",
            }
        ],
        catalyst_theme_shadow_candidates=[],
    )

    assert summary["theme_board_count"] == 1
    assert summary["top_active_themes"] == ["AI Agent"]
    assert summary["hot_theme_board"] == []
    board = summary["theme_boards"][0]
    assert board["theme_leader_count"] == 1
    assert board["theme_midfield_candidates"] == []
    assert board["is_hot_theme_board"] is False


def test_build_theme_radar_context_by_ticker_promotes_multi_name_theme_breadth() -> None:
    """Multi-name breadth should surface a hot board and enrich per-ticker radar context."""
    rows = [
        {"ticker": "300001", "theme_name": "AI Agent", "industry": "Computer", "bucket": "early_runner_first_entry"},
        {"ticker": "300002", "theme_name": "AI Agent", "industry": "Computer", "bucket": "early_runner_first_entry"},
        {"ticker": "300003", "theme_name": "AI Agent", "industry": "Computer", "bucket": "second_entry_reentry"},
    ]

    radar_context, theme_summary, industry_summary = build_theme_radar_context_by_ticker(
        trade_date="2026-03-30",
        rows=rows,
        catalyst_theme_candidates=[
            {"ticker": "300001", "theme_name": "AI Agent", "theme_category": "application", "candidate_source": "catalyst_theme"},
            {"ticker": "300002", "theme_name": "AI Agent", "theme_category": "application", "candidate_source": "catalyst_theme"},
        ],
        catalyst_theme_shadow_candidates=[
            {"ticker": "300003", "theme_name": "AI Agent", "theme_category": "application", "candidate_source": "catalyst_theme_shadow"}
        ],
    )

    assert theme_summary["hot_theme_board"] == ["AI Agent"]
    assert radar_context["300001"]["hot_theme_board"] == "AI Agent"
    assert radar_context["300001"]["theme_leader_count"] == 2
    assert radar_context["300001"]["theme_midfield_candidates"] == ["300003"]
    assert industry_summary["top_industries"] == ["Computer"]


def test_build_theme_radar_context_by_ticker_backfills_unknown_theme_labels_from_row_industry() -> None:
    """Missing catalyst-theme labels should fall back to row-level industry instead of staying unknown."""
    rows = [
        {"ticker": "300001", "industry": "Computer", "theme_name": "", "theme_category": "", "bucket": "full_report_confirmation"},
        {"ticker": "300002", "industry": "Computer", "theme_name": "", "theme_category": "", "bucket": "full_report_confirmation"},
    ]

    radar_context, theme_summary, _ = build_theme_radar_context_by_ticker(
        trade_date="2026-03-30",
        rows=rows,
        catalyst_theme_candidates=[
            {"ticker": "300001", "theme_name": "", "theme_category": "", "candidate_source": "catalyst_theme"},
            {"ticker": "300002", "theme_name": "", "theme_category": "", "candidate_source": "catalyst_theme"},
        ],
        catalyst_theme_shadow_candidates=[],
    )

    assert theme_summary["top_active_themes"] == ["Computer"]
    assert theme_summary["hot_theme_board"] == ["Computer"]
    assert radar_context["300001"]["theme_label"] == "Computer"
    assert radar_context["300001"]["hot_theme_board"] == "Computer"


def test_build_industry_radar_summary_prioritizes_first_entry_leaders() -> None:
    """Industry breadth should rank buckets with more first-entry leaders ahead of passive members."""
    summary = build_industry_radar_summary(
        [
            {"ticker": "300001", "industry": "Computer", "bucket": "early_runner_first_entry"},
            {"ticker": "300002", "industry": "Computer", "bucket": "early_runner_first_entry"},
            {"ticker": "300003", "industry": "Electronics", "bucket": "second_entry_reentry"},
        ],
        trade_date="2026-03-30",
    )

    assert summary["industry_board_count"] == 2
    assert summary["top_industries"][0] == "Computer"
    assert summary["industry_boards"][0]["leader_count"] == 2
