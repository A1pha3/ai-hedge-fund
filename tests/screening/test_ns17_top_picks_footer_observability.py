"""NS-17/BH-017 R2 footer drain — top_picks.py footer block silent return observability.

AutoDev C9/Loop 10 (c279): drains 12 silent return patterns in top_picks.py footer
diagnostic blocks. 11 footer blocks (WARNING — 前门 footer 诊断失败让 operator 丢失
风险校准信息) + 1 per-pick render helper (DEBUG — 纯展示层).

Footer blocks drained (WARNING):
- _print_correlation_block (L1762, Q-4 相关性折减)
- _print_portfolio_risk_block (L1784, R-3 组合风险预算)
- _print_regime_winrate_block (L1813, R-5.A regime 真实胜率)
- _print_monotonicity_block (L1844, NS-4 排序单调性, outer except)
- _print_factor_attribution_block (L1931, M1 因子层归因)
- _print_factor_attribution_by_state_block (L1962, NS-6 state 因子归因)
- _print_model_version_comparison_block (L2011, NS-7 新旧模型对比)
- _print_north_star_block (L2041, 北极星 P&L)
- _print_concentration_block (L2162, P-4 集中度)
- _print_stability_block (L2185, R-1 推荐稳定性)
- _print_data_quality_block (L2212, 数据质量审计)

Per-pick render (DEBUG):
- _render_score_trend (L741, R9 趋势箭头)

Tests verify: best-effort return preserved (no crash) AND warning/debug emitted.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Helper — verify footer block emits WARNING on failure
# ---------------------------------------------------------------------------


def _assert_footer_block_warning(
    caplog,
    block_callable,
    block_name: str,
    patch_target: str,
    *args,
    **kwargs,
) -> None:
    """Helper: patch ``patch_target`` to raise, call ``block_callable``, assert WARNING.

    Args:
        caplog: pytest caplog fixture
        block_callable: the footer block function (e.g. _print_correlation_block)
        block_name: short name for message assertion (e.g. "correlation")
        patch_target: dotted path to the compute function to break
        *args, **kwargs: arguments to pass to block_callable
    """
    with patch(patch_target, side_effect=RuntimeError("boom")):
        with caplog.at_level(logging.WARNING, logger="src.screening.top_picks"):
            block_callable(*args, **kwargs)
    warn_records = [r for r in caplog.records if r.levelno == logging.WARNING and f"{block_name} footer block failed" in r.getMessage()]
    assert len(warn_records) == 1, f"expected 1 WARNING for {block_name} footer, got {warn_records}"


# ---------------------------------------------------------------------------
# Footer block observability tests (WARNING, 11 blocks)
# ---------------------------------------------------------------------------


class TestFooterBlockObservability:
    """Each footer diagnostic block must emit WARNING on failure (NS-17/BH-017 c279)."""

    def test_correlation_footer_failure_emits_warning(self, caplog) -> None:
        from src.screening.top_picks import _print_correlation_block

        _assert_footer_block_warning(
            caplog,
            _print_correlation_block,
            "correlation",
            "src.screening.correlation_discount.compute_correlation_discount",
            [{"ticker": "000001"}],
        )

    def test_portfolio_risk_footer_failure_emits_warning(self, caplog) -> None:
        from src.screening.top_picks import _print_portfolio_risk_block

        _assert_footer_block_warning(
            caplog,
            _print_portfolio_risk_block,
            "portfolio_risk",
            "src.screening.portfolio_risk_budget.summarize_portfolio_risk",
            [{"ticker": "000001"}],
        )

    def test_regime_winrate_footer_failure_emits_warning(self, caplog) -> None:
        from src.screening.top_picks import _print_regime_winrate_block

        _assert_footer_block_warning(
            caplog,
            _print_regime_winrate_block,
            "regime_winrate",
            "src.screening.regime_winrate.render_regime_winrate_line",
            "normal",
        )

    def test_monotonicity_footer_failure_emits_warning(self, caplog, tmp_path: Path) -> None:
        from src.screening.top_picks import _print_monotonicity_block

        _assert_footer_block_warning(
            caplog,
            _print_monotonicity_block,
            "monotonicity",
            "src.screening.rank_monotonicity.compute_rank_monotonicity",
            tmp_path,
        )

    def test_factor_attribution_footer_failure_emits_warning(self, caplog, tmp_path: Path) -> None:
        from src.screening.top_picks import _print_factor_attribution_block

        _assert_footer_block_warning(
            caplog,
            _print_factor_attribution_block,
            "factor_attribution",
            "src.screening.factor_attribution.compute_factor_attribution_from_loaded",
            tmp_path,
        )

    def test_factor_attribution_by_state_footer_failure_emits_warning(self, caplog, tmp_path: Path) -> None:
        from src.screening.top_picks import _print_factor_attribution_by_state_block

        _assert_footer_block_warning(
            caplog,
            _print_factor_attribution_by_state_block,
            "factor_attribution_by_state",
            "src.screening.factor_attribution_by_state.compute_factor_attribution_by_state",
            tmp_path,
        )

    def test_model_version_comparison_footer_failure_emits_warning(self, caplog, tmp_path: Path) -> None:
        from src.screening.top_picks import _print_model_version_comparison_block

        _assert_footer_block_warning(
            caplog,
            _print_model_version_comparison_block,
            "model_version_comparison",
            "src.screening.model_version_comparison.compare_model_versions",
            tmp_path,
        )

    def test_north_star_footer_failure_emits_warning(self, caplog, tmp_path: Path) -> None:
        from src.screening.top_picks import _print_north_star_block

        _assert_footer_block_warning(
            caplog,
            _print_north_star_block,
            "north_star",
            "src.screening.north_star_pnl.compute_north_star_pnl",
            tmp_path,
        )

    def test_concentration_footer_failure_emits_warning(self, caplog) -> None:
        from src.screening.top_picks import _print_concentration_block

        _assert_footer_block_warning(
            caplog,
            _print_concentration_block,
            "concentration",
            "src.screening.portfolio_concentration.compute_industry_concentration",
            [{"ticker": "000001"}],
        )

    def test_stability_footer_failure_emits_warning(self, caplog, tmp_path: Path) -> None:
        from src.screening.top_picks import _print_stability_block

        _assert_footer_block_warning(
            caplog,
            _print_stability_block,
            "stability",
            "src.screening.recommendation_stability.compute_recommendation_stability",
            tmp_path,
        )

    def test_data_quality_footer_failure_emits_warning(self, caplog, tmp_path: Path) -> None:
        from src.screening.top_picks import _print_data_quality_block

        _assert_footer_block_warning(
            caplog,
            _print_data_quality_block,
            "data_quality",
            "src.screening.data_quality_audit.load_latest_recommendations",
            tmp_path,
        )


# ---------------------------------------------------------------------------
# Per-pick render observability test (DEBUG, 1 helper)
# ---------------------------------------------------------------------------


class TestRenderScoreTrendObservability:
    """_render_score_trend failure must emit DEBUG (per-pick 展示层, 非决策链)."""

    def test_render_score_trend_failure_emits_debug(self, caplog, tmp_path: Path) -> None:
        import json

        # Create a report file so _find_latest_report returns non-None
        report_path = tmp_path / "auto_screening_20260701.json"
        report_path.write_text(
            json.dumps({"recommendations": [{"ticker": "000001", "score_b": 0.6}]}),
            encoding="utf-8",
        )

        from src.screening.top_picks import _render_score_trend

        # detect_signal_decay is imported at module top, patch at top_picks namespace
        with patch(
            "src.screening.top_picks.detect_signal_decay",
            side_effect=RuntimeError("boom"),
        ):
            with caplog.at_level(logging.DEBUG, logger="src.screening.top_picks"):
                result = _render_score_trend("000001", report_dir=tmp_path)
        # Best-effort preserved: returns empty string
        assert result == ""
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG and "_render_score_trend failed" in r.getMessage()]
        assert len(debug_records) == 1, f"expected 1 DEBUG for score_trend, got {debug_records}"
        assert "ticker=000001" in debug_records[0].getMessage()

    def test_render_score_trend_success_no_debug(self, caplog, tmp_path: Path) -> None:
        """When signal decay returns None (no prior), no debug should be emitted."""
        from src.screening.top_picks import _render_score_trend

        # _find_latest_report returns None when no reports exist → early return ""
        with caplog.at_level(logging.DEBUG, logger="src.screening.top_picks"):
            result = _render_score_trend("000001", report_dir=tmp_path)
        assert result == ""
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG and "_render_score_trend failed" in r.getMessage()]
        assert len(debug_records) == 0
