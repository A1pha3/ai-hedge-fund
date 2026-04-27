from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING
from contextlib import contextmanager
from collections.abc import Callable

if TYPE_CHECKING:
    from src.backtesting.types import PerformanceMetrics
    from src.execution.daily_pipeline import DailyPipeline
    from src.paper_trading.runtime import PaperTradingArtifacts, SessionRuntimeContext


_FORMAL_BTST_SELECTION_TARGETS = frozenset({"short_trade_only", "dual_target"})


@contextmanager
def _apply_default_btst_formal_flow_flags(*, selection_target: str):
    normalized_selection_target = str(selection_target or "").strip().lower()
    should_default_p2 = normalized_selection_target in _FORMAL_BTST_SELECTION_TARGETS and not str(os.getenv("BTST_0422_P2_REGIME_GATE_MODE", "") or "").strip()
    previous_p2_mode = os.environ.get("BTST_0422_P2_REGIME_GATE_MODE")
    if should_default_p2:
        os.environ["BTST_0422_P2_REGIME_GATE_MODE"] = "enforce"
    try:
        yield
    finally:
        if should_default_p2:
            if previous_p2_mode is None:
                os.environ.pop("BTST_0422_P2_REGIME_GATE_MODE", None)
            else:
                os.environ["BTST_0422_P2_REGIME_GATE_MODE"] = previous_p2_mode


def finalize_runtime_run(
    *,
    context: SessionRuntimeContext,
    metrics: PerformanceMetrics,
    start_date: str,
    end_date: str,
    tickers: list[str] | None,
    initial_capital: float,
    selected_analysts: list[str] | None,
    fast_selected_analysts: list[str] | None,
    short_trade_target_profile_name: str,
    short_trade_target_profile_overrides: dict[str, object] | None,
    selection_target: str,
    cache_benchmark: bool,
    cache_benchmark_ticker: str | None,
    cache_benchmark_clear_first: bool,
    build_runtime_finalization_inputs_fn: Callable[..., dict],
    finalize_paper_trading_session_fn: Callable[..., tuple[dict, Path]],
    build_runtime_artifacts_fn: Callable[[SessionRuntimeContext, Path], PaperTradingArtifacts],
) -> PaperTradingArtifacts:
    _, feedback_summary_path = finalize_paper_trading_session_fn(
        **build_runtime_finalization_inputs_fn(
            context=context,
            metrics=metrics,
            start_date=start_date,
            end_date=end_date,
            tickers=tickers,
            initial_capital=initial_capital,
            selected_analysts=selected_analysts,
            fast_selected_analysts=fast_selected_analysts,
            short_trade_target_profile_name=short_trade_target_profile_name,
            short_trade_target_profile_overrides=short_trade_target_profile_overrides,
            selection_target=selection_target,
            cache_benchmark=cache_benchmark,
            cache_benchmark_ticker=cache_benchmark_ticker,
            cache_benchmark_clear_first=cache_benchmark_clear_first,
        )
    )
    return build_runtime_artifacts_fn(context, feedback_summary_path)


def run_paper_trading_session(
    *,
    start_date: str,
    end_date: str,
    output_dir: str | Path,
    tickers: list[str] | None,
    initial_capital: float,
    model_name: str | None,
    model_provider: str | None,
    selected_analysts: list[str] | None,
    fast_selected_analysts: list[str] | None,
    short_trade_target_profile_name: str,
    short_trade_target_profile_overrides: dict[str, object] | None,
    initial_margin_requirement: float,
    agent: Callable,
    pipeline: DailyPipeline | None,
    frozen_plan_source: str | Path | None,
    selection_target: str,
    cache_benchmark: bool,
    cache_benchmark_ticker: str | None,
    cache_benchmark_clear_first: bool,
    prepare_session_runtime_context_fn: Callable[..., SessionRuntimeContext],
    run_runtime_backtest_fn: Callable[[SessionRuntimeContext], PerformanceMetrics],
    finalize_runtime_run_fn: Callable[..., PaperTradingArtifacts],
) -> PaperTradingArtifacts:
    with _apply_default_btst_formal_flow_flags(selection_target=selection_target):
        context = prepare_session_runtime_context_fn(
            output_dir=output_dir,
            frozen_plan_source=frozen_plan_source,
            model_name=model_name,
            model_provider=model_provider,
            pipeline=pipeline,
            selected_analysts=selected_analysts,
            fast_selected_analysts=fast_selected_analysts,
            short_trade_target_profile_name=short_trade_target_profile_name,
            short_trade_target_profile_overrides=short_trade_target_profile_overrides,
            selection_target=selection_target,
            agent=agent,
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            initial_margin_requirement=initial_margin_requirement,
        )
        metrics = run_runtime_backtest_fn(context)
        return finalize_runtime_run_fn(
            context=context,
            metrics=metrics,
            start_date=start_date,
            end_date=end_date,
            tickers=tickers,
            initial_capital=initial_capital,
            selected_analysts=selected_analysts,
            fast_selected_analysts=fast_selected_analysts,
            short_trade_target_profile_name=short_trade_target_profile_name,
            short_trade_target_profile_overrides=short_trade_target_profile_overrides,
            selection_target=selection_target,
            cache_benchmark=cache_benchmark,
            cache_benchmark_ticker=cache_benchmark_ticker,
            cache_benchmark_clear_first=cache_benchmark_clear_first,
        )
