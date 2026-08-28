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
from datetime import date, datetime, time, timezone
from pathlib import Path


def _fail(code: str, message: str, **details: object) -> int:
    print(
        json.dumps(
            {"ok": False, "code": code, "message": message, "details": details},
            ensure_ascii=False,
        )
    )
    return 2


def _fail_driver(exc: "TrialSessionDriverError") -> int:
    """按 ``_fail`` 输出契约构造 driver 错误 (R47, D1 收口)。

    ``exc.code`` 是权威码; details 里的同名 ``code`` 键显式弃用 —
    此前的 ``_fail("driver_failed", str(exc), code=exc.code, **exc.details)``
    位置/关键字 ``code`` 恒碰撞, 任何 driver 类型化错误都被 TypeError
    掩盖 (R38/R41 同族第四处)。
    """
    details = dict(exc.details)
    details.pop("code", None)
    return _fail(exc.code, str(exc), **details)


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


def _decide_preflight(*, calendar_path: Path, signal_session: date) -> None:
    """日历成员 pre-flight (R48 D6): dry-run/execute 共享, 构造栈之前。

    日历外会话在 execute 必然失败于排程派生 (driver 同款
    ``signal_session_not_in_calendar``), 无 store 依赖即可判定, 故两面
    都在构造栈之前拒绝 (R40 语义)。
    """
    from src.screening.offensive.v3.evidence.trading_schedule import (
        TradingScheduleError,
        load_authoritative_dates,
    )

    try:
        dates = load_authoritative_dates(calendar_path)
    except (TradingScheduleError, OSError) as exc:
        raise SystemExit(_fail("calendar_unreadable", str(exc)))
    if signal_session not in dates:
        raise SystemExit(
            _fail(
                "signal_session_not_in_calendar",
                "the signal session is absent from the authoritative calendar",
                signal_session=signal_session.isoformat(),
            )
        )


def _decide_window_preflight(*, signal_session: date, now: datetime) -> None:
    """候选入库窗 pre-flight (R48 D6, D8 收敛为 dry-run 专属)。

    dry-run 报绿的语义是『execute 的前置全部成立』: 窗口外会话的首次
    execute 必然失败, dry-run 必须先说 (宁假红不假绿)。execute 面的窗口
    判定由 driver 首步守卫 (:meth:`_require_decide_window`) 以 store 真相
    权威执行 — CLI 无 store 读面, 若在 execute 面拦截会让『窗口内已提交
    候选的窗口外恰等重放』这一合法逃生门不可达 (D8 实锤的语义分裂)。
    """
    from src.screening.offensive.v3.producers.auto import candidate_ingestion_window

    window_open, window_close = candidate_ingestion_window(signal_session)
    if not (window_open <= now <= window_close):
        raise SystemExit(
            _fail(
                "decide_window_violated",
                "the signal session is outside its candidate ingestion window"
                " [signal_date 15:00 UTC, +24h]; in-window decide is the only"
                " first drive (missed sessions exit via finalize-missed"
                " NO_RUN). On --execute the driver-side guard re-evaluates"
                " with store truth: a committed in-window decide may replay"
                " (exact-equal), anything else is rejected before any"
                " publication",
                signal_session=signal_session.isoformat(),
                window_open=window_open.isoformat(),
                window_close=window_close.isoformat(),
                now=now.isoformat(),
            )
        )


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
    # pre-flight (R48 D6/D8): 日历成员两面共享; 窗口检查 dry-run 专属
    # (execute 面由 driver 守卫以 store 真相权威判定)。各 helper 与
    # _load_snapshot 同以 SystemExit 携带 typed JSON, 本入口统一收敛为
    # 返回码 (R40 约定: 前置拒绝 rc=2, 不向调用方泄漏异常)。
    try:
        _decide_preflight(calendar_path=calendar_path, signal_session=signal_session)
        if not args.execute:
            _decide_window_preflight(signal_session=signal_session, now=now)
        snapshot = _load_snapshot(
            Path(args.readiness_manifest), signal_session, data_dir=Path(args.data_dir)
        )
    except SystemExit as stopped:
        return int(stopped.code)
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
                "readiness_session": snapshot.signal_date.isoformat(),
                **(checks or {}),
            }
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
        return _fail_driver(exc)
    return _ok(
        {
            "mode": "execute",
            "pair_key": list(receipt.pair_key),
            "champion_status": str(receipt.champion_status),
            "challenger_status": str(receipt.challenger_status),
        }
    )


