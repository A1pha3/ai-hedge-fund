from __future__ import annotations

import json
from pathlib import Path
import sys
from unittest.mock import patch

import pandas as pd

from src.execution.models import ExecutionPlan
from src.execution.models import LayerCResult
from src.paper_trading.runtime import _build_dual_target_session_summary, _build_llm_error_digest, _build_llm_observability_summary, _build_llm_route_provenance, _build_paper_trading_engine, _build_runtime_recorder_and_engine, _finalize_paper_trading_session, _prepare_session_runtime_context, run_paper_trading_session
from src.portfolio.models import PositionPlan
from src.targets.models import DualTargetEvaluation, DualTargetSummary


class StubPipeline:
    def __init__(self, post_market_plans, intraday_responses, *args, **kwargs):
        self.post_market_plans = list(post_market_plans)
        self.intraday_responses = list(intraday_responses)

    def run_post_market(self, trade_date: str, portfolio_snapshot: dict | None = None, blocked_buy_tickers: dict | None = None) -> ExecutionPlan:
        if self.post_market_plans:
            return self.post_market_plans.pop(0)
        return ExecutionPlan(date=trade_date, portfolio_snapshot=portfolio_snapshot or {})

    def run_pre_market(self, plan: ExecutionPlan, trade_date_t1: str, **kwargs) -> ExecutionPlan:
        return plan

    def run_intraday(self, plan: ExecutionPlan, trade_date_t1: str, **kwargs):
        if self.intraday_responses:
            return self.intraday_responses.pop(0)
        return [], [], {"pause_new_buys": False, "forced_reduce_ratio": 0.0}


def test_build_llm_observability_summary_aggregates_entries(tmp_path: Path):
    jsonl_path = tmp_path / "llm_metrics.jsonl"
    jsonl_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "trade_date": "20240301",
                        "pipeline_stage": "daily_pipeline_post_market",
                        "model_tier": "fast",
                        "model_provider": "MiniMax",
                        "success": True,
                        "duration_ms": 1200.0,
                    }
                ),
                json.dumps(
                    {
                        "trade_date": "20240301",
                        "pipeline_stage": "daily_pipeline_post_market",
                        "model_tier": "fast",
                        "model_provider": "Volcengine Ark",
                        "success": False,
                        "is_rate_limit": True,
                        "used_fallback": True,
                        "duration_ms": 2200.0,
                        "error_type": "RateLimitError",
                        "error_message": "provider burst limit exceeded",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = _build_llm_observability_summary(jsonl_path)

    assert summary["jsonl_available"] is True
    assert summary["entry_count"] == 2
    assert summary["by_trade_date"]["20240301"]["attempts"] == 2
    assert summary["by_provider"]["Volcengine Ark"]["errors"] == 1
    assert summary["error_type_counts"] == {"RateLimitError": 1}
    assert summary["sample_errors"] == [
        {
            "trade_date": "20240301",
            "pipeline_stage": "daily_pipeline_post_market",
            "model_tier": "fast",
            "provider": "Volcengine Ark",
            "error_type": "RateLimitError",
            "message": "provider burst limit exceeded",
        }
    ]
    assert summary["context_breakdown"] == [
        {
            "trade_date": "20240301",
            "pipeline_stage": "daily_pipeline_post_market",
            "model_tier": "fast",
            "provider": "MiniMax",
            "attempts": 1,
            "successes": 1,
            "errors": 0,
            "rate_limit_errors": 0,
            "fallback_attempts": 0,
            "total_duration_ms": 1200.0,
            "avg_duration_ms": 1200.0,
            "error_types": {},
        },
        {
            "trade_date": "20240301",
            "pipeline_stage": "daily_pipeline_post_market",
            "model_tier": "fast",
            "provider": "Volcengine Ark",
            "attempts": 1,
            "successes": 0,
            "errors": 1,
            "rate_limit_errors": 1,
            "fallback_attempts": 1,
            "total_duration_ms": 2200.0,
            "avg_duration_ms": 2200.0,
            "error_types": {"RateLimitError": 1},
        },
    ]


def test_build_llm_observability_summary_skips_bad_json_lines(tmp_path: Path):
    jsonl_path = tmp_path / "llm_metrics.jsonl"
    jsonl_path.write_text('{"trade_date":"20240301","model_provider":"MiniMax","success":true}\nnot-json\n', encoding="utf-8")

    summary = _build_llm_observability_summary(jsonl_path)

    assert summary["jsonl_available"] is True
    assert summary["entry_count"] == 2
    assert summary["by_trade_date"]["20240301"]["attempts"] == 1
    assert summary["context_breakdown"] == [
        {
            "trade_date": "20240301",
            "pipeline_stage": "unknown",
            "model_tier": "unknown",
            "provider": "MiniMax",
            "attempts": 1,
            "successes": 1,
            "errors": 0,
            "rate_limit_errors": 0,
            "fallback_attempts": 0,
            "total_duration_ms": 0.0,
            "avg_duration_ms": 0.0,
            "error_types": {},
        }
    ]


def test_build_llm_error_digest_flags_fallback_gap():
    digest = _build_llm_error_digest(
        {
            "summary_available": True,
            "errors": 2,
            "rate_limit_errors": 0,
            "fallback_attempts": 0,
            "providers_seen": ["MiniMax", "Volcengine Ark"],
        },
        {
            "jsonl_available": True,
            "error_type_counts": {"TimeoutError": 2},
            "sample_errors": [{"provider": "MiniMax", "message": "timeout"}],
            "by_provider": {
                "MiniMax": {"attempts": 3, "errors": 2, "rate_limit_errors": 0, "fallback_attempts": 0, "error_types": {"TimeoutError": 2}},
                "Volcengine Ark": {"attempts": 2, "errors": 0, "rate_limit_errors": 0, "fallback_attempts": 0, "error_types": {}},
            },
        },
    )

    assert digest["status"] == "degraded"
    assert digest["fallback_gap_detected"] is True
    assert digest["recommendation"] == "errors_detected_without_fallback_review_provider_routing"
    assert digest["affected_providers"] == [
        {
            "provider": "MiniMax",
            "attempts": 3,
            "errors": 2,
            "error_rate": 0.6667,
            "rate_limit_errors": 0,
            "fallback_attempts": 0,
            "top_error_types": [{"error_type": "TimeoutError", "count": 2}],
        }
    ]


def test_build_llm_error_digest_reports_no_data_when_sources_missing():
    digest = _build_llm_error_digest({"summary_available": False}, {"jsonl_available": False})

    assert digest["status"] == "no_data"
    assert digest["recommendation"] == "no_llm_metrics_available"
    assert digest["affected_provider_count"] == 0


def test_build_dual_target_session_summary_aggregates_paper_trading_days(tmp_path: Path):
    daily_events_path = tmp_path / "daily_events.jsonl"
    daily_events_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event": "paper_trading_day",
                        "current_plan": {
                            "target_mode": "dual_target",
                            "selection_targets": {"000001": {}, "000002": {}},
                            "dual_target_summary": {
                                "research_target_count": 3,
                                "short_trade_target_count": 2,
                                "research_selected_count": 1,
                                "research_near_miss_count": 1,
                                "research_rejected_count": 1,
                                "short_trade_selected_count": 1,
                                "short_trade_near_miss_count": 1,
                                "short_trade_blocked_count": 0,
                                "short_trade_rejected_count": 0,
                                "shell_target_count": 1,
                                "delta_classification_counts": {"upgraded": 2},
                            },
                        },
                    }
                ),
                json.dumps(
                    {
                        "event": "paper_trading_day",
                        "current_plan": {
                            "target_mode": "research_only",
                            "selection_targets": {},
                            "dual_target_summary": {
                                "research_target_count": 1,
                                "short_trade_target_count": 4,
                                "research_selected_count": 0,
                                "research_near_miss_count": 0,
                                "research_rejected_count": 1,
                                "short_trade_selected_count": 0,
                                "short_trade_near_miss_count": 2,
                                "short_trade_blocked_count": 1,
                                "short_trade_rejected_count": 1,
                                "shell_target_count": 0,
                                "delta_classification_counts": {"upgraded": 1, "downgraded": 3},
                            },
                        },
                    }
                ),
                json.dumps({"event": "other"}),
                "{bad json}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = _build_dual_target_session_summary(daily_events_path)

    assert summary["day_count"] == 2
    assert summary["days_with_selection_targets"] == 1
    assert summary["selection_target_count"] == 2
    assert summary["research_target_count"] == 4
    assert summary["short_trade_target_count"] == 6
    assert summary["short_trade_near_miss_count"] == 3
    assert summary["target_mode_counts"] == {"dual_target": 1, "research_only": 1}
    assert summary["delta_classification_counts"] == {"upgraded": 3, "downgraded": 3}


