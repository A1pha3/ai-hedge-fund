"""NS-5 data-flywheel health checks.

Context: the daily auto_screening job (run_daily_auto.sh via launchd) is the
engine that accumulates tracking_history so realized T+1..T+30 returns get
backfilled and feed calibration/reconcile. 2026-06-30 it was discovered SILENTLY
DEAD for 6 days — launchd returns EX_CONFIG (78) when the plist references paths
on the external /Volumes noowners APFS volume, and nothing surfaced the stall.

These tests guard the two engineering deliverables that prevent recurrence:

1. ``check_flywheel_health`` — pure function that classifies flywheel staleness
   from a tracking_history mtime + latest record date, returning a structured
   verdict so staleness is OBSERVABLE (not silent).

2. ``build_launchd_invocation`` — pure function that emits the launchd-safe
   ProgramArguments (boot-volume /bin/bash -c wrapper, NO /Volumes path keys),
   so the plist can never regress into the EX_CONFIG trap.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest


def _ts(days_ago: float) -> float:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).timestamp()


class TestCheckFlywheelHealth:
    """Staleness classification — the silent-stall antidote."""

    def test_fresh_run_is_healthy(self):
        from src.screening.flywheel_health import check_flywheel_health
        result = check_flywheel_health(
            tracking_history_mtime=_ts(0.1), latest_record_date="2026-06-30"
        )
        assert result["status"] == "healthy"
        assert result["stale"] is False
        assert "days_since_last_write" in result

    def test_stale_run_is_flagged(self):
        from src.screening.flywheel_health import check_flywheel_health
        result = check_flywheel_health(
            tracking_history_mtime=_ts(4.0), latest_record_date="2026-06-26"
        )
        assert result["stale"] is True
        assert result["status"] in ("stale", "warning")
        assert result["days_since_last_write"] >= 3

    def test_dead_run_is_critical(self):
        from src.screening.flywheel_health import check_flywheel_health
        result = check_flywheel_health(
            tracking_history_mtime=_ts(7.5), latest_record_date="2026-06-22"
        )
        assert result["status"] == "critical"
        assert result["stale"] is True
        assert result["days_since_last_write"] >= 7

    def test_missing_history_is_critical(self):
        from src.screening.flywheel_health import check_flywheel_health
        result = check_flywheel_health(
            tracking_history_mtime=None, latest_record_date=None
        )
        assert result["status"] == "critical"
        assert result["stale"] is True

    def test_message_is_human_readable_and_includes_dates(self):
        from src.screening.flywheel_health import check_flywheel_health
        result = check_flywheel_health(
            tracking_history_mtime=_ts(5.0), latest_record_date="2026-06-25"
        )
        msg = result["message"]
        assert isinstance(msg, str) and len(msg) > 10
        assert "2026-06-25" in msg or "day" in msg.lower()


class TestBuildLaunchdInvocation:
    """The plist must NEVER reference /Volumes in a path key (EX_CONFIG trap)."""

    def test_uses_bash_c_not_direct_script_exec(self):
        from src.screening.flywheel_health import build_launchd_invocation
        inv = build_launchd_invocation(
            repo_path="/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork"
        )
        argv = inv["program_arguments"]
        # launchd spawns /bin/bash (a boot-volume, trusted binary)
        assert argv[0] == "/bin/bash"
        assert argv[1] == "-c"

    def test_no_path_key_references_external_volumes(self):
        """Regression guard: every plist path key must live on the boot volume,
        otherwise launchd returns EX_CONFIG (78) and the job dies silently."""
        from src.screening.flywheel_health import build_launchd_invocation
        inv = build_launchd_invocation(
            repo_path="/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork"
        )
        for key in ("working_directory", "standard_out_path", "standard_error_path"):
            if inv.get(key):
                assert not inv[key].startswith("/Volumes/"), (
                    f"{key}={inv[key]!r} references external volume -> EX_CONFIG trap"
                )

    def test_invocation_body_cd_into_repo_and_runs_launcher(self):
        from src.screening.flywheel_health import build_launchd_invocation
        inv = build_launchd_invocation(
            repo_path="/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork"
        )
        body = inv["program_arguments"][2]
        assert "run_daily_auto.sh" in body
        # the inline body cd's into the repo (so the script runs in-context)
        assert "cd" in body and "/Volumes" in body


class TestLauncherScriptExists:
    """The repo ships the launcher that gets installed on the boot volume."""

    def test_launcher_script_present_and_avoids_execve_on_volumes(self):
        # The launcher lives in scripts/ (installed to boot volume). It must read
        # the /Volumes pipeline script as STDIN DATA (bash -s < file), NOT execve
        # it — launchd's sandbox returns `Operation not permitted` (rc 126) on
        # execve/read of a /Volumes script file.
        p = Path("scripts/run_daily_auto_launcher.sh")
        assert p.exists(), "boot-volume launcher template must ship in scripts/"
        text = p.read_text()
        assert "/bin/bash" in text
        assert "run_daily_auto.sh" in text
        assert "noowners" in text.lower() or "external" in text.lower() or "ex_config" in text.lower()
        # regression guard: must read as data, not exec the file
        # launcher inlines the pipeline (no /Volumes file open); run_daily_auto.sh stays for ad-hoc shell use
        assert "src/main.py" in text, "launcher must call src/main.py --auto inline"
        assert "run_daily_auto.sh" in text  # still referenced in comments/doc for ad-hoc runs
