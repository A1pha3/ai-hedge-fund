from __future__ import annotations

import json
from pathlib import Path
import sys

import pandas as pd

from src.execution.models import ExecutionPlan
from src.execution.models import LayerCResult
from src.paper_trading.runtime import run_paper_trading_session
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
        },
    ]
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