def test_build_dual_target_session_summary_returns_default_for_missing_file(tmp_path: Path):
    summary = _build_dual_target_session_summary(tmp_path / "missing.jsonl")

    assert summary["day_count"] == 0
    assert summary["target_mode_counts"] == {}


def test_build_llm_route_provenance_reads_summary_file(tmp_path: Path):
    summary_path = tmp_path / "llm_metrics_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "totals": {
                    "attempts": 5,
                    "successes": 4,
                    "errors": 1,
                    "rate_limit_errors": 1,
                    "fallback_attempts": 2,
                },
                "providers": {
                    "MiniMax": {"attempts": 3},
                    "Volcengine Ark": {"attempts": 0},
                },
                "models": {
                    "abab7": {"attempts": 5},
                    "unused": {"attempts": 0},
                },
                "routes": {
                    "fast": {"attempts": 5},
                    "slow": {"attempts": 0},
                },
            }
        ),
        encoding="utf-8",
    )
    jsonl_path = tmp_path / "llm_metrics.jsonl"

    with patch(
        "src.paper_trading.runtime.get_llm_metrics_paths",
        return_value={
            "summary_path": str(summary_path),
            "jsonl_path": str(jsonl_path),
            "session_id": "session-123",
        },
    ):
        provenance, artifacts = _build_llm_route_provenance()

    assert artifacts == {
        "llm_metrics_jsonl": str(jsonl_path),
        "llm_metrics_summary": str(summary_path),
    }
    assert provenance["session_id"] == "session-123"
    assert provenance["summary_available"] is True
    assert provenance["fallback_observed"] is True
    assert provenance["providers_seen"] == ["MiniMax"]
    assert provenance["models_seen"] == ["abab7"]
    assert provenance["routes_seen"] == ["fast"]


def test_build_llm_route_provenance_records_read_error(tmp_path: Path):
    summary_path = tmp_path / "llm_metrics_summary.json"
    summary_path.write_text("{bad json}", encoding="utf-8")

    with patch(
        "src.paper_trading.runtime.get_llm_metrics_paths",
        return_value={
            "summary_path": str(summary_path),
            "jsonl_path": str(tmp_path / "llm_metrics.jsonl"),
            "session_id": "session-err",
        },
    ):
        provenance, _ = _build_llm_route_provenance()

    assert provenance["summary_available"] is False
    assert "summary_read_error" in provenance


def test_prepare_session_runtime_context_wires_helpers(monkeypatch, tmp_path: Path):
    session_paths = type(
        "SessionPaths",
        (),
        {
            "checkpoint_path": tmp_path / "checkpoint.json",
            "daily_events_path": tmp_path / "daily_events.jsonl",
            "timing_log_path": tmp_path / "timings.jsonl",
            "selection_artifact_root": tmp_path / "artifacts",
            "frozen_plan_source_path": None,
        },
    )()
    pipeline = object()
    engine = object()
    reset_calls: list[dict] = []

    monkeypatch.setattr("src.paper_trading.runtime.get_default_model_config", lambda: ("fallback-model", "fallback-provider"))
    monkeypatch.setattr("src.paper_trading.runtime.resolve_session_paths", lambda **kwargs: session_paths)
    monkeypatch.setattr("src.paper_trading.runtime.resolve_pipeline", lambda **kwargs: pipeline)
    monkeypatch.setattr("src.paper_trading.runtime.snapshot_cache_stats", lambda: {"hits": 7})
    monkeypatch.setattr(
        "src.paper_trading.runtime._reset_output_artifacts_for_fresh_run",
        lambda **kwargs: reset_calls.append(kwargs),
    )
    monkeypatch.setattr("src.paper_trading.runtime._build_paper_trading_engine", lambda **kwargs: engine)

    context = _prepare_session_runtime_context(
        output_dir=tmp_path / "paper",
        frozen_plan_source=None,
        model_name=None,
        model_provider=None,
        pipeline=None,
        selected_analysts=["a"],
        fast_selected_analysts=["b"],
        short_trade_target_profile_name="default",
        short_trade_target_profile_overrides={"x": 1},
        selection_target="research_only",
        agent=lambda **kwargs: {},
        tickers=["AAPL"],
        start_date="2024-03-01",
        end_date="2024-03-05",
        initial_capital=100000.0,
        initial_margin_requirement=0.1,
    )

    assert context.resolved_model_name == "fallback-model"
    assert context.resolved_model_provider == "fallback-provider"
    assert context.session_paths is session_paths
    assert context.pipeline is pipeline
    assert context.cache_stats_before_run == {"hits": 7}
    assert context.engine is engine
    assert context.recorder.path == session_paths.daily_events_path
    assert reset_calls == [
        {
            "checkpoint_path": session_paths.checkpoint_path,
            "daily_events_path": session_paths.daily_events_path,
            "timing_log_path": session_paths.timing_log_path,
            "selection_artifact_root": session_paths.selection_artifact_root,
        }
    ]


def test_finalize_paper_trading_session_writes_summary(monkeypatch, tmp_path: Path):
    summary_path = tmp_path / "summary.json"
    session_paths = type(
        "SessionPaths",
        (),
        {
            "selection_artifact_root": tmp_path / "artifacts",
            "daily_events_path": tmp_path / "daily_events.jsonl",
            "timing_log_path": tmp_path / "timings.jsonl",
            "summary_path": summary_path,
            "output_dir_path": tmp_path,
            "frozen_plan_source_path": None,
        },
    )()
    feedback_summary_path = tmp_path / "artifacts" / "research_feedback_summary.json"
    engine = type(
        "EngineStub",
        (),
        {
            "_pipeline": object(),
            "get_portfolio_values": lambda self: [{"Date": pd.Timestamp("2024-03-01"), "Portfolio Value": 101000.0}],
            "get_portfolio_snapshot": lambda self: {"cash": 1000.0},
        },
    )()
    context = type(
        "Context",
        (),
        {
            "session_paths": session_paths,
            "engine": engine,
            "resolved_model_name": "model-x",
            "resolved_model_provider": "provider-y",
            "cache_stats_before_run": {"hits": 1},
            "recorder": type("Recorder", (), {"day_count": 2, "executed_trade_days": 1, "total_executed_orders": 3})(),
        },
    )()

    monkeypatch.setattr("src.paper_trading.runtime._write_research_feedback_summary", lambda root: ({"feedback_file_count": 1}, feedback_summary_path))
    monkeypatch.setattr("src.paper_trading.runtime._build_llm_route_provenance", lambda: ({"summary_available": True}, {"llm_metrics_jsonl": "metrics.jsonl"}))
    monkeypatch.setattr("src.paper_trading.runtime._build_llm_observability_summary", lambda path: {"jsonl_available": True})
    monkeypatch.setattr("src.paper_trading.runtime._build_llm_error_digest", lambda route, observability: {"status": "healthy"})
    monkeypatch.setattr("src.paper_trading.runtime._build_execution_plan_provenance_summary", lambda pipeline: {"observation_count": 1})
    monkeypatch.setattr("src.paper_trading.runtime._build_dual_target_session_summary", lambda path: {"day_count": 2})
    monkeypatch.setattr("src.paper_trading.runtime.get_cache_runtime_info", lambda: {"stats": {"hits": 9}})
    monkeypatch.setattr("src.paper_trading.runtime.diff_cache_stats", lambda before, after: {"hit_rate": 0.5})
    monkeypatch.setattr(
        "src.paper_trading.runtime.run_optional_cache_benchmark",
        lambda **kwargs: ({"duration": 1.0}, {"benchmark": "artifact"}, "skipped"),
    )
    captured: dict[str, dict] = {}

    def fake_build_session_summary(**kwargs):
        captured["summary_kwargs"] = kwargs
        return {
            "mode": "paper_trading",
            "llm_error_digest": kwargs["llm_error_digest"],
            "data_cache": kwargs["data_cache_summary"],
            "research_feedback_summary": kwargs["research_feedback_summary"],
        }

    monkeypatch.setattr("src.paper_trading.runtime.build_session_summary", fake_build_session_summary)

    summary, written_feedback_path = _finalize_paper_trading_session(
        context=context,
        metrics={"sharpe_ratio": 1.2},
        start_date="2024-03-01",
        end_date="2024-03-05",
        tickers=["AAPL"],
        initial_capital=100000.0,
        selected_analysts=["a"],
        fast_selected_analysts=["b"],
        short_trade_target_profile_name="default",
        short_trade_target_profile_overrides={"x": 1},
        selection_target="research_only",
        cache_benchmark=False,
        cache_benchmark_ticker=None,
        cache_benchmark_clear_first=False,
    )

    assert written_feedback_path == feedback_summary_path
    assert summary["llm_error_digest"] == {"status": "healthy"}
    assert summary["data_cache"]["session_stats"] == {"hit_rate": 0.5}
    assert captured["summary_kwargs"]["resolved_model_name"] == "model-x"
    assert captured["summary_kwargs"]["cache_benchmark_artifacts"] == {"benchmark": "artifact"}
    assert captured["summary_kwargs"]["llm_metrics_artifacts"] == {"llm_metrics_jsonl": "metrics.jsonl"}
    assert summary_path.exists()
    assert json.loads(summary_path.read_text(encoding="utf-8")) == summary


