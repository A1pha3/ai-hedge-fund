from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
from statistics import mean
from typing import Callable, Iterator, Mapping, Sequence

from src.backtesting.engine import BacktestEngine
from src.backtesting.types import PerformanceMetrics, PortfolioValuePoint
from src.execution.daily_pipeline import DailyPipeline, _resolve_pipeline_model_config
from src.main import run_hedge_fund


@dataclass(frozen=True)
class RuleVariantConfig:
    name: str
    env: Mapping[str, str]


DEFAULT_RULE_VARIANTS: tuple[RuleVariantConfig, ...] = (
    RuleVariantConfig(name="baseline", env={}),
    RuleVariantConfig(name="profitability_neutral", env={"LAYER_B_ANALYSIS_PROFITABILITY_ZERO_PASS_MODE": "neutral"}),
    RuleVariantConfig(name="profitability_inactive", env={"LAYER_B_ANALYSIS_PROFITABILITY_ZERO_PASS_MODE": "inactive"}),
    RuleVariantConfig(name="neutral_mean_reversion_guarded_033_no_hard_cliff", env={"LAYER_B_ANALYSIS_NEUTRAL_MEAN_REVERSION_MODE": "guarded_dual_leg_033_no_hard_cliff"}),
    RuleVariantConfig(name="neutral_mean_reversion_partial_half_dual_leg_033_no_hard_cliff", env={"LAYER_B_ANALYSIS_NEUTRAL_MEAN_REVERSION_MODE": "partial_mr_half_dual_leg_033_no_hard_cliff"}),
)


def build_rule_variants(variant_names: Sequence[str] | None = None) -> list[RuleVariantConfig]:
    variants_by_name = {variant.name: variant for variant in DEFAULT_RULE_VARIANTS}
    if variant_names is None:
        return list(DEFAULT_RULE_VARIANTS)

    resolved: list[RuleVariantConfig] = []
    for name in variant_names:
        normalized_name = name.strip()
        if normalized_name not in variants_by_name:
            raise ValueError(f"Unsupported rule variant: {normalized_name}")
        resolved.append(variants_by_name[normalized_name])
    return resolved


@contextmanager
def temporary_env(overrides: Mapping[str, str | None]) -> Iterator[None]:
    previous_values = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, previous in previous_values.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous


def make_pipeline_agent_runner(
    *,
    agent: Callable = run_hedge_fund,
    model_name: str,
    model_provider: str,
    selected_analysts: list[str] | None,
) -> Callable[[list[str], str, str], dict[str, dict[str, dict]]]:
    def _runner(tickers: list[str], trade_date: str, model_tier: str) -> dict[str, dict[str, dict]]:
        trade_date_value = datetime.strptime(trade_date, "%Y%m%d")
        start_date = (trade_date_value - timedelta(days=365)).strftime("%Y-%m-%d")
        end_date = trade_date_value.strftime("%Y-%m-%d")
        resolved_model_name, resolved_model_provider = _resolve_pipeline_model_config(model_tier, model_name, model_provider)
        result = agent(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            portfolio={"cash": 1_000_000, "positions": {}, "margin_requirement": 0.0, "margin_used": 0.0, "realized_gains": {}},
            show_reasoning=False,
            model_name=resolved_model_name,
            model_provider=resolved_model_provider,
            selected_analysts=selected_analysts,
        )
        return result.get("analyst_signals", {})

    return _runner


def summarize_portfolio_values(portfolio_values: Sequence[PortfolioValuePoint]) -> dict[str, float | int | None]:
    if not portfolio_values:
        return {
            "start_value": None,
            "end_value": None,
            "total_return_pct": None,
            "portfolio_value_points": 0,
        }

    start_value = float(portfolio_values[0]["Portfolio Value"])
    end_value = float(portfolio_values[-1]["Portfolio Value"])
    total_return_pct = round(((end_value / start_value) - 1.0) * 100.0, 6) if start_value else None
    return {
        "start_value": start_value,
        "end_value": end_value,
        "total_return_pct": total_return_pct,
        "portfolio_value_points": len(portfolio_values),
    }


