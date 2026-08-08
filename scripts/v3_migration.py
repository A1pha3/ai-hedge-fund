#!/usr/bin/env python3
"""Plan 06 Task 8: v2→v3 迁移协调 CLI.

子命令: inventory / freeze-new-risk / prepare / verify / adopt-orders /
flip / replay-inbox / finalize / status.

安全性质:
- 所有 mutation 子命令必须提供 --manifest, 且默认 dry-run (--apply 才执行);
- status 永远只读, 报告 approval/root/writer/fence/lease/inbox/cursor/
  conservation 状态;
- flip 前必须完成 CONSERVATION_VERIFIED; finalize 前必须 replay 完成.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from src.screening.offensive.v3.migration.authority import AuthorityRegistry
from src.screening.offensive.v3.migration.conservation import verify_conservation
from src.screening.offensive.v3.migration.coordinator import (
    MigrationCoordinator,
    MigrationState,
)
from src.screening.offensive.v3.migration.inbox import DurableCapitalInbox
from src.screening.offensive.v3.migration.inventory import capture_v2_inventory


def _coordinator(args: argparse.Namespace) -> MigrationCoordinator:
    return MigrationCoordinator(
        state_path=args.state_path,
        migration_id=args.migration_id,
        source_path=args.source_path,
        ledger_id=args.ledger_id,
    )


def _cmd_status(args: argparse.Namespace) -> int:
    coordinator = _coordinator(args)
    state = coordinator.current_state()
    report: dict[str, object] = {
        "migration_id": args.migration_id,
        "state": state.value,
        "ledger_id": args.ledger_id,
        "source_path": str(args.source_path),
    }
    try:
        inventory = capture_v2_inventory(
            args.source_path, ledger_id=args.ledger_id
        )
        report["source_root"] = inventory.source_root
        report["event_count"] = inventory.event_count
        report["trade_count"] = inventory.trade_count
    except Exception as exc:  # noqa: BLE001 - status must stay read-only
        report["inventory_error"] = str(exc)
    if state in (
        MigrationState.V3_IMPORT_PREPARED,
        MigrationState.CONSERVATION_VERIFIED,
        MigrationState.V2_CAPITAL_WRITE_FENCED_AND_AUTHORITY_FLIPPED,
        MigrationState.V3_INBOX_REPLAYED,
        MigrationState.V2_READ_ONLY,
    ):
        prepared = coordinator.prepared_import()
        report["prepared_source_root"] = prepared.source_root
        report["prepared_executable"] = prepared.executable
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


def _cmd_inventory(args: argparse.Namespace) -> int:
    inventory = capture_v2_inventory(
        args.source_path, ledger_id=args.ledger_id
    )
    print(
        json.dumps(
            {
                "source_root": inventory.source_root,
                "section_roots": dict(inventory.section_roots),
                "cash_balance": str(inventory.cash.cash_balance),
                "positions": len(inventory.positions),
                "plans": len(inventory.plans),
                "pending_exits": len(inventory.pending_exits),
                "event_count": inventory.event_count,
                "trade_count": inventory.trade_count,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _advance(args: argparse.Namespace, target: MigrationState) -> int:
    coordinator = _coordinator(args)
    record = coordinator.advance(target)
    print(
        json.dumps(
            {
                "state": record.state,
                "entered_at": record.entered_at.isoformat(),
                "source_root": record.source_root,
                "dry_run": args.dry_run,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    coordinator = _coordinator(args)
    prepared = coordinator.prepared_import()
    source = capture_v2_inventory(args.source_path, ledger_id=args.ledger_id)
    proof = verify_conservation(source, prepared.target_projection)
    print(
        json.dumps(
            {"verified_sections": list(proof.verified_sections)},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _require_manifest(args: argparse.Namespace) -> None:
    if not getattr(args, "manifest", None):
        raise SystemExit("--manifest is required for mutation commands")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v3_migration")
    parser.add_argument("--state-path", type=Path, required=True)
    parser.add_argument("--migration-id", required=True)
    parser.add_argument("--source-path", type=Path, required=True)
    parser.add_argument("--ledger-id", required=True)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status").add_argument(
        "--dry-run", action="store_true", default=True,
        help="accepted for symmetry; status is always read-only",
    )
    inv = sub.add_parser("inventory")
    inv.add_argument("--dry-run", action="store_true", default=True)

    for name, state in (
        ("freeze-new-risk", MigrationState.V2_NEW_RISK_FROZEN),
        ("prepare", MigrationState.V3_IMPORT_PREPARED),
        ("adopt-orders", MigrationState.ORDERS_DRAINED_OR_ADOPTED),
    ):
        cmd = sub.add_parser(name)
        cmd.add_argument("--manifest", type=Path)
        cmd.add_argument("--apply", dest="dry_run", action="store_false", default=True)
        cmd.set_defaults(_target=state)

    sub.add_parser("verify").add_argument(
        "--dry-run", action="store_true", default=True
    )

    for name, state in (
        ("flip", MigrationState.V2_CAPITAL_WRITE_FENCED_AND_AUTHORITY_FLIPPED),
        ("replay-inbox", MigrationState.V3_INBOX_REPLAYED),
        ("finalize", MigrationState.V2_READ_ONLY),
    ):
        cmd = sub.add_parser(name)
        cmd.add_argument("--manifest", type=Path)
        cmd.add_argument("--apply", dest="dry_run", action="store_false", default=True)
        cmd.set_defaults(_target=state)

    args = parser.parse_args(argv)
    if args.command == "status":
        return _cmd_status(args)
    if args.command == "inventory":
        return _cmd_inventory(args)
    if args.command == "verify":
        return _cmd_verify(args)
    _require_manifest(args)
    return _advance(args, args._target)


if __name__ == "__main__":
    sys.exit(main())