def test_build_paper_trading_engine_wires_writer_and_engine(monkeypatch, tmp_path: Path):
    engine_calls: list[dict] = []
    writer_calls: list[dict] = []

    class WriterStub:
        def __init__(self, *, artifact_root, run_id):
            writer_calls.append({"artifact_root": artifact_root, "run_id": run_id})

    class EngineStub:
        def __init__(self, **kwargs):
            engine_calls.append(kwargs)

    session_paths = type(
        "SessionPaths",
        (),
        {
            "checkpoint_path": tmp_path / "checkpoint.json",
            "selection_artifact_root": tmp_path / "artifacts",
            "output_dir_path": tmp_path / "paper_run",
        },
    )()
    recorder = type("Recorder", (), {"record": lambda self, payload: None})()

    monkeypatch.setattr("src.paper_trading.runtime.FileSelectionArtifactWriter", WriterStub)
    monkeypatch.setattr("src.paper_trading.runtime.BacktestEngine", EngineStub)

    engine = _build_paper_trading_engine(
        agent=lambda **kwargs: {},
        tickers=["AAPL"],
        start_date="2024-03-01",
        end_date="2024-03-05",
        initial_capital=100000.0,
        resolved_model_name="model-x",
        resolved_model_provider="provider-y",
        selected_analysts=["a"],
        initial_margin_requirement=0.1,
        pipeline=object(),
        session_paths=session_paths,
        recorder=recorder,
    )

    assert isinstance(engine, EngineStub)
    assert writer_calls == [{"artifact_root": session_paths.selection_artifact_root, "run_id": session_paths.output_dir_path.name}]
    assert engine_calls[0]["checkpoint_path"] == str(session_paths.checkpoint_path)
    assert engine_calls[0]["selection_artifact_writer"].__class__.__name__ == "WriterStub"


def test_build_runtime_recorder_and_engine_reuses_recorder_path(monkeypatch, tmp_path: Path):
    build_calls: list[dict] = []

    class RecorderStub:
        def __init__(self, path):
            self.path = path

    monkeypatch.setattr("src.paper_trading.runtime.JsonlPaperTradingRecorder", RecorderStub)
    monkeypatch.setattr(
        "src.paper_trading.runtime._build_paper_trading_engine",
        lambda **kwargs: build_calls.append(kwargs) or "engine-stub",
    )

    session_paths = type("SessionPaths", (), {"daily_events_path": tmp_path / "daily_events.jsonl"})()
    recorder, engine = _build_runtime_recorder_and_engine(
        agent=lambda **kwargs: {},
        tickers=["AAPL"],
        start_date="2024-03-01",
        end_date="2024-03-05",
        initial_capital=100000.0,
        resolved_model_name="model-x",
        resolved_model_provider="provider-y",
        selected_analysts=["a"],
        initial_margin_requirement=0.1,
        pipeline=object(),
        session_paths=session_paths,
    )

    assert recorder.path == session_paths.daily_events_path
    assert engine == "engine-stub"
    assert build_calls[0]["recorder"] is recorder
    assert build_calls[0]["session_paths"] is session_paths


def _patch_market_data(monkeypatch, closes_by_ticker: dict[str, dict[str, float]]) -> None:
    monkeypatch.setattr("src.backtesting.engine.get_prices", lambda *a, **k: None)
    monkeypatch.setattr("src.backtesting.engine.get_financial_metrics", lambda *a, **k: [])
    monkeypatch.setattr("src.backtesting.engine.get_insider_trades", lambda *a, **k: [])
    monkeypatch.setattr("src.backtesting.engine.get_company_news", lambda *a, **k: [])
    monkeypatch.setattr("src.backtesting.output.print_backtest_results", lambda *a, **k: None)
    monkeypatch.setattr("src.backtesting.engine.get_limit_list", lambda *a, **k: None)

    def fake_get_price_data(ticker: str, start_date: str, end_date: str, api_key=None):
        closes = closes_by_ticker[ticker]
        rows = [
            {"date": date_str, "close": close, "open": close, "high": close, "low": close, "volume": 1_000_000}
            for date_str, close in closes.items()
            if start_date <= date_str <= end_date
        ]
        frame = pd.DataFrame(rows)
        if frame.empty:
            return frame
        frame["date"] = pd.to_datetime(frame["date"])
        frame.set_index("date", inplace=True)
        return frame[["open", "close", "high", "low", "volume"]]

    monkeypatch.setattr("src.backtesting.engine.get_price_data", fake_get_price_data)
    monkeypatch.setattr("src.backtesting.benchmarks.get_price_data", fake_get_price_data)


