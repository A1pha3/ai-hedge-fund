from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

import pytest


def test_auto_cli_accepts_strict_quality_flag():
    from src.cli.input import add_common_args

    parser = argparse.ArgumentParser()
    add_common_args(parser, require_tickers=False)
    args = parser.parse_args(["--auto", "--strict-quality"])
    assert args.auto is True
    assert args.strict_quality is True


@dataclass
class _FakeRefreshStats:
    price_total: int = 3
    price_updated: int = 2
    price_missing: int = 0
    price_insufficient_history: int = 0
    fund_flow_total: int = 3
    fund_flow_saved: int = 1
    fund_flow_empty: int = 0
    price_failed: int = 0
    fund_flow_failed: int = 0
    industry_index_failed: int = 0

    def to_dict(self) -> dict:
        return {
            "price_total": self.price_total,
            "price_updated": self.price_updated,
            "price_missing": self.price_missing,
            "price_insufficient_history": self.price_insufficient_history,
            "fund_flow_total": self.fund_flow_total,
            "fund_flow_saved": self.fund_flow_saved,
            "fund_flow_empty": self.fund_flow_empty,
            "price_failed": self.price_failed,
            "fund_flow_failed": self.fund_flow_failed,
            "industry_index_failed": self.industry_index_failed,
        }


def test_refresh_daily_action_caches_for_auto_attaches_summary_without_publishing(monkeypatch):
    from src import main as main_mod

    saved: list[tuple[str, dict]] = []
    payload = {"date": "20260708", "recommendations": []}

    monkeypatch.delenv("DAILY_ACTION_CACHE_REFRESH", raising=False)
    monkeypatch.setattr(main_mod, "_save_json_report", lambda filename, body: saved.append((filename, dict(body))))

    main_mod._refresh_daily_action_caches_for_auto(
        "20260708",
        payload,
        refresh_fn=lambda trade_date: _FakeRefreshStats(),
    )

    assert payload["daily_action_cache_refresh"] == {
        "status": "success",
        "price_total": 3,
        "price_updated": 2,
        "price_missing": 0,
        "price_insufficient_history": 0,
        "fund_flow_total": 3,
        "fund_flow_saved": 1,
        "fund_flow_empty": 0,
        "price_failed": 0,
        "fund_flow_failed": 0,
        "industry_index_failed": 0,
    }
    assert saved == []


def test_compute_auto_screening_results_does_not_publish_report(monkeypatch):
    """Compute is publication-free; only auto_pipeline may publish canonical."""
    from src import main as main_mod

    source = main_mod.compute_auto_screening_results
    assert "_save_json_report" not in source.__code__.co_names


def test_run_auto_screening_busy_returns_temporary_failure(monkeypatch):
    from src import main as main_mod

    monkeypatch.setattr(main_mod, "_try_acquire_pipeline_lock", lambda _path: None)
    monkeypatch.setattr(
        "src.utils.date_utils.latest_open_trade_date_on_or_before",
        lambda value: value,
    )

    assert main_mod.run_auto_screening("20260710") == 75


def test_run_auto_screening_closes_lock_fd_when_pipeline_returns(monkeypatch):
    from src import main as main_mod

    closed: list[int] = []
    monkeypatch.setattr(main_mod, "_try_acquire_pipeline_lock", lambda _path: 321)
    monkeypatch.setattr(main_mod.os, "close", closed.append)
    monkeypatch.setattr(
        "src.utils.date_utils.latest_open_trade_date_on_or_before",
        lambda value: value,
    )
    monkeypatch.setattr(
        "src.screening.auto_pipeline.run_auto_pipeline",
        lambda *args, **kwargs: __import__(
            "src.screening.auto_pipeline", fromlist=["AutoRunResult"]
        ).AutoRunResult(
            status=__import__(
                "src.screening.auto_pipeline", fromlist=["AutoRunStatus"]
            ).AutoRunStatus.HEALTHY,
            exit_code=0,
            artifact_path=None,
            payload=None,
            manifest=None,
        ),
    )

    assert main_mod.run_auto_screening("20260710") == 0
    assert closed == [321]


