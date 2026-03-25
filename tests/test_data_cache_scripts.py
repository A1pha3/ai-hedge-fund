from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import benchmark_data_cache_reuse, manage_data_cache, validate_data_cache_reuse
from src.data import cache_benchmark
from src.data import enhanced_cache as enhanced_cache_module
from src.data.enhanced_cache import DiskCache, EnhancedCache, clear_cache, diff_cache_stats, get_cache_runtime_info


def test_diff_cache_stats_returns_run_delta():
    before = {
        "lru_hits": 1,
        "redis_hits": 2,
        "disk_hits": 3,
        "misses": 4,
        "sets": 5,
        "total_hits": 6,
        "total_requests": 10,
    }
    after = {
        "lru_hits": 3,
        "redis_hits": 2,
        "disk_hits": 7,
        "misses": 5,
        "sets": 8,
        "total_hits": 12,
        "total_requests": 17,
    }

    delta = diff_cache_stats(before, after)

    assert delta == {
        "lru_hits": 2,
        "redis_hits": 0,
        "disk_hits": 4,
        "misses": 1,
        "sets": 3,
        "total_hits": 6,
        "total_requests": 7,
        "hit_rate": 0.8571,
    }


def test_disk_cache_persists_across_instances_and_clear(tmp_path: Path):
    cache_path = tmp_path / "cache.sqlite"

    writer = DiskCache(path=str(cache_path), default_ttl=3600)
    writer.set("selection:test", {"rows": 3}, ttl=3600)
    assert writer.count_entries() == 1
    assert writer.get_file_size_bytes() > 0

    reader = DiskCache(path=str(cache_path), default_ttl=3600)
    assert reader.get("selection:test") == {"rows": 3}

    reader.clear()

    verifier = DiskCache(path=str(cache_path), default_ttl=3600)
    assert verifier.get("selection:test") is None


def test_get_cache_runtime_info_and_clear_cache_use_temp_disk_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cache_path = tmp_path / "runtime-cache.sqlite"
    temp_cache = EnhancedCache(disk_path=str(cache_path))

    monkeypatch.setattr(enhanced_cache_module, "_enhanced_cache", temp_cache)

    temp_cache.set("selection:test", {"rows": 2}, ttl=3600)
    first_read = temp_cache.get("selection:test")
    runtime_before_clear = get_cache_runtime_info()

    clear_cache()
    runtime_after_clear = get_cache_runtime_info()
    reloaded_cache = DiskCache(path=str(cache_path), default_ttl=3600)

    assert first_read == {"rows": 2}
    assert runtime_before_clear["disk_available"] is True
    assert runtime_before_clear["disk_path"] == str(cache_path)
    assert runtime_before_clear["disk_entry_count"] == 1
    assert runtime_before_clear["disk_file_size_bytes"] > 0
    assert runtime_before_clear["stats"]["sets"] == 1
    assert runtime_before_clear["stats"]["total_hits"] == 1
    assert reloaded_cache.get("selection:test") is None
    assert runtime_after_clear["disk_path"] == str(cache_path)
    assert runtime_after_clear["disk_entry_count"] == 0


def test_manage_data_cache_stats_command_writes_output(tmp_path, monkeypatch: pytest.MonkeyPatch):
    payload = {
        "lru_maxsize": 128,
        "redis_available": False,
        "disk_available": True,
        "disk_path": "/tmp/cache.sqlite",
        "disk_entry_count": 12,
        "disk_file_size_bytes": 4096,
        "stats": {"disk_hits": 6},
    }
    output_path = tmp_path / "cache_stats.json"

    monkeypatch.setattr("scripts.manage_data_cache.get_cache_runtime_info", lambda: payload)

    result = manage_data_cache._stats_command(str(output_path))

    assert result == payload
    assert json.loads(output_path.read_text(encoding="utf-8")) == payload


def test_manage_data_cache_clear_requires_confirmation():
    with pytest.raises(SystemExit, match="without --yes"):
        manage_data_cache._clear_command(False)


def test_manage_data_cache_clear_command_returns_before_after(monkeypatch: pytest.MonkeyPatch):
    snapshots = iter(
        [
            {"stats": {"misses": 3, "sets": 3}},
            {"stats": {"misses": 0, "sets": 0}},
        ]
    )
    clear_calls: list[str] = []

    monkeypatch.setattr("scripts.manage_data_cache.get_cache_runtime_info", lambda: next(snapshots))
    monkeypatch.setattr("scripts.manage_data_cache.clear_cache", lambda: clear_calls.append("cleared"))

    result = manage_data_cache._clear_command(True)

    assert result == {
        "status": "cleared",
        "before": {"stats": {"misses": 3, "sets": 3}},
        "after": {"stats": {"misses": 0, "sets": 0}},
    }
    assert clear_calls == ["cleared"]