def _advance_window_sessions(
    *,
    calendar_path: Path,
    signal_session: date,
    through_session: date,
) -> list[date]:
    """Read-only derivation of the frozen advance window (shared pre-flight).

    Mirrors the driver's ``advance_sessions`` slicing exactly: the schedule is
    authoritative, and the window shape is available_at-independent (the
    instant only feeds the evidence envelope). Raises SystemExit with typed
    failures on calendar/schedule problems; never constructs the stack.
    """
    from src.screening.offensive.v3.evidence.trading_schedule import (
        TradingScheduleError,
        derive_trading_schedule,
        load_authoritative_dates,
    )

    try:
        dates = load_authoritative_dates(calendar_path)
    except (TradingScheduleError, OSError) as exc:
        raise SystemExit(_fail("calendar_unreadable", str(exc)))
    if signal_session not in dates:
        raise SystemExit(
            _fail(
                "signal_session_not_in_calendar",
                "the signal session is absent from the authoritative calendar",
                signal_session=signal_session.isoformat(),
            )
        )
    try:
        schedule = derive_trading_schedule(
            signal_session=signal_session,
            calendar_dates=dates,
            # Nominal close-finalized instant (mirrors the driver's
            # _CLOSE_FINALIZED); the window shape is available_at-independent.
            available_at=datetime.combine(
                signal_session, time(15, 0), tzinfo=timezone.utc
            ),
        )
    except TradingScheduleError as exc:
        code = str(exc).partition(":")[0] or "insufficient_forward_sessions"
        raise SystemExit(_fail(code, str(exc)))
    window = [
        session
        for session in (signal_session, *schedule.following_sessions)
        if session <= through_session
    ]
    if not window or window[-1] != through_session:
        raise SystemExit(
            _fail(
                "advance_window_not_in_schedule",
                "through_session must be a member of the frozen schedule"
                " slice (the schedule is authoritative)",
                schedule_window=[
                    session.isoformat()
                    for session in (signal_session, *schedule.following_sessions)
                ],
            )
        )
    return window


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
    # Shared pre-flight (dry-run and execute): every session of the frozen
    # window must have a daily snapshot BEFORE the stack is constructed (the
    # constructor itself writes WAL+DDL into the trial root).
    window = _advance_window_sessions(
        calendar_path=calendar_path,
        signal_session=signal_session,
        through_session=through_session,
    )
    source = Path(args.bar_source)
    if not source.is_dir():
        return _fail("bar_source_missing", str(source))
    missing_sessions = [
        session
        for session in window
        if not (source / f"daily_{session:%Y%m%d}.csv").is_file()
    ]
    if missing_sessions:
        return _fail(
            "bar_sessions_missing",
            "every session in the frozen advance window needs a"
            " daily_YYYYMMDD.csv snapshot (unadjusted pro.daily format;"
            " refresh the source before advancing)",
            missing_sessions=[
                session.isoformat() for session in missing_sessions
            ],
            window_sessions=[session.isoformat() for session in window],
            bar_source=str(source),
        )
    if not args.execute:
        return _ok(
            {
                "mode": "dry-run",
                "plan": [
                    "publish bar-set evidence per session in window",
                    "advance_market_session (both arms, conservation)",
                ],
                "window_sessions": len(window),
                **(checks or {}),
            }
        )
    from scripts.v3_seed_market_bars import CourtBarCsvError, bars_from_court_csv

    # Parse only the window's snapshots (a full research directory can hold
    # hundreds of full-market files; the driver only consumes the window).
    bars_by_session = {}
    for session in window:
        try:
            bars_by_session[session] = bars_from_court_csv(
                source / f"daily_{session:%Y%m%d}.csv", session
            )
        except FileNotFoundError as exc:
            # preflight 判在的 CSV 于读取点消失 (R49 Op2, D7 家族):
            # pandas 的裸 FileNotFoundError 不得绕过类型化面。
            print(
                json.dumps(
                    {
                        "ok": False,
                        "code": "bar_csv_missing",
                        "message": str(exc),
                        "details": {
                            "path": str(source / f"daily_{session:%Y%m%d}.csv")
                        },
                    },
                    ensure_ascii=False,
                )
            )
            return 2
        except CourtBarCsvError as exc:
            # _fail 的首个位置参数就是顶层 code, 底层拒绝码要进 details.code
            # ——键名与位置参数同名, kwargs 无法表达, 只能按 _fail 的输出
            # 契约手工构造 (R38 同族参数碰撞的第三处, 语义与 _fail 逐字对齐)。
            print(
                json.dumps(
                    {
                        "ok": False,
                        "code": "bar_csv_invalid",
                        "message": str(exc),
                        "details": {**exc.details, "code": exc.code},
                    },
                    ensure_ascii=False,
                )
            )
            return 2
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
        return _fail_driver(exc)
    return _ok(
        {
            "mode": "execute",
            "through_session": receipt.through_session.isoformat(),
            "conservation_ok_by_arm": receipt.conservation_ok_by_arm,
            "open_at_end_by_arm": receipt.open_at_end_by_arm,
        }
    )


