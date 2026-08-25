#!/usr/bin/env python3
"""Official forward-trial daily session driver CLI (R36, offline primitive).

把真实日度管道产物驱入官方栈: decide (readiness manifest → snapshot → 证据
发布 → 配对决策) / advance (court raw bar 快照 → bar-set 证据 → 市场窗口
推进) / finalize-missed (错过会话 NO_RUN 补记)。

与 ``v3_trial_genesis.py`` 同款纪律: **默认 dry-run 零写入** — 只做身份/
布局/日历/manifest 的只读校验并输出计划, 不打开任何写连接 (官方栈构造器
本身会落 WAL+DDL, 因此 dry-run 绝不构造栈); ``--execute`` 才真正驱动。

全部离线 primitive: 不解锁权限、不连 broker、不写真实 trial root 之外的
任何位置; exit 0 仅当命令成功 (dry-run = 校验全过)。

用法:
  uv run python scripts/v3_trial_session.py decide \\
      --identity-dir data/v3_governance_identity \\
      --trial-root <trial_root> --trial-id <trial_id> \\
      --calendar data/reports/trade_calendar.json \\
      --readiness-manifest data/reports/daily_action_readiness_YYYYMMDD.json \\
      --signal-session YYYY-MM-DD [--execute] [--now ISO]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path


def _fail(code: str, message: str, **details: object) -> int:
    print(
        json.dumps(
            {"ok": False, "code": code, "message": message, "details": details},
            ensure_ascii=False,
        )
    )
    return 2


def _ok(payload: dict) -> int:
    print(json.dumps({"ok": True, **payload}, ensure_ascii=False, default=str))
    return 0


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _parse_now(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise SystemExit(_fail("now_requires_timezone", value))
    return parsed.astimezone(timezone.utc)


def _dry_run_checks(
    *,
    identity_dir: Path,
    trial_root: Path,
    calendar_path: Path,
    trial_id: str,
) -> dict | None:
    """Zero-write validation: identity, layout files, calendar readability."""
    from src.screening.offensive.v3.evidence.governance_identity import (
        GovernanceIdentityError,
        verify_identity_directory,
    )
    from src.screening.offensive.v3.evidence.trading_schedule import (
        TradingScheduleError,
        load_authoritative_dates,
    )

    try:
        verify_identity_directory(identity_dir)
    except GovernanceIdentityError as exc:
        raise SystemExit(_fail("identity_check_failed", str(exc)))
    required = [
        trial_root / "evidence.sqlite3",
        trial_root / "bars-evidence.sqlite3",
        trial_root / "spine.sqlite3",
        trial_root / "governance.sqlite3",
        trial_root / trial_id / "genesis-manifest.json",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(_fail("trial_root_not_initialized", "missing files", missing=missing))
    try:
        dates = load_authoritative_dates(calendar_path)
    except (TradingScheduleError, OSError) as exc:
        raise SystemExit(_fail("calendar_unreadable", str(exc)))
    return {"calendar_sessions": len(dates)}


def _build_stack(
    *,
    identity_dir: Path,
    trial_root: Path,
    trial_id: str,
    research_program_id: str,
    now: datetime,
):
    from src.screening.offensive.v3.capital.fills import FillAttribution
    from src.screening.offensive.v3.kernel.sizing import SizingConfig
    from src.screening.offensive.v3.orchestration.arm_lifecycle import (
        CURRENT_COST_SCENARIO,
    )
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
        build_official_trial_stack,
    )

    try:
        return build_official_trial_stack(
            identity_dir=identity_dir,
            trial_root=trial_root,
            trial_id=trial_id,
            sizing_config=SizingConfig(
                per_ticker_gross_cap_cents=200_000,
                per_industry_gross_cap_cents=300_000,
                per_day_gross_cap_cents=500_000,
                portfolio_gross_cap_cents=400_000,
                worst_case_fee_ppm=3_000,
            ),
            clock=lambda: now,
            market_scenario=CURRENT_COST_SCENARIO,
            trial_attribution=FillAttribution(
                producer_namespace="btst",
                research_program_id=research_program_id,
                economic_lineage_id=f"eline-{trial_id}",
                stage_id=f"stage-{trial_id}",
            ),
            research_program_id=research_program_id,
        )
    except OfficialStackError as exc:
        raise SystemExit(_fail(exc.code, str(exc)))


def _load_snapshot(
    manifest_path: Path,
    signal_session: date,
    *,
    data_dir: Path,
):
    from src.screening.offensive.daily_action_snapshot import (
        SnapshotLoadError,
        load_verified_daily_action_snapshot,
    )

    try:
        result = load_verified_daily_action_snapshot(
            signal_session,
            reports_dir=manifest_path.parent,
            data_dir=data_dir,
        )
    except SnapshotLoadError as exc:
        raise SystemExit(_fail("snapshot_load_failed", str(exc)))
    if result.snapshot is None:
        raise SystemExit(
            _fail(
                "snapshot_load_failed",
                "readiness snapshot is unavailable for the signal session",
                global_reason=result.global_reason,
                ticker_blocks=list(result.ticker_blocks),
            )
        )
    snapshot = result.snapshot
    if snapshot.signal_date != signal_session:
        raise SystemExit(
            _fail(
                "manifest_session_mismatch",
                "the manifest's trade date is not the requested signal session",
                manifest=str(snapshot.signal_date),
                requested=signal_session.isoformat(),
            )
        )
    return snapshot


def _cmd_decide(args: argparse.Namespace) -> int:
    identity_dir = Path(args.identity_dir)
    trial_root = Path(args.trial_root)
    calendar_path = Path(args.calendar)
    signal_session = _parse_date(args.signal_session)
    now = _parse_now(args.now)
    checks = _dry_run_checks(
        identity_dir=identity_dir,
        trial_root=trial_root,
        calendar_path=calendar_path,
        trial_id=args.trial_id,
    )
    if not args.execute:
        return _ok(
            {
                "mode": "dry-run",
                "plan": [
                    "publish regime observation (snapshot PIT regime)",
                    "publish trading-schedule slice",
                    "publish btst candidates (SELECTED)",
                    "decide_signal_session (pair commit)",
                ],
                **(checks or {}),
            }
        )
    snapshot = _load_snapshot(
        Path(args.readiness_manifest), signal_session, data_dir=Path(args.data_dir)
    )
    stack = _build_stack(
        identity_dir=identity_dir,
        trial_root=trial_root,
        trial_id=args.trial_id,
        research_program_id=args.research_program,
        now=now,
    )
    from src.screening.offensive.v3.evidence.governance_identity import (
        load_governance_identity,
    )
    from src.screening.offensive.v3.orchestration.trial_session_driver import (
        OfficialTrialSessionDriver,
        TrialSessionDriverError,
    )

    identity = load_governance_identity(identity_dir, trusted_at=now)
    driver = OfficialTrialSessionDriver(
        stack=stack,
        identity=identity,
        calendar_path=calendar_path,
        clock=lambda: now,
    )
    try:
        driver.ensure_trial_registration()
        receipt = driver.decide_session(
            snapshot=snapshot, signal_session=signal_session, now=now
        )
    except TrialSessionDriverError as exc:
        return _fail("driver_failed", str(exc), code=exc.code, **exc.details)
    return _ok(
        {
            "mode": "execute",
            "pair_key": list(receipt.pair_key),
            "champion_status": str(receipt.champion_status),
            "challenger_status": str(receipt.challenger_status),
        }
    )


def _cmd_advance(args: argparse.Namespace) -> int:
    identity_dir = Path(args.identity_dir)
    trial_root = Path(args.trial_root)
    calendar_path = Path(args.calendar)
    signal_session = _parse_date(args.signal_session)
    through_session = _parse_date(args.through_session)
    now = _parse_now(args.now)
    checks = _dry_run_checks(
        identity_dir=identity_dir,
        trial_root=trial_root,
        calendar_path=calendar_path,
        trial_id=args.trial_id,
    )
    from scripts.v3_seed_market_bars import bars_from_court_csv

    source = Path(args.bar_source)
    sessions = sorted(
        path for path in source.glob("daily_*.csv")
    )
    if not sessions and not args.execute:
        return _fail("bar_source_empty", str(source))
    if not args.execute:
        return _ok(
            {
                "mode": "dry-run",
                "plan": [
                    "publish bar-set evidence per session in window",
                    "advance_market_session (both arms, conservation)",
                ],
                "bar_snapshots": len(sessions),
                **(checks or {}),
            }
        )
    bars_by_session = {}
    for path in sessions:
        session = _parse_date(path.stem.removeprefix("daily_"))
        bars_by_session[session] = bars_from_court_csv(path, session)
    stack = _build_stack(
        identity_dir=identity_dir,
        trial_root=trial_root,
        trial_id=args.trial_id,
        research_program_id=args.research_program,
        now=now,
    )
    from src.screening.offensive.v3.evidence.governance_identity import (
        load_governance_identity,
    )
    from src.screening.offensive.v3.orchestration.trial_session_driver import (
        OfficialTrialSessionDriver,
        TrialSessionDriverError,
    )

    identity = load_governance_identity(identity_dir, trusted_at=now)
    driver = OfficialTrialSessionDriver(
        stack=stack,
        identity=identity,
        calendar_path=calendar_path,
        clock=lambda: now,
    )
    try:
        receipt = driver.advance_sessions(
            signal_session=signal_session,
            through_session=through_session,
            bars_by_session=bars_by_session,
            now=now,
        )
    except TrialSessionDriverError as exc:
        return _fail("driver_failed", str(exc), code=exc.code, **exc.details)
    return _ok(
        {
            "mode": "execute",
            "through_session": receipt.through_session.isoformat(),
            "conservation_ok_by_arm": receipt.conservation_ok_by_arm,
            "open_at_end_by_arm": receipt.open_at_end_by_arm,
        }
    )


def _cmd_finalize(args: argparse.Namespace) -> int:
    identity_dir = Path(args.identity_dir)
    trial_root = Path(args.trial_root)
    now = _parse_now(args.now)
    _dry_run_checks(
        identity_dir=identity_dir,
        trial_root=trial_root,
        calendar_path=Path(args.calendar),
        trial_id=args.trial_id,
    )
    if not args.execute:
        return _ok(
            {
                "mode": "dry-run",
                "plan": ["finalize_missed_sessions (NO_RUN bookkeeping, idempotent)"],
            }
        )
    stack = _build_stack(
        identity_dir=identity_dir,
        trial_root=trial_root,
        trial_id=args.trial_id,
        research_program_id=args.research_program,
        now=now,
    )
    from src.screening.offensive.v3.orchestration.trial_session_driver import (
        TrialSessionDriverError,
    )

    try:
        finalized = stack.runner.finalize_missed_sessions(now)
    except TrialSessionDriverError as exc:
        return _fail("driver_failed", str(exc), code=exc.code, **exc.details)
    return _ok(
        {
            "mode": "execute",
            "finalized_sessions": [session.isoformat() for session in finalized],
        }
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--identity-dir", required=True)
        p.add_argument("--trial-root", required=True)
        p.add_argument("--trial-id", required=True)
        p.add_argument("--research-program", default="research.btst.regime")
        p.add_argument("--calendar", required=True)
        p.add_argument("--now", default=None, help="UTC ISO instant (default: now)")
        p.add_argument("--execute", action="store_true", help="real writes (default: dry-run)")

    decide = sub.add_parser("decide", help="publish session evidence + pair decision")
    common(decide)
    decide.add_argument("--readiness-manifest", required=True)
    decide.add_argument("--signal-session", required=True)
    decide.add_argument("--data-dir", default="data", help="repo data dir (price/fund-flow caches)")
    decide.set_defaults(func=_cmd_decide)

    advance = sub.add_parser("advance", help="publish bar sets + market-window advance")
    common(advance)
    advance.add_argument("--signal-session", required=True)
    advance.add_argument("--through-session", required=True)
    advance.add_argument("--bar-source", required=True, help="court raw daily_*.csv directory")
    advance.set_defaults(func=_cmd_advance)

    finalize = sub.add_parser("finalize-missed", help="NO_RUN bookkeeping for missed sessions")
    common(finalize)
    finalize.set_defaults(func=_cmd_finalize)
    return parser


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
