from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import scripts.analyze_btst_5d_15pct_trend_top20_gate_diagnostics as gate_script


_TICKER_OUTCOMES = {
    # ticker: (hit_15pct, max_future_high_return, next_open_return)
    "TOP_STRONG": (True, 0.20, 0.01),
    "TOP_SELECTED": (False, 0.07, 0.02),
    "LOW_TREND": (False, 0.04, 0.01),
    "VOLUME_ONLY": (True, 0.18, 0.01),
}


def _build_price_bars(trade_close: float, next_open_return: float, max_future_high_return: float) -> list[dict[str, float | str]]:
    """Build 5-day price bars that produce the desired outcome metrics."""
    next_open = round(trade_close * (1.0 + next_open_return), 2)
    max_high = round(trade_close * (1.0 + max_future_high_return), 2)
    bars = [
        {"date": "2026-03-24", "open": round(trade_close * 0.99, 2), "high": round(trade_close * 1.01, 2), "low": round(trade_close * 0.98, 2), "close": trade_close},
        {"date": "2026-03-25", "open": next_open, "high": round(trade_close * 1.05, 2), "low": trade_close, "close": round(trade_close * 1.03, 2)},
        {"date": "2026-03-26", "open": round(trade_close * 1.03, 2), "high": round(trade_close * 1.06, 2), "low": round(trade_close * 1.02, 2), "close": round(trade_close * 1.04, 2)},
        {"date": "2026-03-27", "open": round(trade_close * 1.04, 2), "high": max_high, "low": round(trade_close * 1.03, 2), "close": round(max_high * 0.96, 2)},
        {"date": "2026-03-28", "open": round(max_high * 0.96, 2), "high": round(max_high * 0.98, 2), "low": round(trade_close * 1.05, 2), "close": round(trade_close * 1.06, 2)},
    ]
    return bars


