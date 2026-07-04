"""Unit tests for src/research/review_renderer_selected_helpers.py

Covers the markdown line emitters for a selected candidate. Uses stub
format_* callables and SimpleNamespace stand-ins for SelectedCandidate.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.research.review_renderer_selected_helpers import (
    _render_downgrade_section,
    _render_execution_bridge,
    _render_execution_eligibility_section,
    _render_layer_b_summary,
    _render_prompt_section,
    _render_target_decisions,
    render_selected_candidate,
)


def _candidate(**overrides: Any) -> Any:
    base: dict[str, Any] = dict(
        symbol="000001",
        name="平安银行",
        score_final=0.65,
        execution_bridge={},
        research_prompts={},
        target_context={},
        layer_b_summary={},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# _render_target_decisions
# ---------------------------------------------------------------------------


def test_render_target_decisions_both_present() -> None:
    cand = _candidate()

    def _fmt(c, mode):
        return f"{mode}_ok"

    lines = _render_target_decisions(cand, _fmt)
    assert "- research_target: research_ok" in lines
    assert "- short_trade_target: short_trade_ok" in lines


def test_render_target_decisions_one_present() -> None:
    cand = _candidate()

    def _fmt(c, mode):
        return "" if mode == "research" else "st_ok"

    lines = _render_target_decisions(cand, _fmt)
    assert "- research_target:" not in lines
    assert "- short_trade_target: st_ok" in lines


def test_render_target_decisions_both_empty() -> None:
    cand = _candidate()
    lines = _render_target_decisions(cand, lambda c, mode: "")
    assert lines == []


# ---------------------------------------------------------------------------
# _render_execution_bridge
# ---------------------------------------------------------------------------


def test_execution_bridge_no_fields() -> None:
    assert _render_execution_bridge(_candidate()) == []


def test_execution_bridge_block_reason() -> None:
    cand = _candidate(execution_bridge={"block_reason": "low_liquidity"})
    lines = _render_execution_bridge(cand)
    assert any("buy_order_blocker: low_liquidity" in ln for ln in lines)


def test_execution_bridge_block_reason_with_binding() -> None:
    cand = _candidate(execution_bridge={"block_reason": "x", "constraint_binding": "max_positions"})
    lines = _render_execution_bridge(cand)
    assert any("binding=max_positions" in ln for ln in lines)


def test_execution_bridge_reentry_review_until() -> None:
    cand = _candidate(execution_bridge={"reentry_review_until": "20260701"})
    lines = _render_execution_bridge(cand)
    assert any("reentry_review_until: 20260701" in ln for ln in lines)


# ---------------------------------------------------------------------------
# _render_layer_b_summary
# ---------------------------------------------------------------------------


def test_layer_b_summary_empty() -> None:
    assert _render_layer_b_summary(_candidate(), lambda f: str(f)) == []


def test_layer_b_summary_missing_top_factors() -> None:
    assert _render_layer_b_summary(_candidate(layer_b_summary={"x": 1}), lambda f: str(f)) == []


def test_layer_b_summary_caps_at_three() -> None:
    factors = [{"name": f"f{i}"} for i in range(10)]
    cand = _candidate(layer_b_summary={"top_factors": factors})
    lines = _render_layer_b_summary(cand, lambda f: f["name"])
    # Header + 3 factors
    assert lines[0] == "- Layer B 因子摘要:"
    assert len(lines) == 4


# ---------------------------------------------------------------------------
# _render_prompt_section
# ---------------------------------------------------------------------------


def test_prompt_section_with_reasons() -> None:
    cand = _candidate(research_prompts={"why_selected": ["a", "b", "c", "d"]})
    lines = _render_prompt_section(candidate=cand, label="为什么入选", key="why_selected", limit=3)
    assert lines[0] == "- 为什么入选:"
    assert lines[1] == "  - a"
    assert lines[2] == "  - b"
    assert lines[3] == "  - c"
    assert len(lines) == 4  # cap at 3


def test_prompt_section_missing_key() -> None:
    cand = _candidate()
    lines = _render_prompt_section(candidate=cand, label="X", key="missing", limit=5)
    assert lines == ["- X:"]


# ---------------------------------------------------------------------------
# _render_downgrade_section
# ---------------------------------------------------------------------------


def test_downgrade_section_existing_reasons() -> None:
    cand = _candidate(target_context={"downgrade_reasons": ["low_volume", "st_filter"]})
    lines = _render_downgrade_section(cand)
    assert lines[0] == "- 为何被降级:"
    assert any("low_volume" in ln for ln in lines)
    assert any("st_filter" in ln for ln in lines)


def test_downgrade_section_empty_default_message() -> None:
    cand = _candidate()
    lines = _render_downgrade_section(cand)
    assert lines[0] == "- 为何被降级:"
    assert any("无，保留正式执行资格" in ln for ln in lines)


def test_downgrade_section_strips_blank_reasons() -> None:
    cand = _candidate(target_context={"downgrade_reasons": ["valid", "  ", ""]})
    lines = _render_downgrade_section(cand)
    # Only "valid" survives after strip
    assert any("valid" in ln for ln in lines)
    # Cap at 3 reasons → only 1 here
    assert sum(1 for ln in lines if ln.startswith("  - ")) == 1


# ---------------------------------------------------------------------------
# _render_execution_eligibility_section
# ---------------------------------------------------------------------------


def test_eligibility_eligible() -> None:
    cand = _candidate(target_context={"execution_eligible": True})
    lines = _render_execution_eligibility_section(cand)
    assert lines[0] == "- 是否可执行:"
    assert any("是" in ln for ln in lines)


def test_eligibility_not_eligible() -> None:
    cand = _candidate(target_context={"execution_eligible": False})
    lines = _render_execution_eligibility_section(cand)
    assert any("否" in ln for ln in lines)


def test_eligibility_with_details() -> None:
    cand = _candidate(target_context={
        "execution_eligible": True,
        "btst_regime_gate": "halt",
        "historical_prior_quality_level": "low",
        "short_trade_reporting_decision": "shadow_only",
    })
    lines = _render_execution_eligibility_section(cand)
    assert any("gate=halt" in ln for ln in lines)
    assert any("prior=low" in ln for ln in lines)
    assert any("reporting=shadow_only" in ln for ln in lines)


def test_eligibility_with_formal_block_flags() -> None:
    cand = _candidate(target_context={
        "execution_eligible": False,
        "formal_execution_block_flags": ["p3_hard_cliff", "p5_low_confidence"],
    })
    lines = _render_execution_eligibility_section(cand)
    assert any("formal_block=p3_hard_cliff+p5_low_confidence" in ln for ln in lines)


def test_eligibility_empty_target_context() -> None:
    cand = _candidate()
    lines = _render_execution_eligibility_section(cand)
    assert lines[0] == "- 是否可执行:"
    # No details → just "否"
    assert any("否" in ln for ln in lines)


# ---------------------------------------------------------------------------
# render_selected_candidate (integration)
# ---------------------------------------------------------------------------


def test_render_selected_candidate_basic() -> None:
    cand = _candidate(
        score_final=0.75,
        execution_bridge={"included_in_buy_orders": True},
    )
    lines = render_selected_candidate(
        cand, index=1, format_target_decision=lambda c, m: "", format_layer_b_factor=lambda f: ""
    )
    assert lines[0].startswith("### 1. 000001 平安银行")
    assert any("final_score: 0.7500" in ln for ln in lines)
    assert any("buy_order: yes" in ln for ln in lines)
    # Trailing empty line
    assert lines[-1] == ""


def test_render_selected_candidate_buy_order_no() -> None:
    cand = _candidate(execution_bridge={})
    lines = render_selected_candidate(
        cand, index=1, format_target_decision=lambda c, m: "", format_layer_b_factor=lambda f: ""
    )
    assert any("buy_order: no" in ln for ln in lines)