def test_run_paper_trading_session_writes_artifacts(tmp_path, monkeypatch):
    metrics_summary_path = tmp_path / "llm_metrics.summary.json"
    metrics_jsonl_path = tmp_path / "llm_metrics.jsonl"
    monkeypatch.setattr(
        "src.paper_trading.runtime.get_llm_metrics_paths",
        lambda: {
            "session_id": "test-session",
            "summary_path": str(metrics_summary_path),
            "jsonl_path": str(metrics_jsonl_path),
        },
    )

    _patch_market_data(
        monkeypatch,
        {
            "AAPL": {
                "2024-03-01": 10.0,
                "2024-03-04": 11.0,
                "2024-03-05": 12.0,
            },
            "SPY": {
                "2024-03-01": 100.0,
                "2024-03-04": 101.0,
                "2024-03-05": 102.0,
            },
        },
    )
    plan = ExecutionPlan(
        date="20240301",
        buy_orders=[PositionPlan(ticker="AAPL", shares=100, amount=1000.0, score_final=0.8, execution_ratio=1.0)],
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={"counts": {"watchlist_count": 1}},
        selection_targets={"AAPL": DualTargetEvaluation(ticker="AAPL", trade_date="20240301")},
        target_mode="research_only",
        dual_target_summary=DualTargetSummary(target_mode="research_only", selection_target_count=1, shell_target_count=1),
    )
    pipeline = StubPipeline(
        post_market_plans=[plan, ExecutionPlan(date="20240304", portfolio_snapshot={})],
        intraday_responses=[(plan.buy_orders, [], {"pause_new_buys": False, "forced_reduce_ratio": 0.0})],
    )
    pipeline.execution_plan_provenance_log = [
        {
            "trade_date": "20240301",
            "model_tier": "fast",
            "tickers": ["AAPL"],
            "execution_plan_provenance": {
                "planning_mode": "parallel",
                "active_provider_names": ["MiniMax", "Volcengine Ark"],
                "effective_concurrency_limit": 9,
            },
        }
    ]

    artifacts = run_paper_trading_session(
        start_date="2024-03-01",
        end_date="2024-03-05",
        output_dir=tmp_path / "paper_trading",
        tickers=["AAPL"],
        model_name="test-model",
        model_provider="test-provider",
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        pipeline=pipeline,
    )

    assert artifacts.daily_events_path.exists()
    assert artifacts.timing_log_path.exists()
    assert artifacts.summary_path.exists()
    assert artifacts.selection_artifact_root.exists()
    assert artifacts.feedback_summary_path.exists()

    lines = [json.loads(line) for line in artifacts.daily_events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines
    assert lines[0]["event"] == "paper_trading_day"
    assert "current_plan" in lines[0]
    assert lines[0]["current_plan"]["selection_artifacts"]["write_status"] == "success"
    assert lines[0]["current_plan"]["target_mode"] == "research_only"
    assert lines[0]["current_plan"]["dual_target_summary"]["selection_target_count"] == 1
    assert lines[0]["execution_plan_provenance"] == [
        {
            "trade_date": "20240301",
            "model_tier": "fast",
            "tickers": ["AAPL"],
            "execution_plan_provenance": {
                "planning_mode": "parallel",
                "active_provider_names": ["MiniMax", "Volcengine Ark"],
                "effective_concurrency_limit": 9,
            },
        }
    ]

    timing_lines = [json.loads(line) for line in artifacts.timing_log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    day_timing = next(line for line in timing_lines if line.get("event") == "pipeline_day_timing" and line.get("trade_date") == "20240301")
    assert day_timing["execution_plan_provenance"] == lines[0]["execution_plan_provenance"]
    assert day_timing["current_plan"]["selection_artifacts"]["write_status"] == "success"
    assert day_timing["current_plan"]["target_mode"] == "research_only"
    assert day_timing["current_plan"]["selection_target_count"] == 1

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["mode"] == "paper_trading"
    assert summary["plan_generation"]["mode"] == "live_pipeline"
    assert summary["execution_plan_provenance"] == {
        "observation_count": 1,
        "observations": [
            {
                "trade_date": "20240301",
                "model_tier": "fast",
                "tickers": ["AAPL"],
                "execution_plan_provenance": {
                    "planning_mode": "parallel",
                    "active_provider_names": ["MiniMax", "Volcengine Ark"],
                    "effective_concurrency_limit": 9,
                },
            }
        ],
    }
    assert summary["dual_target_summary"] == {
        "day_count": 3,
        "days_with_selection_targets": 1,
        "selection_target_count": 1,
        "research_target_count": 0,
        "short_trade_target_count": 0,
        "research_selected_count": 0,
        "research_near_miss_count": 0,
        "research_rejected_count": 0,
        "short_trade_selected_count": 0,
        "short_trade_near_miss_count": 0,
        "short_trade_blocked_count": 0,
        "short_trade_rejected_count": 0,
        "shell_target_count": 1,
        "target_mode_counts": {"research_only": 3},
        "delta_classification_counts": {},
    }
    assert summary["llm_route_provenance"] == {
        "session_id": "test-session",
        "summary_available": False,
        "attempts": 0,
        "successes": 0,
        "errors": 0,
        "rate_limit_errors": 0,
        "fallback_attempts": 0,
        "fallback_observed": False,
        "contaminated_by_provider_fallback": False,
        "providers_seen": [],
        "models_seen": [],
        "routes_seen": [],
    }
    assert summary["llm_observability_summary"] == {
        "jsonl_available": False,
        "entry_count": 0,
        "by_trade_date": {},
        "by_model_tier": {},
        "by_provider": {},
        "context_breakdown": [],
        "error_type_counts": {},
        "sample_errors": [],
    }
    assert summary["llm_error_digest"] == {
        "status": "no_data",
        "error_count": 0,
        "rate_limit_error_count": 0,
        "fallback_attempt_count": 0,
        "affected_provider_count": 0,
        "top_error_types": [],
        "affected_providers": [],
        "sample_errors": [],
        "fallback_gap_detected": False,
        "recommendation": "no_llm_metrics_available",
    }
    assert summary["research_feedback_summary"]["feedback_file_count"] >= 1
    assert summary["research_feedback_summary"]["trade_date_count"] >= 1
    assert summary["data_cache"]["disk_available"] is True
    assert "stats" in summary["data_cache"]
    assert "session_stats" in summary["data_cache"]
    assert "hit_rate" in summary["data_cache"]["session_stats"]
    assert summary["daily_event_stats"]["day_count"] >= 1
    assert summary["artifacts"]["summary"] == str(artifacts.summary_path)
    assert summary["artifacts"]["selection_artifact_root"] == str(artifacts.selection_artifact_root)
    assert summary["artifacts"]["research_feedback_summary"] == str(artifacts.feedback_summary_path)
    assert summary["artifacts"]["data_cache_path"] == summary["data_cache"]["disk_path"]
    assert summary["artifacts"]["llm_metrics_summary"] == str(metrics_summary_path)
    assert summary["artifacts"]["llm_metrics_jsonl"] == str(metrics_jsonl_path)


def test_run_paper_trading_session_threads_fast_selected_analysts_into_pipeline(tmp_path, monkeypatch):
    metrics_summary_path = tmp_path / "llm_metrics.summary.json"
    metrics_jsonl_path = tmp_path / "llm_metrics.jsonl"
    monkeypatch.setattr(
        "src.paper_trading.runtime.get_llm_metrics_paths",
        lambda: {
            "session_id": "test-session-fast-analysts",
            "summary_path": str(metrics_summary_path),
            "jsonl_path": str(metrics_jsonl_path),
        },
    )

    _patch_market_data(
        monkeypatch,
        {
            "AAPL": {
                "2024-03-01": 10.0,
                "2024-03-04": 11.0,
            },
            "SPY": {
                "2024-03-01": 100.0,
                "2024-03-04": 101.0,
            },
        },
    )

    captured: dict = {}

    class CapturingPipeline(StubPipeline):
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)
            plan = ExecutionPlan(
                date="20240301",
                buy_orders=[PositionPlan(ticker="AAPL", shares=100, amount=1000.0, score_final=0.8, execution_ratio=1.0)],
                portfolio_snapshot={"cash": 100000.0, "positions": {}},
                risk_metrics={"counts": {"watchlist_count": 1}},
            )
            super().__init__(
                post_market_plans=[plan],
                intraday_responses=[(plan.buy_orders, [], {"pause_new_buys": False, "forced_reduce_ratio": 0.0})],
            )
            self.execution_plan_provenance_log = []

    monkeypatch.setattr("src.paper_trading.runtime.DailyPipeline", CapturingPipeline)

    artifacts = run_paper_trading_session(
        start_date="2024-03-01",
        end_date="2024-03-04",
        output_dir=tmp_path / "paper_trading_fast_analysts",
        tickers=["AAPL"],
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=["technical_analyst", "valuation_analyst"],
        fast_selected_analysts=["technical_analyst"],
        short_trade_target_profile_name="aggressive",
        short_trade_target_profile_overrides={"select_threshold": 0.52, "near_miss_threshold": 0.44},
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert captured["selected_analysts"] == ["technical_analyst", "valuation_analyst"]
    assert captured["fast_selected_analysts"] == ["technical_analyst"]
    assert captured["short_trade_target_profile_name"] == "aggressive"
    assert captured["short_trade_target_profile_overrides"] == {"select_threshold": 0.52, "near_miss_threshold": 0.44}
    assert summary["selected_analysts"] == ["technical_analyst", "valuation_analyst"]
    assert summary["fast_selected_analysts"] == ["technical_analyst"]
    assert summary["short_trade_target_profile_name"] == "aggressive"
    assert summary["short_trade_target_profile_overrides"] == {"select_threshold": 0.52, "near_miss_threshold": 0.44}


def test_run_paper_trading_session_resets_stale_artifacts_for_fresh_run(tmp_path, monkeypatch):
    metrics_summary_path = tmp_path / "llm_metrics.summary.json"
    metrics_jsonl_path = tmp_path / "llm_metrics.jsonl"
    monkeypatch.setattr(
        "src.paper_trading.runtime.get_llm_metrics_paths",
        lambda: {
            "session_id": "test-session-reset-output",
            "summary_path": str(metrics_summary_path),
            "jsonl_path": str(metrics_jsonl_path),
        },
    )

    _patch_market_data(
        monkeypatch,
        {
            "AAPL": {
                "2024-03-01": 10.0,
                "2024-03-04": 11.0,
            },
            "SPY": {
                "2024-03-01": 100.0,
                "2024-03-04": 101.0,
            },
        },
    )
    monkeypatch.setattr("src.execution.daily_pipeline.build_candidate_pool", lambda trade_date: (_ for _ in ()).throw(AssertionError("live pipeline should not run during frozen replay")))

    first_source_path = tmp_path / "first_daily_events.jsonl"
    first_source_path.write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": "20240301",
                "current_plan": ExecutionPlan(
                    date="20240301",
                    buy_orders=[PositionPlan(ticker="AAPL", shares=100, amount=1000.0, score_final=0.8, execution_ratio=1.0)],
                    portfolio_snapshot={"cash": 100000.0, "positions": {}},
                    risk_metrics={"counts": {"watchlist_count": 1}},
                ).model_dump(),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    output_dir = tmp_path / "paper_trading_reused_output"
    run_paper_trading_session(
        start_date="2024-03-01",
        end_date="2024-03-01",
        output_dir=output_dir,
        tickers=["AAPL"],
        model_name="test-model",
        model_provider="test-provider",
        frozen_plan_source=first_source_path,
    )

    second_source_path = tmp_path / "second_daily_events.jsonl"
    second_source_path.write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": "20240304",
                "current_plan": ExecutionPlan(
                    date="20240304",
                    buy_orders=[PositionPlan(ticker="AAPL", shares=100, amount=1100.0, score_final=0.7, execution_ratio=1.0)],
                    portfolio_snapshot={"cash": 99000.0, "positions": {}},
                    risk_metrics={"counts": {"watchlist_count": 1}},
                ).model_dump(),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    artifacts = run_paper_trading_session(
        start_date="2024-03-04",
        end_date="2024-03-04",
        output_dir=output_dir,
        tickers=["AAPL"],
        model_name="test-model",
        model_provider="test-provider",
        frozen_plan_source=second_source_path,
    )

    lines = [json.loads(line) for line in artifacts.daily_events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [line["trade_date"] for line in lines] == ["20240304"]

    timing_lines = [json.loads(line) for line in artifacts.timing_log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    replay_day_timings = [line for line in timing_lines if line.get("event") == "pipeline_day_timing"]
    assert [line["trade_date"] for line in replay_day_timings] == ["20240304"]

    artifact_dates = sorted(path.name for path in artifacts.selection_artifact_root.iterdir() if path.is_dir())
    assert artifact_dates == ["2024-03-04"]

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["daily_event_stats"]["day_count"] == 1
    assert summary["research_feedback_summary"]["trade_date_count"] == 1
    assert sorted(summary["research_feedback_summary"]["by_trade_date"].keys()) == ["2024-03-04"]


def test_run_paper_trading_session_collects_engine_created_pipeline_provenance(tmp_path, monkeypatch):
    metrics_summary_path = tmp_path / "llm_metrics.summary.json"
    metrics_jsonl_path = tmp_path / "llm_metrics.jsonl"
    monkeypatch.setattr(
        "src.paper_trading.runtime.get_llm_metrics_paths",
        lambda: {
            "session_id": "test-session-engine-pipeline",
            "summary_path": str(metrics_summary_path),
            "jsonl_path": str(metrics_jsonl_path),
        },
    )

    _patch_market_data(
        monkeypatch,
        {
            "AAPL": {
                "2024-03-01": 10.0,
                "2024-03-04": 11.0,
            },
            "SPY": {
                "2024-03-01": 100.0,
                "2024-03-04": 101.0,
            },
        },
    )

    plan = ExecutionPlan(
        date="20240301",
        buy_orders=[PositionPlan(ticker="AAPL", shares=100, amount=1000.0, score_final=0.8, execution_ratio=1.0)],
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={"counts": {"watchlist_count": 1}},
    )

    class AutoPipeline(StubPipeline):
        def __init__(self, *args, **kwargs):
            super().__init__([plan], [(plan.buy_orders, [], {"pause_new_buys": False, "forced_reduce_ratio": 0.0})], *args, **kwargs)
            self.execution_plan_provenance_log = [
                {
                    "trade_date": "20240301",
                    "model_tier": "fast",
                    "tickers": ["AAPL"],
                    "execution_plan_provenance": {
                        "planning_mode": "parallel",
                        "active_provider_names": ["MiniMax", "Volcengine"],
                        "effective_concurrency_limit": 9,
                    },
                }
            ]

    monkeypatch.setattr("src.paper_trading.runtime.DailyPipeline", AutoPipeline)

    artifacts = run_paper_trading_session(
        start_date="2024-03-01",
        end_date="2024-03-04",
        output_dir=tmp_path / "paper_trading_engine_pipeline",
        tickers=["AAPL"],
        model_name="test-model",
        model_provider="test-provider",
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["execution_plan_provenance"] == {
        "observation_count": 1,
        "observations": [
            {
                "trade_date": "20240301",
                "model_tier": "fast",
                "tickers": ["AAPL"],
                "execution_plan_provenance": {
                    "planning_mode": "parallel",
                    "active_provider_names": ["MiniMax", "Volcengine"],
                    "effective_concurrency_limit": 9,
                },
            }
        ],
    }


def test_run_paper_trading_session_live_pipeline_multi_day_artifacts_are_aggregated(tmp_path, monkeypatch):
    metrics_summary_path = tmp_path / "llm_metrics.summary.json"
    metrics_jsonl_path = tmp_path / "llm_metrics.jsonl"
    monkeypatch.setattr(
        "src.paper_trading.runtime.get_llm_metrics_paths",
        lambda: {
            "session_id": "test-session-live-pipeline-multi-day",
            "summary_path": str(metrics_summary_path),
            "jsonl_path": str(metrics_jsonl_path),
        },
    )

    _patch_market_data(
        monkeypatch,
        {
            "AAPL": {
                "2024-03-01": 10.0,
                "2024-03-04": 11.0,
            },
            "MSFT": {
                "2024-03-01": 20.0,
                "2024-03-04": 21.0,
            },
            "SPY": {
                "2024-03-01": 100.0,
                "2024-03-04": 101.0,
            },
        },
    )

    first_day_plan = ExecutionPlan(
        date="20240301",
        buy_orders=[PositionPlan(ticker="AAPL", shares=100, amount=1000.0, score_final=0.81, execution_ratio=1.0, quality_score=0.7)],
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={
            "counts": {
                "layer_a_count": 20,
                "layer_b_count": 3,
                "watchlist_count": 1,
                "buy_order_count": 1,
            }
        },
        watchlist=[
            LayerCResult(
                ticker="AAPL",
                score_b=0.82,
                score_c=0.8,
                score_final=0.81,
                quality_score=0.7,
                decision="watch",
            )
        ],
    )
    second_day_plan = ExecutionPlan(
        date="20240304",
        buy_orders=[PositionPlan(ticker="MSFT", shares=50, amount=1000.0, score_final=0.76, execution_ratio=1.0, quality_score=0.68)],
        portfolio_snapshot={"cash": 99000.0, "positions": {"AAPL": {"long": 100, "short": 0, "long_cost_basis": 10.0, "short_cost_basis": 0.0}}},
        risk_metrics={
            "counts": {
                "layer_a_count": 22,
                "layer_b_count": 4,
                "watchlist_count": 1,
                "buy_order_count": 1,
            }
        },
        watchlist=[
            LayerCResult(
                ticker="MSFT",
                score_b=0.77,
                score_c=0.75,
                score_final=0.76,
                quality_score=0.68,
                decision="watch",
            )
        ],
    )

    pipeline = StubPipeline(
        post_market_plans=[first_day_plan, second_day_plan],
        intraday_responses=[(first_day_plan.buy_orders, [], {"pause_new_buys": False, "forced_reduce_ratio": 0.0})],
    )
    pipeline.execution_plan_provenance_log = [
        {
            "trade_date": "20240301",
            "model_tier": "fast",
            "tickers": ["AAPL"],
            "execution_plan_provenance": {
                "planning_mode": "parallel",
                "active_provider_names": ["MiniMax"],
                "effective_concurrency_limit": 9,
            },
        },
        {
            "trade_date": "20240304",
            "model_tier": "fast",
            "tickers": ["MSFT"],
            "execution_plan_provenance": {
                "planning_mode": "parallel",
                "active_provider_names": ["MiniMax"],
                "effective_concurrency_limit": 9,
            },
        },
    ]

    artifacts = run_paper_trading_session(
        start_date="2024-03-01",
        end_date="2024-03-04",
        output_dir=tmp_path / "paper_trading_live_pipeline_multi_day",
        tickers=["AAPL", "MSFT"],
        model_name="test-model",
        model_provider="test-provider",
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        pipeline=pipeline,
    )

    first_day_dir = artifacts.selection_artifact_root / "2024-03-01"
    second_day_dir = artifacts.selection_artifact_root / "2024-03-04"
    assert (first_day_dir / "selection_snapshot.json").exists()
    assert (first_day_dir / "selection_review.md").exists()
    assert (first_day_dir / "research_feedback.jsonl").exists()
    assert (second_day_dir / "selection_snapshot.json").exists()
    assert (second_day_dir / "selection_review.md").exists()
    assert (second_day_dir / "research_feedback.jsonl").exists()

    lines = [json.loads(line) for line in artifacts.daily_events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [line["trade_date"] for line in lines] == ["20240301", "20240304"]
    assert lines[0]["current_plan"]["selection_artifacts"]["write_status"] == "success"
    assert lines[0]["current_plan"]["selection_artifacts"]["snapshot_path"].endswith("2024-03-01/selection_snapshot.json")
    assert lines[1]["current_plan"]["selection_artifacts"]["write_status"] == "success"
    assert lines[1]["current_plan"]["selection_artifacts"]["snapshot_path"].endswith("2024-03-04/selection_snapshot.json")

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["plan_generation"]["mode"] == "live_pipeline"
    assert summary["research_feedback_summary"]["feedback_file_count"] == 2
    assert summary["research_feedback_summary"]["trade_date_count"] == 2
    assert sorted(summary["research_feedback_summary"]["by_trade_date"].keys()) == ["2024-03-01", "2024-03-04"]
    assert summary["execution_plan_provenance"]["observation_count"] == 2
    assert [item["trade_date"] for item in summary["execution_plan_provenance"]["observations"]] == ["20240301", "20240304"]


def test_run_paper_trading_session_writes_cache_benchmark_artifacts(tmp_path, monkeypatch):
    metrics_summary_path = tmp_path / "llm_metrics.summary.json"
    metrics_jsonl_path = tmp_path / "llm_metrics.jsonl"
    monkeypatch.setattr(
        "src.paper_trading.runtime.get_llm_metrics_paths",
        lambda: {
            "session_id": "test-session-cache-benchmark",
            "summary_path": str(metrics_summary_path),
            "jsonl_path": str(metrics_jsonl_path),
        },
    )

    _patch_market_data(
        monkeypatch,
        {
            "AAPL": {
                "2024-03-01": 10.0,
                "2024-03-04": 11.0,
            },
            "SPY": {
                "2024-03-01": 100.0,
                "2024-03-04": 101.0,
            },
        },
    )

    benchmark_calls: list[dict] = []

    def fake_run_cache_reuse_benchmark(**kwargs):
        benchmark_calls.append(kwargs)
        output_path = Path(kwargs["output_path"])
        markdown_path = Path(kwargs["markdown_output_path"])
        report_path = Path(kwargs["append_markdown_to"])
        payload = {
            "trade_date": kwargs["trade_date"],
            "ticker": kwargs["ticker"],
            "clear_first": kwargs["clear_first"],
            "summary": {"reuse_confirmed": True, "disk_hit_gain": 6},
        }
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text("# Data Cache Benchmark\n", encoding="utf-8")
        report_path.write_text("# Window Review\n\n# Data Cache Benchmark\n", encoding="utf-8")
        return payload

    monkeypatch.setattr("src.paper_trading.runtime.run_cache_reuse_benchmark", fake_run_cache_reuse_benchmark)

    plan = ExecutionPlan(
        date="20240301",
        buy_orders=[PositionPlan(ticker="AAPL", shares=100, amount=1000.0, score_final=0.8, execution_ratio=1.0)],
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={"counts": {"watchlist_count": 1}},
    )
    pipeline = StubPipeline(
        post_market_plans=[plan],
        intraday_responses=[(plan.buy_orders, [], {"pause_new_buys": False, "forced_reduce_ratio": 0.0})],
    )

    artifacts = run_paper_trading_session(
        start_date="2024-03-01",
        end_date="2024-03-04",
        output_dir=tmp_path / "paper_trading_cache_benchmark",
        tickers=["AAPL"],
        model_name="test-model",
        model_provider="test-provider",
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        pipeline=pipeline,
        cache_benchmark=True,
        cache_benchmark_clear_first=True,
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert len(benchmark_calls) == 1
    assert benchmark_calls[0]["repo_root"].name == "ai-hedge-fund-fork"
    assert benchmark_calls[0]["python_executable"] == sys.executable
    assert benchmark_calls[0]["trade_date"] == "20240304"
    assert benchmark_calls[0]["ticker"] == "AAPL"
    assert benchmark_calls[0]["clear_first"] is True
    assert summary["data_cache_benchmark"]["summary"]["reuse_confirmed"] is True
    assert summary["data_cache_benchmark_status"] == {
        "requested": True,
        "executed": True,
        "write_status": "success",
        "reason": None,
    }
    assert summary["artifacts"]["data_cache_benchmark_json"].endswith("data_cache_benchmark.json")
    assert summary["artifacts"]["data_cache_benchmark_markdown"].endswith("data_cache_benchmark.md")
    assert summary["artifacts"]["data_cache_benchmark_appended_report"].endswith("window_review.md")


def test_run_paper_trading_session_does_not_fail_when_cache_benchmark_errors(tmp_path, monkeypatch):
    metrics_summary_path = tmp_path / "llm_metrics.summary.json"
    metrics_jsonl_path = tmp_path / "llm_metrics.jsonl"
    monkeypatch.setattr(
        "src.paper_trading.runtime.get_llm_metrics_paths",
        lambda: {
            "session_id": "test-session-cache-benchmark-failed",
            "summary_path": str(metrics_summary_path),
            "jsonl_path": str(metrics_jsonl_path),
        },
    )

    _patch_market_data(
        monkeypatch,
        {
            "AAPL": {
                "2024-03-01": 10.0,
                "2024-03-04": 11.0,
            },
            "SPY": {
                "2024-03-01": 100.0,
                "2024-03-04": 101.0,
            },
        },
    )

    monkeypatch.setattr("src.paper_trading.runtime.run_cache_reuse_benchmark", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("benchmark failed")))

    plan = ExecutionPlan(
        date="20240301",
        buy_orders=[PositionPlan(ticker="AAPL", shares=100, amount=1000.0, score_final=0.8, execution_ratio=1.0)],
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={"counts": {"watchlist_count": 1}},
    )
    pipeline = StubPipeline(
        post_market_plans=[plan],
        intraday_responses=[(plan.buy_orders, [], {"pause_new_buys": False, "forced_reduce_ratio": 0.0})],
    )

    artifacts = run_paper_trading_session(
        start_date="2024-03-01",
        end_date="2024-03-04",
        output_dir=tmp_path / "paper_trading_cache_benchmark_failed",
        tickers=["AAPL"],
        model_name="test-model",
        model_provider="test-provider",
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        pipeline=pipeline,
        cache_benchmark=True,
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert artifacts.summary_path.exists()
    assert summary["data_cache_benchmark"] == {
        "requested": True,
        "executed": False,
        "write_status": "failed",
        "reason": "benchmark failed",
        "ticker": "AAPL",
        "trade_date": "20240304",
    }
    assert summary["data_cache_benchmark_status"] == {
        "requested": True,
        "executed": False,
        "write_status": "failed",
        "reason": "benchmark failed",
    }
    assert "data_cache_benchmark_json" not in summary["artifacts"]


def test_run_paper_trading_session_skips_cache_benchmark_without_available_ticker(tmp_path, monkeypatch):
    metrics_summary_path = tmp_path / "llm_metrics.summary.json"
    metrics_jsonl_path = tmp_path / "llm_metrics.jsonl"
    monkeypatch.setattr(
        "src.paper_trading.runtime.get_llm_metrics_paths",
        lambda: {
            "session_id": "test-session-cache-benchmark-skipped",
            "summary_path": str(metrics_summary_path),
            "jsonl_path": str(metrics_jsonl_path),
        },
    )

    _patch_market_data(
        monkeypatch,
        {
            "SPY": {
                "2024-03-01": 100.0,
                "2024-03-04": 101.0,
            },
        },
    )

    benchmark_calls: list[dict] = []
    monkeypatch.setattr("src.paper_trading.runtime.run_cache_reuse_benchmark", lambda **kwargs: benchmark_calls.append(kwargs))

    pipeline = StubPipeline(
        post_market_plans=[ExecutionPlan(date="20240301", portfolio_snapshot={"cash": 100000.0, "positions": {}}, risk_metrics={"counts": {"watchlist_count": 0}})],
        intraday_responses=[([], [], {"pause_new_buys": False, "forced_reduce_ratio": 0.0})],
    )

    artifacts = run_paper_trading_session(
        start_date="2024-03-01",
        end_date="2024-03-04",
        output_dir=tmp_path / "paper_trading_cache_benchmark_skipped",
        tickers=[],
        model_name="test-model",
        model_provider="test-provider",
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        pipeline=pipeline,
        cache_benchmark=True,
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert benchmark_calls == []
    assert summary["data_cache_benchmark"] == {
        "requested": True,
        "executed": False,
        "write_status": "skipped",
        "reason": "no benchmark ticker available",
    }
    assert summary["data_cache_benchmark_status"] == {
        "requested": True,
        "executed": False,
        "write_status": "skipped",
        "reason": "no benchmark ticker available",
    }


def test_run_paper_trading_session_replays_frozen_current_plans(tmp_path, monkeypatch):
    metrics_summary_path = tmp_path / "llm_metrics.summary.json"
    metrics_jsonl_path = tmp_path / "llm_metrics.jsonl"
    metrics_summary_path.write_text(
        json.dumps(
            {
                "totals": {
                    "attempts": 12,
                    "successes": 10,
                    "errors": 2,
                    "rate_limit_errors": 2,
                    "fallback_attempts": 3,
                },
                "providers": {
                    "MiniMax": {"attempts": 9},
                    "Volcengine Ark": {"attempts": 3},
                },
                "models": {
                    "MiniMax:MiniMax-M2.7": {"attempts": 9},
                    "Volcengine Ark:doubao-seed-2.0-pro": {"attempts": 3},
                },
                "routes": {
                    "MiniMax:default": {"attempts": 9},
                    "Volcengine Ark:default": {"attempts": 3},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    metrics_jsonl_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "trade_date": "20240301",
                        "pipeline_stage": "daily_pipeline_post_market",
                        "model_tier": "fast",
                        "model_provider": "MiniMax",
                        "success": True,
                        "is_rate_limit": False,
                        "used_fallback": False,
                        "duration_ms": 1200.0,
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "trade_date": "20240301",
                        "pipeline_stage": "daily_pipeline_post_market",
                        "model_tier": "fast",
                        "model_provider": "Volcengine Ark",
                        "success": False,
                        "error_type": "RateLimitError",
                        "error_message": "provider burst limit exceeded",
                        "is_rate_limit": True,
                        "used_fallback": True,
                        "duration_ms": 2200.0,
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "trade_date": "20240304",
                        "pipeline_stage": "daily_pipeline_post_market",
                        "model_tier": "precise",
                        "model_provider": "MiniMax",
                        "success": True,
                        "is_rate_limit": False,
                        "used_fallback": False,
                        "duration_ms": 3200.0,
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "src.paper_trading.runtime.get_llm_metrics_paths",
        lambda: {
            "session_id": "replay-session",
            "summary_path": str(metrics_summary_path),
            "jsonl_path": str(metrics_jsonl_path),
        },
    )

    _patch_market_data(
        monkeypatch,
        {
            "AAPL": {
                "2024-03-01": 10.0,
                "2024-03-04": 11.0,
            },
            "SPY": {
                "2024-03-01": 100.0,
                "2024-03-04": 101.0,
            },
        },
    )
    monkeypatch.setattr("src.execution.daily_pipeline.build_candidate_pool", lambda trade_date: (_ for _ in ()).throw(AssertionError("live pipeline should not run during frozen replay")))

    source_path = tmp_path / "baseline_daily_events.jsonl"
    plan_day_1 = ExecutionPlan(
        date="20240301",
        buy_orders=[PositionPlan(ticker="AAPL", shares=100, amount=1000.0, score_final=0.8, execution_ratio=1.0)],
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={"counts": {"watchlist_count": 1}},
    )
    plan_day_2 = ExecutionPlan(date="20240304", portfolio_snapshot={"cash": 98900.0, "positions": {}})
    source_path.write_text(
        "\n".join(
            [
                json.dumps({"event": "paper_trading_day", "trade_date": "20240301", "current_plan": plan_day_1.model_dump()}, ensure_ascii=False),
                json.dumps({"event": "paper_trading_day", "trade_date": "20240304", "current_plan": plan_day_2.model_dump()}, ensure_ascii=False),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    artifacts = run_paper_trading_session(
        start_date="2024-03-01",
        end_date="2024-03-04",
        output_dir=tmp_path / "paper_trading_replay",
        tickers=["AAPL"],
        model_name="test-model",
        model_provider="test-provider",
        frozen_plan_source=source_path,
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["plan_generation"] == {
        "mode": "frozen_current_plan_replay",
        "frozen_plan_source": str(source_path.resolve()),
        "selection_target": "research_only",
    }
    assert summary["execution_plan_provenance"] == {"observation_count": 0, "observations": []}
    assert summary["llm_route_provenance"]["summary_available"] is True
    assert summary["llm_route_provenance"]["fallback_attempts"] == 3
    assert summary["llm_route_provenance"]["contaminated_by_provider_fallback"] is True
    assert summary["llm_route_provenance"]["providers_seen"] == ["MiniMax", "Volcengine Ark"]
    assert summary["llm_observability_summary"]["jsonl_available"] is True
    assert summary["llm_observability_summary"]["entry_count"] == 3
    assert summary["llm_observability_summary"]["by_trade_date"]["20240301"]["attempts"] == 2
    assert summary["llm_observability_summary"]["by_model_tier"]["fast"]["attempts"] == 2
    assert summary["llm_observability_summary"]["by_provider"]["Volcengine Ark"]["rate_limit_errors"] == 1
    assert summary["llm_observability_summary"]["error_type_counts"] == {"RateLimitError": 1}
    assert summary["llm_observability_summary"]["sample_errors"] == [
        {
            "trade_date": "20240301",
            "pipeline_stage": "daily_pipeline_post_market",
            "model_tier": "fast",
            "provider": "Volcengine Ark",
            "error_type": "RateLimitError",
            "message": "provider burst limit exceeded",
        }
    ]
    assert summary["llm_observability_summary"]["context_breakdown"] == [
        {
            "trade_date": "20240301",
            "pipeline_stage": "daily_pipeline_post_market",
            "model_tier": "fast",
            "provider": "MiniMax",
            "attempts": 1,
            "successes": 1,
            "errors": 0,
            "rate_limit_errors": 0,
            "fallback_attempts": 0,
            "total_duration_ms": 1200.0,
            "avg_duration_ms": 1200.0,
            "error_types": {},
        },
        {
            "trade_date": "20240301",
            "pipeline_stage": "daily_pipeline_post_market",
            "model_tier": "fast",
            "provider": "Volcengine Ark",
            "attempts": 1,
            "successes": 0,
            "errors": 1,
            "rate_limit_errors": 1,
            "fallback_attempts": 1,
            "total_duration_ms": 2200.0,
            "avg_duration_ms": 2200.0,
            "error_types": {"RateLimitError": 1},
        },
        {
            "trade_date": "20240304",
            "pipeline_stage": "daily_pipeline_post_market",
            "model_tier": "precise",
            "provider": "MiniMax",
            "attempts": 1,
            "successes": 1,
            "errors": 0,
            "rate_limit_errors": 0,
            "fallback_attempts": 0,
            "total_duration_ms": 3200.0,
            "avg_duration_ms": 3200.0,
            "error_types": {},
        },
    ]
    assert summary["llm_error_digest"] == {
        "status": "degraded",
        "error_count": 2,
        "rate_limit_error_count": 2,
        "fallback_attempt_count": 3,
        "affected_provider_count": 1,
        "top_error_types": [{"error_type": "RateLimitError", "count": 1}],
        "affected_providers": [
            {
                "provider": "Volcengine Ark",
                "attempts": 1,
                "errors": 1,
                "error_rate": 1.0,
                "rate_limit_errors": 1,
                "fallback_attempts": 1,
                "top_error_types": [{"error_type": "RateLimitError", "count": 1}],
            }
        ],
        "sample_errors": [
            {
                "trade_date": "20240301",
                "pipeline_stage": "daily_pipeline_post_market",
                "model_tier": "fast",
                "provider": "Volcengine Ark",
                "error_type": "RateLimitError",
                "message": "provider burst limit exceeded",
            }
        ],
        "fallback_gap_detected": False,
        "recommendation": "rate_limit_pressure_detected_consider_cooldown_or_concurrency_reduction",
    }
    assert summary["final_portfolio_snapshot"]["positions"]["AAPL"]["long"] == 100

    lines = [json.loads(line) for line in artifacts.daily_events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines[0]["current_plan"]["date"] == "20240301"
    assert lines[-1]["current_plan"]["date"] == "20240304"
    assert lines[0]["execution_plan_provenance"] == []

    timing_lines = [json.loads(line) for line in artifacts.timing_log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    replay_day_timing = next(line for line in timing_lines if line.get("event") == "pipeline_day_timing" and line.get("trade_date") == "20240301")
    assert replay_day_timing["execution_plan_provenance"] == []


def test_run_paper_trading_session_frozen_replay_long_window_preserves_artifact_and_log_consistency(tmp_path, monkeypatch):
    metrics_summary_path = tmp_path / "llm_metrics_long_window.summary.json"
    metrics_jsonl_path = tmp_path / "llm_metrics_long_window.jsonl"
    monkeypatch.setattr(
        "src.paper_trading.runtime.get_llm_metrics_paths",
        lambda: {
            "session_id": "replay-session-long-window",
            "summary_path": str(metrics_summary_path),
            "jsonl_path": str(metrics_jsonl_path),
        },
    )

    _patch_market_data(
        monkeypatch,
        {
            "AAPL": {
                "2024-03-01": 10.0,
                "2024-03-04": 10.8,
                "2024-03-05": 11.1,
                "2024-03-06": 11.4,
                "2024-03-07": 11.7,
            },
            "MSFT": {
                "2024-03-01": 20.0,
                "2024-03-04": 20.5,
                "2024-03-05": 20.8,
                "2024-03-06": 21.0,
                "2024-03-07": 21.3,
            },
            "SPY": {
                "2024-03-01": 100.0,
                "2024-03-04": 100.8,
                "2024-03-05": 101.2,
                "2024-03-06": 101.7,
                "2024-03-07": 102.0,
            },
        },
    )
    monkeypatch.setattr("src.execution.daily_pipeline.build_candidate_pool", lambda trade_date: (_ for _ in ()).throw(AssertionError("live pipeline should not run during frozen replay")))

    source_path = tmp_path / "baseline_long_window_daily_events.jsonl"
    trade_dates = ["20240301", "20240304", "20240305", "20240306", "20240307"]
    plans = [
        ExecutionPlan(
            date=trade_date,
            buy_orders=[PositionPlan(ticker="AAPL" if index % 2 == 0 else "MSFT", shares=100, amount=1000.0 + index * 100.0, score_final=0.8 - index * 0.02, execution_ratio=1.0)],
            portfolio_snapshot={"cash": 100000.0 - index * 500.0, "positions": {}},
            risk_metrics={"counts": {"watchlist_count": 1, "candidate_count": 8 - index}},
        )
        for index, trade_date in enumerate(trade_dates)
    ]
    source_path.write_text(
        "\n".join(
            json.dumps({"event": "paper_trading_day", "trade_date": trade_date, "current_plan": plan.model_dump()}, ensure_ascii=False)
            for trade_date, plan in zip(trade_dates, plans, strict=True)
        )
        + "\n",
        encoding="utf-8",
    )

    artifacts = run_paper_trading_session(
        start_date="2024-03-01",
        end_date="2024-03-07",
        output_dir=tmp_path / "paper_trading_replay_long_window",
        tickers=["AAPL", "MSFT"],
        model_name="test-model",
        model_provider="test-provider",
        frozen_plan_source=source_path,
    )

    expected_artifact_dates = ["2024-03-01", "2024-03-04", "2024-03-05", "2024-03-06", "2024-03-07"]
    for trade_date in expected_artifact_dates:
        day_dir = artifacts.selection_artifact_root / trade_date
        assert (day_dir / "selection_snapshot.json").exists()
        assert (day_dir / "selection_review.md").exists()
        assert (day_dir / "research_feedback.jsonl").exists()

    lines = [json.loads(line) for line in artifacts.daily_events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [line["trade_date"] for line in lines] == trade_dates
    assert all(line["current_plan"]["selection_artifacts"]["write_status"] == "success" for line in lines)
    assert [line["current_plan"]["selection_artifacts"]["snapshot_path"].split("/")[-2] for line in lines] == expected_artifact_dates

    timing_lines = [json.loads(line) for line in artifacts.timing_log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    replay_day_timings = [line for line in timing_lines if line.get("event") == "pipeline_day_timing"]
    assert [line["trade_date"] for line in replay_day_timings] == trade_dates
    assert all(line["current_plan"]["selection_artifacts"]["write_status"] == "success" for line in replay_day_timings)
    assert all(line["execution_plan_provenance"] == [] for line in replay_day_timings)

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["plan_generation"] == {
        "mode": "frozen_current_plan_replay",
        "frozen_plan_source": str(source_path.resolve()),
        "selection_target": "research_only",
    }
    assert summary["daily_event_stats"]["day_count"] == 5
    assert summary["research_feedback_summary"]["feedback_file_count"] == 5
    assert summary["research_feedback_summary"]["trade_date_count"] == 5
    assert sorted(summary["research_feedback_summary"]["by_trade_date"].keys()) == expected_artifact_dates
    assert summary["execution_plan_provenance"] == {"observation_count": 0, "observations": []}