def _write_snapshot(snapshot_dir: Path) -> None:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.joinpath("selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "20260324",
                "selection_targets": {
                    "TOP_STRONG": {
                        "candidate_source": "catalyst_theme",
                        "short_trade": {
                            "decision": "near_miss",
                            "explainability_payload": {
                                "trend_acceleration": 0.92,
                                "close_strength": 0.88,
                                "volume_expansion_quality": 0.40,
                                "breakout_freshness": 0.30,
                                "trend_continuation": 0.86,
                            },
                        },
                    },
                    "TOP_SELECTED": {
                        "candidate_source": "catalyst_theme",
                        "short_trade": {
                            "decision": "selected",
                            "explainability_payload": {
                                "trend_acceleration": 0.88,
                                "close_strength": 0.82,
                                "volume_expansion_quality": 0.42,
                                "breakout_freshness": 0.30,
                                "trend_continuation": 0.84,
                            },
                        },
                    },
                    "LOW_TREND": {
                        "candidate_source": "short_trade_boundary",
                        "short_trade": {
                            "decision": "selected",
                            "explainability_payload": {
                                "trend_acceleration": 0.55,
                                "close_strength": 0.62,
                                "volume_expansion_quality": 0.40,
                                "breakout_freshness": 0.30,
                                "trend_continuation": 0.60,
                            },
                        },
                    },
                    "VOLUME_ONLY": {
                        "candidate_source": "short_trade_boundary",
                        "short_trade": {
                            "decision": "selected",
                            "explainability_payload": {
                                "trend_acceleration": 0.35,
                                "close_strength": 0.65,
                                "volume_expansion_quality": 0.80,
                                "breakout_freshness": 0.20,
                            },
                        },
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_local_prices(report_dir: Path) -> None:
    """Write local price data snapshots so subprocess tests get closed_cycle outcomes."""
    for ticker, (hit, max_return, next_open_return) in _TICKER_OUTCOMES.items():
        prices_dir = report_dir / "data_snapshots" / ticker / "2026-03-24"
        prices_dir.mkdir(parents=True, exist_ok=True)
        bars = _build_price_bars(100.0, next_open_return, max_return)
        prices_dir.joinpath("prices.json").write_text(
            json.dumps(bars, ensure_ascii=False),
            encoding="utf-8",
        )


def test_trend_top20_gate_diagnostics_builds_pre_registered_gates(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_gate_diag"
    _write_snapshot(report_dir / "selection_artifacts" / "2026-03-24")

    def _fake_extract(ticker: str, trade_date: str, price_cache: dict[tuple[str, str], object]) -> dict[str, object]:
        outcomes = {
            "TOP_STRONG": (True, 0.20, 0.01),
            "TOP_SELECTED": (False, 0.07, 0.02),
            "LOW_TREND": (False, 0.04, 0.01),
            "VOLUME_ONLY": (True, 0.18, 0.01),
        }
        hit, max_return, next_open_return = outcomes[ticker]
        return {
            "cycle_status": "closed_cycle",
            "future_high_hit_15pct_2_5d": hit,
            "max_future_high_return_2_5d": max_return,
            "next_open_return": next_open_return,
        }

    monkeypatch.setattr(gate_script, "_extract_btst_price_outcome", _fake_extract)

    diagnostics = gate_script.analyze_btst_5d_15pct_trend_top20_gate_diagnostics(
        reports_root,
        min_closed_cycle_count=1,
        top_fraction=0.50,
    )

    assert diagnostics["base_slice"]["slice_id"] == "trend_acceleration_top_50pct_gap_le_3pct"
    assert diagnostics["base_slice"]["closed_cycle_count"] == 2
    assert diagnostics["base_slice"]["hit_rate_15pct"] == 0.5
    assert diagnostics["frozen_out_event_prototype_counts"] == {"volume_quality_release": 1}

    close_gate = next(row for row in diagnostics["gate_board"] if row["gate_id"] == "close_strength_ge_0_85")
    assert close_gate["closed_cycle_count"] == 1
    assert close_gate["deduped_closed_cycle_count"] == 1
    assert close_gate["hit_rate_15pct"] == 1.0
    assert close_gate["deduped_hit_rate_15pct"] == 1.0
    assert close_gate["decision"] == "observe"

    selected_gate = next(row for row in diagnostics["gate_board"] if row["gate_id"] == "decision_selected_only")
    assert selected_gate["hit_rate_uplift_vs_base"] == -0.5
    assert selected_gate["decision"] == "downgrade"

    combo_gate = next(row for row in diagnostics["gate_board"] if row["gate_id"] == "catalyst_theme_non_selected")
    assert combo_gate["closed_cycle_count"] == 1
    assert combo_gate["deduped_closed_cycle_count"] == 1
    assert combo_gate["hit_rate_15pct"] == 1.0
    assert combo_gate["decision"] == "observe"

    assert diagnostics["gate_decision"]["next_step"] == "continue_gate_validation"


def test_trend_top20_gate_diagnostics_uses_deduped_metrics_for_upgrade_guardrail(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    for suffix in ("a", "b"):
        report_dir = reports_root / f"paper_trading_window_20260323_20260326_gate_diag_{suffix}"
        _write_snapshot(report_dir / "selection_artifacts" / "2026-03-24")

    def _fake_extract(ticker: str, trade_date: str, price_cache: dict[tuple[str, str], object]) -> dict[str, object]:
        outcomes = {
            "TOP_STRONG": (True, 0.20, 0.01),
            "TOP_SELECTED": (False, 0.07, 0.02),
            "LOW_TREND": (False, 0.04, 0.01),
            "VOLUME_ONLY": (True, 0.18, 0.01),
        }
        hit, max_return, next_open_return = outcomes[ticker]
        return {
            "cycle_status": "closed_cycle",
            "future_high_hit_15pct_2_5d": hit,
            "max_future_high_return_2_5d": max_return,
            "next_open_return": next_open_return,
        }

    monkeypatch.setattr(gate_script, "_extract_btst_price_outcome", _fake_extract)

    diagnostics = gate_script.analyze_btst_5d_15pct_trend_top20_gate_diagnostics(
        reports_root,
        min_closed_cycle_count=1,
        top_fraction=0.50,
    )

    combo_gate = next(row for row in diagnostics["gate_board"] if row["gate_id"] == "catalyst_theme_non_selected")
    assert combo_gate["closed_cycle_count"] == 2
    assert combo_gate["deduped_closed_cycle_count"] == 1
    assert combo_gate["hit_rate_15pct"] == 1.0
    assert combo_gate["deduped_hit_rate_15pct"] == 1.0
    assert combo_gate["decision"] == "observe"


def test_trend_top20_gate_diagnostics_script_writes_outputs(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_gate_diag"
    _write_snapshot(report_dir / "selection_artifacts" / "2026-03-24")
    _write_local_prices(report_dir)
    output_json = tmp_path / "gate.json"
    output_md = tmp_path / "gate.md"

    result = subprocess.run(
        [
            sys.executable,
            str(Path("scripts/analyze_btst_5d_15pct_trend_top20_gate_diagnostics.py").resolve()),
            "--reports-root",
            str(reports_root),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
            "--min-closed-cycle-count",
            "1",
            "--top-fraction",
            "0.50",
            "--local-price-only",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["base_slice"]["closed_cycle_count"] == 2
    assert "close_strength_ge_0_85" in output_md.read_text(encoding="utf-8")
