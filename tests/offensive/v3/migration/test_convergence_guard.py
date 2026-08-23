"""Plan 06 Task 2 (RED): v2 资本 mutator 收敛守卫 (AST 调用点清单).

任何新增的直接 v2 资本写调用都必须经 CompatibilityWriter; 绕过者在此处失败.
清单是显式的: 新调用点需要连同 compat 接线一起评审后才会进入白名单.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]

# v2 资本写方法全集 (与 ledger_repository.LedgerRepository 公共写面一致).
V2_LEDGER_MUTATORS = frozenset(
    {
        "create_plan",
        "create_plan_if_absent",
        "fill_plan",
        "settle_plan_at_open",
        "mark_exit_pending",
        "defer_exit",
        "close_trade",
        "skip_plan",
        "record_valuation",
        "record_position_mark",
    }
)

# 允许直接调用 v2 mutator 的生产文件 (Task 2 收敛目标: 全部经由 compat seam).
# daily_action_service 在 Task 2 完成接线前是已知遗留; 每收拢一处就删一行.
_ALLOWED_DIRECT_CALLERS = {
    "src/screening/offensive/ledger_repository.py",  # 自身定义
    "src/screening/offensive/daily_action_service.py",
    "src/screening/offensive/v3/migration/compat_writer.py",
}

_PRODUCTION_ROOTS = ("src", "scripts")


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for root in _PRODUCTION_ROOTS:
        files.extend(sorted((ROOT / root).rglob("*.py")))
    return files


def _mutator_calls(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in V2_LEDGER_MUTATORS:
                hits.append((node.lineno, node.func.attr))
    return hits


def test_no_unvetted_direct_v2_capital_mutator_calls() -> None:
    violations: list[str] = []
    for path in _iter_python_files():
        relative = path.relative_to(ROOT).as_posix()
        if relative in _ALLOWED_DIRECT_CALLERS:
            continue
        for lineno, name in _mutator_calls(path):
            violations.append(f"{relative}:{lineno} calls {name}()")
    assert violations == [], (
        "new direct v2 capital mutator call sites bypass the compatibility "
        "writer; route them through CompatibilityWriter or justify the "
        f"exception explicitly: {violations}"
    )


def test_allowlist_files_actually_exist() -> None:
    for relative in sorted(_ALLOWED_DIRECT_CALLERS):
        assert (ROOT / relative).exists(), f"stale allowlist entry: {relative}"


def test_ledger_repository_has_no_new_public_mutators() -> None:
    """LedgerRepository 新增公共写方法必须先登记进 V2_LEDGER_MUTATORS."""

    source = (
        ROOT / "src/screening/offensive/ledger_repository.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == "LedgerRepository"):
            continue
        public_methods = {
            item.name
            for item in node.body
            if isinstance(item, ast.FunctionDef) and not item.name.startswith("_")
        }
        unknown = public_methods - V2_LEDGER_MUTATORS - {
            "__init__",
            "__enter__",
            "__exit__",
            "initialize",
            "open_trades",
            "planned_trades",
            "get_trade",
            "latest_valuation",
            "latest_position_mark",
            "cash_balance",
            "count_events",
            # event_occurred_at (2026-08-23): 纯只读单事件时刻查询 (渲染对账用,
            # 与 count_events 同族读面), 无写入面 — 只读白名单登记.
            "event_occurred_at",
            "count_exit_defers",
            "count_trades",
        }
        assert unknown == set(), (
            f"new public LedgerRepository methods need convergence review: {unknown}"
        )
