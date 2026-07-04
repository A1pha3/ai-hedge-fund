from __future__ import annotations

from src.targets.early_runner_runtime_adapter import (
    build_runtime_supplemental_entries,
    build_runtime_supplemental_entry,
    derive_entry_status,
    derive_failure_reason,
    resolve_gate_action,
    select_confirmed_entries,
)


def test_resolve_gate_action_and_entry_status_fail_closed_under_research_gate() -> None:
    """Research-only gates should prevent entry promotion even when scores look healthy."""
    gate_action = resolve_gate_action("shadow_only", tradeable_gates={"normal_trade"})
    entry_status = derive_entry_status(
        {
            "ticker": "300001",
            "next_open_return": 0.01,
            "gap_to_limit": 0.05,
            "confirm_score": 0.80,
        },
        gate_action=gate_action,
        max_open_gap=0.05,
        confirm_score_min=0.60,
    )

    assert gate_action == "research_only"
    assert entry_status == "research_only"


def test_build_runtime_supplemental_entry_preserves_theme_and_reason_codes() -> None:
    """Runtime adapter output should preserve audit fields needed by short-trade routing."""
    entry = build_runtime_supplemental_entry(
        {
            "ticker": "300383",
            "candidate_source": "catalyst_theme",
            "pre_score": 0.71,
            "confirm_score": 0.82,
            "preferred_entry_mode": "reconfirm_on_open",
            "hot_theme_board": "AI Agent",
            "theme_category": "application",
            "is_new_theme": True,
            "trend_acceleration": 0.66,
            "breakout_freshness": 0.58,
            "volume_expansion_quality": 0.61,
            "close_strength": 0.77,
            "sector_resonance": 0.62,
            "catalyst_freshness": 0.73,
            "theme_breadth_score": 0.81,
            "btst_regime_gate": "normal_trade",
            "gate_action": "tradeable",
        }
    )

    assert entry["ticker"] == "300383"
    assert entry["candidate_source"] == "early_runner_runtime_adapter"
    assert "theme_radar_pass" in entry["candidate_reason_codes"]
    assert "intraday_confirm_pass" in entry["candidate_reason_codes"]
    assert entry["theme_name"] == "AI Agent"
    assert entry["is_new_theme"] is True
    assert entry["short_trade_boundary_metrics"]["gate_status"]["gate_action"] == "tradeable"


def test_build_runtime_supplemental_entries_respects_tradeable_gate_and_confirmed_rows() -> None:
    """Only confirmed rows from a tradeable board should become runtime supplemental entries."""
    analysis = {
        "daily_boards": [
            {
                "trade_date": "2026-03-30",
                "gate_action": "tradeable",
                "confirmed_entries": [{"ticker": "300383", "confirm_score": 0.82, "pre_score": 0.71, "hot_theme_board": "AI Agent"}],
            },
            {
                "trade_date": "2026-03-31",
                "gate_action": "research_only",
                "confirmed_entries": [{"ticker": "002015", "confirm_score": 0.76, "pre_score": 0.64}],
            },
        ]
    }

    tradable_entries = build_runtime_supplemental_entries(analysis, trade_date="2026-03-30", require_tradeable_gate=True)
    blocked_entries = build_runtime_supplemental_entries(analysis, trade_date="2026-03-31", require_tradeable_gate=True)

    assert [entry["ticker"] for entry in tradable_entries] == ["300383"]
    assert blocked_entries == []


def test_select_confirmed_entries_and_failure_reason_cover_primary_contract_labels() -> None:
    """Confirmed selection and failure labels should remain deterministic for postmortems."""
    rows = [
        {"ticker": "300001", "entry_status": "filled", "confirm_score": 0.75},
        {"ticker": "300002", "entry_status": "not_confirmed", "confirm_score": 0.54},
    ]

    confirmed = select_confirmed_entries(rows, confirm_score_min=0.60)
    failure_reason = derive_failure_reason(
        {
            "ret_5d": 0.08,
            "ret_10d": 0.12,
            "next_high_return": 0.05,
            "next_close_return": -0.01,
            "volume_expansion_quality": 0.40,
            "next_open_to_close_return": 0.01,
            "sector_resonance": 0.50,
            "btst_regime_gate": "normal_trade",
        },
        entry_status="not_confirmed",
    )

    assert [row["ticker"] for row in confirmed] == ["300001"]
    assert failure_reason == "fake_breakout"
