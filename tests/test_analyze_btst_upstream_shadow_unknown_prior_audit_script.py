from __future__ import annotations

from __future__ import annotations
import json
import pytest
import sys
from scripts.btst_latest_followup_utils import load_upstream_shadow_followup_rows_for_report
from scripts.analyze_btst_upstream_shadow_unknown_prior_audit import (
    analyze_btst_upstream_shadow_unknown_prior_audit,
    render_btst_upstream_shadow_unknown_prior_audit_markdown,
)

# Patch sys.modules for test isolation
sys.modules["scripts.analyze_btst_upstream_shadow_unknown_prior_audit"] = __import__("types").SimpleNamespace()

def test_load_upstream_shadow_followup_rows_for_report_returns_rows_with_report_metadata(tmp_path) -> None:
    report_dir = tmp_path / "report-20260520"
    report_dir.mkdir()
    brief_path = report_dir / "brief.json"
    brief_path.write_text(
        json.dumps(
            {
                "upstream_shadow_summary": {
                    "top_focus_tickers": ["300683"],
                    "validated_rows": [
                        {
                            "ticker": "300683",
                            "decision": "near_miss",
                            "candidate_source": "upstream_liquidity_corridor_shadow",
                            "historical_prior": {
                                "execution_quality_label": "unknown",
                                "sample_count": 1,
                                "evaluable_count": 1,
                            },
                        }
                    ],
                }
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (report_dir / "session_summary.json").write_text(
        json.dumps(
            {
                "end_date": "2026-05-20",
                "selection_target": "short_trade_only",
                "btst_followup": {"trade_date": "2026-05-20", "brief_json": str(brief_path)},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    rows = load_upstream_shadow_followup_rows_for_report(report_dir)

    assert len(rows) == 1
    assert rows[0]["ticker"] == "300683"
    assert rows[0]["decision"] == "near_miss"
    assert rows[0]["candidate_source"] == "upstream_liquidity_corridor_shadow"
    assert rows[0]["trade_date"] == "20260520"
    assert rows[0]["report_dir"] == report_dir.resolve().as_posix()
    assert rows[0]["validated_by_upstream_shadow_recall"] is True
    assert rows[0]["historical_prior"]["execution_quality_label"] == "unknown"

# Step 2: Write the failing trace-status and aggregate test
import sys
sys.modules["scripts.analyze_btst_upstream_shadow_unknown_prior_audit"] = __import__("types").SimpleNamespace()
from scripts.analyze_btst_upstream_shadow_unknown_prior_audit import (
    analyze_btst_upstream_shadow_unknown_prior_audit,
)

def test_analyze_btst_upstream_shadow_unknown_prior_audit_splits_attachment_gap_and_low_sample_rows(
    monkeypatch, tmp_path
) -> None:
    report_dir = tmp_path / "report-20260520"
    report_dir.mkdir()

    monkeypatch.setattr(
        "scripts.analyze_btst_upstream_shadow_unknown_prior_audit.load_upstream_shadow_followup_rows_for_report",
        lambda path: [
            {
                "ticker": "300683",
                "trade_date": "20260520",
                "report_dir": report_dir.resolve().as_posix(),
                "decision": "near_miss",
                "candidate_source": "upstream_liquidity_corridor_shadow",
                "historical_prior": {
                    "execution_quality_label": "unknown",
                    "sample_count": 1,
                    "evaluable_count": 1,
                },
            },
            {
                "ticker": "300720",
                "trade_date": "20260520",
                "report_dir": report_dir.resolve().as_posix(),
                "decision": "selected",
                "candidate_source": "upstream_liquidity_corridor_shadow",
                "historical_prior": {
                    "execution_quality_label": "close_continuation",
                    "sample_count": 1,
                    "evaluable_count": 1,
                },
            },
        ],
    )
    monkeypatch.setattr(
        "scripts.analyze_btst_upstream_shadow_unknown_prior_audit.load_latest_btst_historical_prior_by_ticker",
        lambda reports_root: {
            "300683": {
                "execution_quality_label": "close_continuation",
                "sample_count": 6,
                "evaluable_count": 5,
                "applied_scope": "same_ticker",
            },
            "300720": {
                "execution_quality_label": "close_continuation",
                "sample_count": 1,
                "evaluable_count": 1,
                "applied_scope": "same_ticker",
            },
        },
    )
    monkeypatch.setattr(
        "scripts.analyze_btst_upstream_shadow_unknown_prior_audit.collect_short_trade_rows",
        lambda report_dir, trade_dates=None: [
            {
                "ticker": "300683",
                "trade_date": "20260520",
                "candidate_source": "upstream_liquidity_corridor_shadow",
                "short_trade": {
                    "decision": "near_miss",
                    "historical_prior": {
                        "execution_quality_label": "unknown",
                        "sample_count": 1,
                        "evaluable_count": 1,
                    },
                },
            },
            {
                "ticker": "300720",
                "trade_date": "20260520",
                "candidate_source": "upstream_liquidity_corridor_shadow",
                "short_trade": {
                    "decision": "selected",
                    "historical_prior": {
                        "execution_quality_label": "close_continuation",
                        "sample_count": 1,
                        "evaluable_count": 1,
                    },
                },
            },
        ],
    )

    analysis = analyze_btst_upstream_shadow_unknown_prior_audit(tmp_path)

    assert analysis["coverage_summary"]["rows_audited"] == 2
    assert analysis["trace_status_split"] == {
        "resolve_dropped_stronger_prior": 1,
        "resolved_but_low_sample": 1,
    }
    assert [row["ticker"] for row in analysis["attachment_gap_rows"]] == ["300683"]
    assert [row["ticker"] for row in analysis["low_sample_or_weak_prior_rows"]] == ["300720"]
    assert analysis["ticker_timeline_board"] == [
        {
            "ticker": "300683",
            "occurrences": 1,
            "trace_statuses": ["resolve_dropped_stronger_prior"],
            "trade_dates": ["20260520"],
        },
        {
            "ticker": "300720",
            "occurrences": 1,
            "trace_statuses": ["resolved_but_low_sample"],
            "trade_dates": ["20260520"],
        },
    ]

# Step 3: Write the failing fail-closed + Markdown test
from scripts.analyze_btst_upstream_shadow_unknown_prior_audit import (
    render_btst_upstream_shadow_unknown_prior_audit_markdown,
)

def test_render_btst_upstream_shadow_unknown_prior_audit_markdown_renders_coverage_and_boards() -> None:
    markdown = render_btst_upstream_shadow_unknown_prior_audit_markdown(
        {
            "coverage_summary": {
                "rows_audited": 2,
                "rows_skipped_for_missing_report_inputs": 1,
                "rows_with_partial_trace": 1,
            },
            "trace_status_split": {"resolve_dropped_stronger_prior": 1, "resolved_but_low_sample": 1},
            "attachment_gap_rows": [{"trade_date": "20260520", "ticker": "300683"}],
            "low_sample_or_weak_prior_rows": [{"trade_date": "20260520", "ticker": "300720"}],
            "ticker_timeline_board": [
                {
                    "ticker": "300683",
                    "occurrences": 1,
                    "trace_statuses": ["resolve_dropped_stronger_prior"],
                    "trade_dates": ["20260520"],
                }
            ],
            "recommendation": "Prioritize attachment repair before any label-generation audit.",
        }
    )

    assert "# Upstream Shadow Unknown Prior Coverage Audit" in markdown
    assert "rows_audited: 2" in markdown
    assert "resolve_dropped_stronger_prior" in markdown
    assert "## Attachment Gap Rows" in markdown
    assert "300683" in markdown
