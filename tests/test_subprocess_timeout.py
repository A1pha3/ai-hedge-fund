from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _import_runner(name: str):
    """Import a script as a module without executing main()."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_run_btst_march_backtest_refresh_runner_passes_timeout(monkeypatch) -> None:
    """_run() must forward a finite ``timeout=`` to subprocess.run so that
    a hung child cannot wedge the daily refresh orchestrator forever.
    """
    runner = _import_runner("run_btst_march_backtest_refresh")

    captured: dict = {}

    class _StubCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    def _stub_run(command, *, cwd, text, capture_output, check, timeout):
        captured["timeout"] = timeout
        captured["command"] = command
        return _StubCompleted()

    monkeypatch.setattr(runner.subprocess, "run", _stub_run)

    result = runner._run([sys.executable, "-c", "pass"], cwd=SCRIPTS_DIR)

    assert result.returncode == 0
    assert captured["timeout"] is not None
    assert captured["timeout"] > 0


def test_run_paper_trading_gate_experiments_runner_passes_timeout(monkeypatch) -> None:
    """The gate-experiments orchestrator must also gate subprocess.run
    with an explicit timeout — the previous version left it implicit,
    which is a known anti-pattern.
    """
    import argparse

    runner = _import_runner("run_paper_trading_gate_experiments")

    captured: dict = {}

    def _stub_run(command, *, cwd, env, capture_output, text, check, timeout):
        captured["timeout"] = timeout

        class _Done:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Done()

    monkeypatch.setattr(runner.subprocess, "run", _stub_run)

    fake_args = argparse.Namespace(
        start_date="2026-01-01",
        end_date="2026-01-02",
        initial_capital=100000.0,
        model_name=None,
        model_provider=None,
        frozen_plan_source=str(SCRIPTS_DIR / "missing.jsonl"),
    )

    result = runner._run_variant(
        repo_root=SCRIPTS_DIR,
        output_dir=SCRIPTS_DIR,
        args=fake_args,
        variant_name="unit_test_variant",
        env_updates={},
    )

    assert result["exit_code"] == 0
    assert captured["timeout"] is not None
    assert captured["timeout"] > 0