def test_manage_data_cache_main_prints_stats_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    payload = {
        "lru_maxsize": 128,
        "redis_available": False,
        "disk_available": True,
        "disk_path": "/tmp/cache.sqlite",
        "disk_entry_count": 12,
        "disk_file_size_bytes": 4096,
        "stats": {"total_requests": 6},
    }

    monkeypatch.setattr("sys.argv", ["manage_data_cache.py", "stats"])
    monkeypatch.setattr("scripts.manage_data_cache.get_cache_runtime_info", lambda: payload)

    manage_data_cache.main()

    assert json.loads(capsys.readouterr().out) == payload


def test_manage_data_cache_main_prints_clear_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    payload = {
        "status": "cleared",
        "before": {"stats": {"misses": 2, "sets": 2}},
        "after": {"stats": {"misses": 0, "sets": 0}},
    }

    monkeypatch.setattr("sys.argv", ["manage_data_cache.py", "clear", "--yes"])
    monkeypatch.setattr("scripts.manage_data_cache._clear_command", lambda confirm: payload if confirm else None)

    manage_data_cache.main()

    assert json.loads(capsys.readouterr().out) == payload


def test_validate_data_cache_reuse_main_writes_payload(tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    output_path = tmp_path / "validation.json"
    before = {
        "lru_hits": 1,
        "redis_hits": 0,
        "disk_hits": 2,
        "misses": 3,
        "sets": 4,
        "total_hits": 3,
        "total_requests": 6,
    }
    runtime = {
        "lru_maxsize": 128,
        "redis_available": False,
        "disk_available": True,
        "disk_path": "/tmp/cache.sqlite",
        "disk_entry_count": 12,
        "disk_file_size_bytes": 4096,
        "stats": {
            "lru_hits": 2,
            "redis_hits": 0,
            "disk_hits": 5,
            "misses": 3,
            "sets": 4,
            "total_hits": 7,
            "total_requests": 10,
        },
    }

    monkeypatch.setattr(
        "sys.argv",
        [
            "validate_data_cache_reuse.py",
            "--trade-date",
            "20260324",
            "--ticker",
            "300724",
            "--output",
            str(output_path),
        ],
    )
    monkeypatch.setattr("scripts.validate_data_cache_reuse.snapshot_cache_stats", lambda: before)
    monkeypatch.setattr("scripts.validate_data_cache_reuse.get_cache_runtime_info", lambda: runtime)
    monkeypatch.setattr("scripts.validate_data_cache_reuse.get_all_stock_basic", lambda: [1, 2, 3])
    monkeypatch.setattr("scripts.validate_data_cache_reuse.get_daily_basic_batch", lambda trade_date: [trade_date, "x"])
    monkeypatch.setattr("scripts.validate_data_cache_reuse.get_limit_list", lambda trade_date: [trade_date])
    monkeypatch.setattr("scripts.validate_data_cache_reuse.get_suspend_list", lambda trade_date: [])
    monkeypatch.setattr(
        "scripts.validate_data_cache_reuse.get_stock_details",
        lambda ticker, trade_date: {"ticker": ticker, "trade_date": trade_date, "name": "捷佳伟创"},
    )

    validate_data_cache_reuse.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload == json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["trade_date"] == "20260324"
    assert payload["ticker"] == "300724"
    assert payload["cache_runtime"] == runtime
    assert payload["session_stats"] == {
        "lru_hits": 1,
        "redis_hits": 0,
        "disk_hits": 3,
        "misses": 0,
        "sets": 0,
        "total_hits": 4,
        "total_requests": 4,
        "hit_rate": 1.0,
    }
    assert payload["result_shapes"] == {
        "stock_basic_rows": 3,
        "daily_basic_rows": 2,
        "limit_list_rows": 1,
        "suspend_list_rows": 0,
    }
    assert payload["stock_details"] == {"ticker": "300724", "trade_date": "20260324", "name": "捷佳伟创"}


def test_benchmark_data_cache_reuse_builds_validation_command():
    command = cache_benchmark.build_validation_command(
        python_executable="/tmp/python",
        repo_root=Path("/repo"),
        trade_date="20260324",
        ticker="300724",
    )

    assert command == [
        "/tmp/python",
        "/repo/scripts/validate_data_cache_reuse.py",
        "--trade-date",
        "20260324",
        "--ticker",
        "300724",
    ]


def test_benchmark_data_cache_reuse_summarizes_cold_and_warm_runs():
    first_run = {
        "session_stats": {"disk_hits": 0, "misses": 6, "sets": 6, "hit_rate": 0.0},
        "result_shapes": {"stock_basic_rows": 3, "daily_basic_rows": 2, "limit_list_rows": 1, "suspend_list_rows": 0},
    }
    second_run = {
        "session_stats": {"disk_hits": 6, "misses": 0, "sets": 0, "hit_rate": 1.0},
        "result_shapes": {"stock_basic_rows": 3, "daily_basic_rows": 2, "limit_list_rows": 1, "suspend_list_rows": 0},
    }

    payload = cache_benchmark.summarize_cache_reuse_benchmark(
        first_run=first_run,
        second_run=second_run,
        trade_date="20260324",
        ticker="300724",
        clear_first=True,
    )

    assert payload["trade_date"] == "20260324"
    assert payload["ticker"] == "300724"
    assert payload["clear_first"] is True
    assert payload["summary"] == {
        "first_total_rows": 6,
        "second_total_rows": 6,
        "first_disk_hits": 0,
        "second_disk_hits": 6,
        "first_misses": 6,
        "second_misses": 0,
        "first_sets": 6,
        "second_sets": 0,
        "disk_hit_gain": 6,
        "miss_reduction": 6,
        "set_reduction": 6,
        "first_hit_rate": 0.0,
        "second_hit_rate": 1.0,
        "reuse_confirmed": True,
    }


def test_benchmark_data_cache_reuse_renders_markdown_summary():
    payload = {
        "trade_date": "20260324",
        "ticker": "300724",
        "clear_first": True,
        "summary": {
            "first_total_rows": 6,
            "second_total_rows": 6,
            "first_disk_hits": 0,
            "second_disk_hits": 6,
            "disk_hit_gain": 6,
            "first_misses": 6,
            "second_misses": 0,
            "miss_reduction": 6,
            "first_sets": 6,
            "second_sets": 0,
            "set_reduction": 6,
            "first_hit_rate": 0.0,
            "second_hit_rate": 1.0,
            "reuse_confirmed": True,
        },
    }

    markdown = cache_benchmark.render_cache_benchmark_markdown(payload)

    assert "# Data Cache Benchmark - 20260324 - 300724" in markdown
    assert "- clear_first: yes" in markdown
    assert "- reuse_confirmed: confirmed" in markdown
    assert "- disk_hit_gain: 6" in markdown
    assert "- miss_reduction: 6" in markdown
    assert markdown.endswith("\n")


def test_benchmark_data_cache_reuse_appends_markdown_summary(tmp_path: Path):
    report_path = tmp_path / "window_review.md"
    report_path.write_text("# Existing Review\n", encoding="utf-8")

    cache_benchmark.append_cache_benchmark_markdown(str(report_path), "# Data Cache Benchmark - 20260324 - 300724\n")

    updated = report_path.read_text(encoding="utf-8")
    assert updated.startswith("# Existing Review\n")
    assert "# Data Cache Benchmark - 20260324 - 300724\n" in updated


def test_benchmark_data_cache_reuse_main_runs_twice_and_writes_output(tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    output_path = tmp_path / "benchmark.json"
    markdown_path = tmp_path / "benchmark.md"
    report_path = tmp_path / "window_review.md"
    completed_runs = iter(
        [
            SimpleNamespace(returncode=0, stdout=json.dumps({"session_stats": {"disk_hits": 0, "misses": 6, "sets": 6, "hit_rate": 0.0}, "result_shapes": {"stock_basic_rows": 3, "daily_basic_rows": 2, "limit_list_rows": 1, "suspend_list_rows": 0}}), stderr=""),
            SimpleNamespace(returncode=0, stdout=json.dumps({"session_stats": {"disk_hits": 6, "misses": 0, "sets": 0, "hit_rate": 1.0}, "result_shapes": {"stock_basic_rows": 3, "daily_basic_rows": 2, "limit_list_rows": 1, "suspend_list_rows": 0}}), stderr=""),
        ]
    )
    benchmark_calls: list[dict] = []

    def _fake_run_cache_reuse_benchmark(**kwargs):
        benchmark_calls.append(kwargs)
        first_run = json.loads(next(completed_runs).stdout)
        second_run = json.loads(next(completed_runs).stdout)
        payload = cache_benchmark.summarize_cache_reuse_benchmark(
            first_run=first_run,
            second_run=second_run,
            trade_date=kwargs["trade_date"],
            ticker=kwargs["ticker"],
            clear_first=kwargs["clear_first"],
        )
        Path(kwargs["output_path"]).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        markdown = cache_benchmark.render_cache_benchmark_markdown(payload)
        Path(kwargs["markdown_output_path"]).write_text(markdown, encoding="utf-8")
        cache_benchmark.append_cache_benchmark_markdown(kwargs["append_markdown_to"], markdown)
        return payload

    monkeypatch.setattr(
        "sys.argv",
        [
            "benchmark_data_cache_reuse.py",
            "--trade-date",
            "20260324",
            "--ticker",
            "300724",
            "--clear-first",
            "--output",
            str(output_path),
            "--markdown-output",
            str(markdown_path),
            "--append-markdown-to",
            str(report_path),
        ],
    )
    monkeypatch.setattr("scripts.benchmark_data_cache_reuse.run_cache_reuse_benchmark", _fake_run_cache_reuse_benchmark)

    benchmark_data_cache_reuse.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload == json.loads(output_path.read_text(encoding="utf-8"))
    assert markdown_path.read_text(encoding="utf-8").startswith("# Data Cache Benchmark - 20260324 - 300724")
    assert report_path.read_text(encoding="utf-8").startswith("# Data Cache Benchmark - 20260324 - 300724")
    assert len(benchmark_calls) == 1
    assert benchmark_calls[0]["clear_first"] is True
    assert benchmark_calls[0]["trade_date"] == "20260324"
    assert benchmark_calls[0]["ticker"] == "300724"
    assert payload["summary"]["reuse_confirmed"] is True
    assert payload["summary"]["disk_hit_gain"] == 6