"""NS-5 data-flywheel health + launchd-safe invocation.

The daily auto_screening job (``scripts/run_daily_auto.sh``) is the engine that
accumulates ``tracking_history`` so realized T+1..T+30 returns are backfilled
and feed calibration / ``--reconcile``. On 2026-06-30 it was discovered SILENTLY
DEAD for 6 days: ``launchd`` returned ``EX_CONFIG`` (78) for every fire because
the plist referenced paths on the external ``/Volumes`` APFS volume mounted with
``noowners``. macOS ``launchd`` refuses to trust executable/output paths it
cannot enforce ownership on, and nothing surfaced the stall — the flywheel just
stopped and the "observe until 2026-07-12" trigger quietly lost its data source.

Two pure, testable helpers prevent recurrence:

* :func:`check_flywheel_health` — classifies staleness so a dead flywheel is
  OBSERVABLE (status healthy/stale/critical) instead of silent.
* :func:`build_launchd_invocation` — emits a launchd-safe plist invocation that
  keeps every path key on the boot volume (the ``EX_CONFIG`` trap is structurally
  impossible), delegating the real work to a ``/bin/bash -c`` inline that ``cd``'s
  into the repo at runtime.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Thresholds (days). Tuned to the realized-evidence pipeline: records become
# eligible for T+1 backfill at ~6 days, so a 3-day gap already starves
# calibration; >=7 days is a dead flywheel.
STALE_DAYS = 3.0
CRITICAL_DAYS = 7.0


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def check_flywheel_health(
    tracking_history_mtime: Optional[float],
    latest_record_date: Optional[str] = None,
    *,
    now_ts: Optional[float] = None,
    stale_days: float = STALE_DAYS,
    critical_days: float = CRITICAL_DAYS,
) -> dict:
    """Classify data-flywheel freshness from tracking_history metadata.

    Parameters
    ----------
    tracking_history_mtime:
        POSIX mtime of the tracking_history store, or ``None`` if missing.
    latest_record_date:
        Optional human-readable date string of the newest record (for messages).
    now_ts:
        Injectable "now" (UTC POSIX) for deterministic tests.

    Returns
    -------
    dict with ``status`` (healthy|stale|critical), ``stale`` (bool),
    ``days_since_last_write`` (float, or ``None`` if missing) and a
    ``message``. Missing history is always ``critical``.
    """
    now = now_ts if now_ts is not None else _now_ts()
    if tracking_history_mtime is None:
        return {
            "status": "critical",
            "stale": True,
            "days_since_last_write": None,
            "latest_record_date": latest_record_date,
            "message": ("tracking_history 缺失 — 数据飞轮从未运行或被删除。" "检查 daily_auto launchd job 状态。"),
        }
    days = max(0.0, (now - tracking_history_mtime) / 86400.0)
    if days >= critical_days:
        status = "critical"
    elif days >= stale_days:
        status = "stale"
    else:
        status = "healthy"
    date_part = f" (最新记录 {latest_record_date})" if latest_record_date else ""
    if status == "healthy":
        msg = f"数据飞轮健康 — {days:.1f} 天前更新{date_part}。"
    elif status == "stale":
        msg = f"⚠ 数据飞轮停滞 — {days:.1f} 天未更新 (>= {stale_days:.0f} 天阈值){date_part}。" "launchd daily-auto job 可能未触发。"
    else:
        msg = f"🔴 数据飞轮已停 — {days:.1f} 天未更新 (>= {critical_days:.0f} 天){date_part}。" "校准/对账数据源已断，需立即修复 launchd job。"
    return {
        "status": status,
        "stale": status != "healthy",
        "days_since_last_write": round(days, 2),
        "latest_record_date": latest_record_date,
        "message": msg,
    }


def build_launchd_invocation(repo_path: str) -> dict:
    """Build a launchd-safe invocation for the daily auto_screening job.

    Regression guard for the EX_CONFIG (78) trap: macOS ``launchd`` refuses to
    spawn a daemon whose ``Program``/``WorkingDirectory``/``StandardOutPath``/
    ``StandardErrorPath`` reference files on an external ``noowners`` volume
    (the whole config is rejected with ``last exit code = 78: EX_CONFIG`` and
    ZERO captured output — a silent stall).

    The fix is structural: keep every plist path key on the boot volume and do
    the real work inside a ``/bin/bash -c '<inline>'`` body that ``cd``'s into
    the repo at runtime. ``/bin/bash`` (boot volume, trusted) spawns fine under
    launchd and the inline body can freely access ``/Volumes`` once running.

    Returns the plist fields ``program_arguments`` (the ``ProgramArguments``
    array), ``working_directory`` (``None`` — intentionally NOT set), and
    ``standard_out_path`` / ``standard_error_path`` pointing at ``~/Library/Logs``
    (boot volume), never at the repo.
    """
    repo = str(Path(repo_path).resolve())
    script = f"{repo}/scripts/run_daily_auto.sh"
    body = f"cd {repo} && " f"exec {script} --top-n 10"
    home = str(Path.home())
    log_dir = f"{home}/Library/Logs/ai-hedge-fund"
    return {
        "program_arguments": ["/bin/bash", "-c", body],
        # INTENTIONALLY None: a /Volumes WorkingDirectory triggers EX_CONFIG.
        "working_directory": None,
        "standard_out_path": f"{log_dir}/daily_auto.out.log",
        "standard_error_path": f"{log_dir}/daily_auto.err.log",
    }


def assess_tracking_history(report_dir: Optional[Path] = None) -> dict:
    """Convenience: read tracking_history mtime + latest record date and classify.

    Safe to call from the daily job itself or a CLI health check; never raises
    (missing files -> critical status).
    """
    from src.screening.consecutive_recommendation import (
        load_tracking_history,
        resolve_report_dir,
    )

    rd = Path(report_dir) if report_dir else resolve_report_dir()
    th = rd / "tracking_history.json"
    mtime = th.stat().st_mtime if th.exists() else None
    latest_date: Optional[str] = None
    try:
        recs = load_tracking_history(rd)
        dates = sorted(r.get("recommended_date", "") for r in recs if r.get("recommended_date"))
        latest_date = dates[-1] if dates else None
    except Exception as exc:
        # NS-17/BH-017 同族: 静默 pass 会让 latest_date 保持 None, check_flywheel_health
        # 仍按 mtime 判级, 但 operators 无法区分 "无记录" 与 "tracking_history.json 损坏
        # / load_tracking_history bug"。surface 到 logger.warning 让 flywheel 健康降级
        # 可观测 (NS-5 flywheel 健康是前门信任校准的核心信号)。
        logger.warning(
            "assess_tracking_history load failed (rd=%s): %s",
            rd,
            exc,
        )
    return check_flywheel_health(mtime, latest_date)


def run_daily_regime_refresh(
    reports_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    *,
    min_samples: int = 10,
    _runner=None,
) -> dict:
    """NS-5 part 2: auto-recompute regime winrates inside the daily job.

    The daily flywheel (unblocked in c256) accumulates ``tracking_history``, but
    the hardcoded ``REGIME_HISTORICAL_WINRATES`` (stale after owner factor
    changes) only refreshes if the recompute actually runs. This wires
    :func:`regime_winrate_recompute.run_refresh_cli` into the daily path and
    writes a dated, owner-auditable artifact so the stale constants can be
    replaced with fresh values as data accrues.

    Parameters
    ----------
    reports_dir:
        Directory holding ``tracking_history.json`` + ``auto_screening_*.json``.
        ``None`` → resolved via ``resolve_report_dir``.
    output_dir:
        Where to write the dated recomputed artifact. ``None`` → ``reports_dir``.
    min_samples:
        Minimum records per regime (default 10 = production threshold).
    _runner:
        Test seam: a callable receiving ``reports_dir``, ``output_path``,
        ``min_samples`` and returning ``(written_path | None, rc)``. Defaults to
        the real :func:`run_refresh_cli` (which writes the file itself and rc).

    Returns
    -------
    dict with ``status`` (ok|skipped|failed), ``rc``, ``output_path``, ``message``.
    rc != 0 is non-fatal (the daily job's value is the --auto + backfill; this is
    a best-effort refresh) so callers log and continue.
    """
    # R90 family (autodev-34-op3): 用模块级 ``datetime`` (line 26), 不在此局部
    # re-import —— 局部 import 会遮蔽模块级 name, 使测试 patch 失效 (Op2 在
    # daily_brief 已证同病致 staleness 测试随日历漂移变红).
    from src.screening.consecutive_recommendation import resolve_report_dir

    rd = Path(reports_dir) if reports_dir else resolve_report_dir()
    out_dir = Path(output_dir) if output_dir else rd
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")
    out_path = out_dir / f"regime_winrates_recomputed_{stamp}.json"

    if _runner is None:
        from src.screening.regime_winrate_recompute import run_refresh_cli

        def _runner(**kw):  # type: ignore[misc]
            rc = run_refresh_cli(
                reports_dir=kw["reports_dir"],
                output_path=kw["output_path"],
                min_samples=kw["min_samples"],
            )
            written = kw["output_path"] if rc == 0 and kw["output_path"].exists() else None
            return (written, rc)

    try:
        written, rc = _runner(reports_dir=rd, output_path=out_path, min_samples=min_samples)
    except Exception as exc:  # defensive: daily job must not die on refresh failure
        return {
            "status": "failed",
            "rc": None,
            "output_path": str(out_path),
            "message": f"regime refresh 异常 (non-fatal): {exc}",
        }

    if rc == 0 and written is not None:
        return {
            "status": "ok",
            "rc": 0,
            "output_path": str(written),
            "message": f"regime winrates refreshed → {written}",
        }
    return {
        "status": "skipped",
        "rc": rc,
        "output_path": str(out_path),
        "message": f"regime refresh skipped (rc={rc}, non-fatal — insufficient data or no date→regime map yet)",
    }