def summarize_timing_log(timing_log_path: Path) -> dict[str, float | int | None]:
    if not timing_log_path.exists():
        return {"pipeline_days": 0}

    pipeline_day_events = []
    with timing_log_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if payload.get("event") == "pipeline_day_timing":
                pipeline_day_events.append(payload)

    if not pipeline_day_events:
        return {"pipeline_days": 0}

    def _avg(path: tuple[str, ...]) -> float | None:
        values: list[float] = []
        for event in pipeline_day_events:
            current = event
            for key in path:
                if not isinstance(current, dict) or key not in current:
                    current = None
                    break
                current = current[key]
            if isinstance(current, (int, float)):
                values.append(float(current))
        return mean(values) if values else None

    def _count_nonzero(path: tuple[str, ...]) -> int:
        count = 0
        for event in pipeline_day_events:
            current = event
            for key in path:
                if not isinstance(current, dict) or key not in current:
                    current = None
                    break
                current = current[key]
            if isinstance(current, (int, float)) and float(current) > 0:
                count += 1
        return count

    return {
        "pipeline_days": len(pipeline_day_events),
        "avg_total_day_seconds": _avg(("timing_seconds", "total_day")),
        "avg_post_market_seconds": _avg(("timing_seconds", "post_market")),
        "avg_layer_a_count": _avg(("current_plan", "counts", "layer_a_count")),
        "avg_layer_b_count": _avg(("current_plan", "counts", "layer_b_count")),
        "avg_layer_c_count": _avg(("current_plan", "counts", "layer_c_count")),
        "avg_watchlist_count": _avg(("current_plan", "counts", "watchlist_count")),
        "avg_buy_order_count": _avg(("current_plan", "counts", "buy_order_count")),
        "avg_sell_order_count": _avg(("current_plan", "counts", "sell_order_count")),
        "nonzero_layer_b_days": _count_nonzero(("current_plan", "counts", "layer_b_count")),
        "nonzero_buy_order_days": _count_nonzero(("current_plan", "counts", "buy_order_count")),
        "executed_order_days": _count_nonzero(("executed_order_count",)),
    }


def run_rule_variant_backtests(
    *,
    start_date: str,
    end_date: str,
    initial_capital: float,
    model_name: str,
    model_provider: str,
    selected_analysts: list[str] | None,
    variants: Sequence[RuleVariantConfig],
    output_dir: str | None = None,
    agent: Callable = run_hedge_fund,
) -> dict:
    report_dir = Path(output_dir) if output_dir is not None else Path(__file__).resolve().parents[2] / "data" / "reports" / "rule_variant_backtests"
    report_dir.mkdir(parents=True, exist_ok=True)

    comparisons: dict[str, dict] = {}
    for variant in variants:
        timing_log_path = report_dir / f"{variant.name}.timings.jsonl"
        checkpoint_path = report_dir / f"{variant.name}.checkpoint.json"
        if timing_log_path.exists():
            timing_log_path.unlink()
        if checkpoint_path.exists():
            checkpoint_path.unlink()
        pipeline = DailyPipeline(
            agent_runner=make_pipeline_agent_runner(
                agent=agent,
                model_name=model_name,
                model_provider=model_provider,
                selected_analysts=selected_analysts,
            ),
            base_model_name=model_name,
            base_model_provider=model_provider,
        )
        env_overrides: dict[str, str | None] = {
            "BACKTEST_TIMING_LOG_PATH": str(timing_log_path),
            "LAYER_B_ANALYSIS_PROFITABILITY_ZERO_PASS_MODE": None,
            "LAYER_B_ANALYSIS_NEUTRAL_MEAN_REVERSION_MODE": None,
            "LAYER_B_ANALYSIS_EXCLUDE_NEUTRAL_MEAN_REVERSION": None,
        }
        env_overrides.update(variant.env)

        with temporary_env(env_overrides):
            engine = BacktestEngine(
                agent=agent,
                tickers=[],
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                model_name=model_name,
                model_provider=model_provider,
                selected_analysts=selected_analysts,
                initial_margin_requirement=0.0,
                backtest_mode="pipeline",
                pipeline=pipeline,
                checkpoint_path=str(checkpoint_path),
            )
            performance_metrics = engine.run_backtest()
            portfolio_summary = summarize_portfolio_values(engine.get_portfolio_values())

        if checkpoint_path.exists():
            checkpoint_path.unlink()

        comparisons[variant.name] = {
            "variant": variant.name,
            "env": dict(variant.env),
            "performance_metrics": dict(performance_metrics),
            "portfolio_summary": portfolio_summary,
            "timing_summary": summarize_timing_log(timing_log_path),
            "timing_log_path": str(timing_log_path),
        }

    return {
        "window": {
            "start_date": start_date,
            "end_date": end_date,
        },
        "model": {
            "model_name": model_name,
            "model_provider": model_provider,
        },
        "comparisons": comparisons,
    }


def save_rule_variant_backtests(report: dict, output_path: str) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path