def _cold_read_spine_statuses(program: str, spine_path: Path) -> dict[date, str]:
    """只读 spine 状态探针 (dry-run 计划面; 零写, R51 Op2)。

    ``immutable=1`` 冷读 (R35 组装器 / R50 Op2 enroll 冷读同款): 只读主
    文件, 不创建 -shm/-wal, 不触碰任何字节; 最新 revision = 当前状态。
    """
    import sqlite3

    if not spine_path.is_file():
        return {}
    conn = sqlite3.connect(f"file:{spine_path}?immutable=1", uri=True)
    try:
        rows = conn.execute(
            "SELECT r.signal_session, r.status"
            " FROM session_status_revisions AS r"
            " JOIN (SELECT signal_session, MAX(revision) AS rev"
            "       FROM session_status_revisions"
            "       WHERE research_program_id = ?"
            "       GROUP BY signal_session) AS latest"
            " ON latest.signal_session = r.signal_session"
            "  AND latest.rev = r.revision"
            " WHERE r.research_program_id = ?",
            (program, program),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        # 0 字节占位 = 零注册合法形态 (R50 Op2 P1 语义) — 表缺失不是损坏。
        if "no such table" in str(exc):
            return {}
        raise SystemExit(_fail("spine_unreadable", str(exc), path=str(spine_path)))
    except sqlite3.DatabaseError as exc:
        raise SystemExit(_fail("spine_unreadable", str(exc), path=str(spine_path)))
    finally:
        conn.close()
    return {date.fromisoformat(signal): status for signal, status in rows}


def _finalize_dry_run_plan(*, program: str, spine_path: Path, today: date) -> dict:
    """finalize-missed 的 spine 级计划 (R51 Op2; enroll R50 Op2 同族保真)。

    判定语义与 runner ``finalize_missed_sessions`` 同源: 评估窗已过 +
    无终态 (或 DATA_UNKNOWN 可升级) = NO_RUN 候选。诚实边界: pair 排除
    (已决策会话) 属 decision-store truth, CLI 无 store 读面不越权冷读
    decisions — execute 面以 store 权威执行, 本计划宁可高估不漏披。
    """
    from scripts.v3_trial_bootstrap import _cold_read_enrollments
    from src.screening.offensive.v3.evidence.session_spine import SessionStatus

    enrolled = _cold_read_enrollments(program, spine_path)
    statuses = {
        session: (SessionStatus(raw) if raw is not None else None)
        for session, raw in _cold_read_spine_statuses(program, spine_path).items()
    }
    upgradable = SessionStatus.DATA_UNKNOWN
    candidates: list[str] = []
    already: list[str] = []
    pending: list[str] = []
    for session in sorted(enrolled):
        if enrolled[session] > today:
            pending.append(session.isoformat())
            continue
        status = statuses.get(session)
        if status is None or status is upgradable:
            candidates.append(session.isoformat())
        else:
            already.append(session.isoformat())
    return {
        "no_run_spine_candidates": candidates,
        "already_terminal": already,
        "not_yet_assessed": pending,
        "note": (
            "spine-level plan; execute additionally excludes sessions with"
            " committed decision pairs (decision-store truth)"
        ),
    }


def _cmd_finalize(args: argparse.Namespace) -> int:
    identity_dir = Path(args.identity_dir)
    trial_root = Path(args.trial_root)
    now = _parse_now(args.now)
    checks = _dry_run_checks(
        identity_dir=identity_dir,
        trial_root=trial_root,
        calendar_path=Path(args.calendar),
        trial_id=args.trial_id,
    )
    if not args.execute:
        plan = _finalize_dry_run_plan(
            program=args.research_program,
            spine_path=trial_root / "spine.sqlite3",
            today=now.date(),
        )
        return _ok({"mode": "dry-run", **plan, **(checks or {})})
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
        return _fail_driver(exc)
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
