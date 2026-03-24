from __future__ import annotations

import json

import pandas as pd

from src.execution.models import ExecutionPlan
from src.paper_trading.runtime import run_paper_trading_session
from src.portfolio.models import PositionPlan


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

    monkeypatch.setattr("src.backtesting.engine.DailyPipeline", AutoPipeline)

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