def test_run_auto_screening_closes_lock_fd_when_delegate_raises(monkeypatch):
    from src import main as main_mod

    closed: list[int] = []
    monkeypatch.setattr(main_mod, "_try_acquire_pipeline_lock", lambda _path: 654)
    monkeypatch.setattr(main_mod.os, "close", closed.append)
    monkeypatch.setattr(
        "src.utils.date_utils.latest_open_trade_date_on_or_before",
        lambda value: value,
    )

    def explode(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("src.screening.auto_pipeline.run_auto_pipeline", explode)

    with pytest.raises(KeyboardInterrupt):
        main_mod.run_auto_screening("20260710")
    assert closed == [654]


def test_recovery_delegate_runs_before_any_preheat_or_new_input_work(monkeypatch):
    from src import main as main_mod
    from src.screening.auto_pipeline import AutoRunResult, AutoRunStatus

    events: list[str] = []
    fd = os.open("/dev/null", os.O_RDONLY)
    monkeypatch.setenv("PREHEAT_BEFORE_AUTO", "true")
    monkeypatch.setattr(main_mod, "_try_acquire_pipeline_lock", lambda _path: fd)
    monkeypatch.setattr(
        "src.utils.date_utils.latest_open_trade_date_on_or_before",
        lambda value: value,
    )
    monkeypatch.setattr(
        "src.data.cache_preheater.preheat_cache",
        lambda *args, **kwargs: events.append("preheat"),
    )

    def recovered(*args, **kwargs):
        events.append("pipeline")
        return AutoRunResult(
            AutoRunStatus.FATAL,
            1,
            Path("pending.json"),
            None,
            None,
            recovered=True,
            recovery_diagnostics=({"action": "recovery_failed"},),
        )

    monkeypatch.setattr(
        "src.screening.auto_pipeline.run_auto_pipeline",
        recovered,
    )

    assert main_mod.run_auto_screening("20260710") == 1
    assert events == ["pipeline"]


def test_run_auto_screening_closes_lock_fd_when_progress_start_raises(monkeypatch):
    from src import main as main_mod

    closed: list[int] = []
    monkeypatch.setattr(main_mod, "_try_acquire_pipeline_lock", lambda _path: 655)
    monkeypatch.setattr(main_mod.os, "close", closed.append)
    monkeypatch.setattr(main_mod.progress, "start", lambda: (_ for _ in ()).throw(RuntimeError("progress failed")))
    monkeypatch.setattr(
        "src.utils.date_utils.latest_open_trade_date_on_or_before",
        lambda value: value,
    )

    with pytest.raises(RuntimeError, match="progress failed"):
        main_mod.run_auto_screening("20260710")
    assert closed == [655]


def test_degraded_run_skips_watchlist_pdf_rebalance_and_push(monkeypatch):
    from src import main as main_mod
    from src.screening.auto_pipeline import AutoRunResult, AutoRunStatus

    payload = {
        "date": "20260710",
        "recommendations": [],
        "market_state": {},
        "batch_data_fetcher": {},
        "layer_a_count": 0,
        "sector_concentration_warnings": [],
    }
    fd = os.open("/dev/null", os.O_RDONLY)
    monkeypatch.setattr(main_mod, "_try_acquire_pipeline_lock", lambda _path: fd)
    monkeypatch.setattr(
        "src.utils.date_utils.latest_open_trade_date_on_or_before",
        lambda value: value,
    )
    monkeypatch.setattr(
        "src.screening.auto_pipeline.run_auto_pipeline",
        lambda *args, **kwargs: AutoRunResult(
            AutoRunStatus.DEGRADED,
            3,
            Path("attempt.json"),
            payload,
            object(),
        ),
    )
    monkeypatch.setattr(main_mod, "_rebuild_cli_objects", lambda _payload: ([], object(), [], {}, {}))
    monkeypatch.setattr(main_mod, "_print_table_block", lambda **kwargs: None)
    monkeypatch.setattr(
        main_mod,
        "_enrich_recommendations_with_history",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("degraded run must not enrich")),
    )
    monkeypatch.setattr(
        main_mod,
        "_handle_post_screening_tasks",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("degraded run must not push")),
    )

    assert main_mod.run_auto_screening("20260710", strict_quality=True) == 3


def test_run_auto_screening_releases_pipeline_lock_before_post_processing(monkeypatch):
    from src import main as main_mod
    from src.screening.auto_pipeline import AutoRunResult, AutoRunStatus

    closed: list[int] = []
    payload = {
        "date": "20260710",
        "recommendations": [],
        "market_state": {},
        "batch_data_fetcher": {},
    }
    monkeypatch.setattr(main_mod, "_try_acquire_pipeline_lock", lambda _path: 777)
    monkeypatch.setattr(main_mod.os, "close", closed.append)
    monkeypatch.setattr(
        "src.utils.date_utils.latest_open_trade_date_on_or_before",
        lambda value: value,
    )
    monkeypatch.setattr(
        "src.screening.auto_pipeline.run_auto_pipeline",
        lambda *args, **kwargs: AutoRunResult(
            AutoRunStatus.HEALTHY,
            0,
            Path("report.json"),
            payload,
            object(),
        ),
    )

    def assert_released(_payload):
        assert closed == [777]
        raise RuntimeError("post-processing sentinel")

    monkeypatch.setattr(main_mod, "_rebuild_cli_objects", assert_released)

    with pytest.raises(RuntimeError, match="post-processing sentinel"):
        main_mod.run_auto_screening("20260710")
    assert closed == [777]


def test_refresh_daily_action_caches_for_auto_respects_env_kill_switch(monkeypatch):
    from src import main as main_mod

    called = False
    payload = {"date": "20260708", "recommendations": []}

    def refresh_fn(_trade_date: str):
        nonlocal called
        called = True
        return _FakeRefreshStats()

    monkeypatch.setenv("DAILY_ACTION_CACHE_REFRESH", "false")
    monkeypatch.setattr(main_mod, "_save_json_report", lambda *_args, **_kwargs: None)

    main_mod._refresh_daily_action_caches_for_auto("20260708", payload, refresh_fn=refresh_fn)

    assert called is False
    assert "daily_action_cache_refresh" not in payload


def test_attach_freshness_check_adds_data_freshness_field(monkeypatch):
    """_attach_freshness_check should attach data_freshness to report_payload."""
    from src import main as main_mod

    payload: dict = {"date": "20260708", "recommendations": []}

    def fake_check(*, trade_date: str, **kwargs) -> dict:
        assert trade_date == "20260708"
        return {
            "fresh": True,
            "trade_date": "20260708",
            "warnings": [],
            "warning_count": 0,
            "summary": "全部数据源新鲜",
        }

    monkeypatch.setattr("src.screening.data_freshness_guard.check_data_freshness", fake_check)

    main_mod._attach_freshness_check("20260708", payload)
    assert "data_freshness" in payload
    assert payload["data_freshness"]["fresh"] is True


def test_attach_freshness_check_handles_exception_gracefully(monkeypatch):
    """If check_data_freshness raises, _attach_freshness_check should not crash."""
    from src import main as main_mod

    payload: dict = {"date": "20260708", "recommendations": []}

    def fake_check(*, trade_date: str, **kwargs) -> dict:
        raise RuntimeError("cache unreachable")

    monkeypatch.setattr("src.screening.data_freshness_guard.check_data_freshness", fake_check)

    main_mod._attach_freshness_check("20260708", payload)
    assert "data_freshness" not in payload  # no field on failure


def test_attach_freshness_check_stale_data_prints_warning(monkeypatch, capsys):
    """If data is stale, _attach_freshness_check prints a warning line (not fatal)."""
    from src import main as main_mod

    payload: dict = {"date": "20260708", "recommendations": []}

    def fake_check(*, trade_date: str, **kwargs) -> dict:
        return {
            "fresh": False,
            "trade_date": "20260708",
            "warnings": [{"source": "fund_flow", "label": "资金流向", "latest_date": "20260701", "stale_days": 7, "max_stale_days": 3, "severity": "HIGH", "message": "资金流数据 7 天未更新"}],
            "warning_count": 1,
            "summary": "资金流向: 7 天未更新",
        }

    monkeypatch.setattr("src.screening.data_freshness_guard.check_data_freshness", fake_check)

    main_mod._attach_freshness_check("20260708", payload)
    captured = capsys.readouterr()
    assert "资金流向" in captured.out
