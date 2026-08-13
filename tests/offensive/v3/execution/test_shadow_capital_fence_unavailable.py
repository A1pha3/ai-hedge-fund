"""Fail-closed boundary for the unfinished shadow capital writer fence.

The paired forward runner is disabled, but its lower-level capital mutation
facades are importable Python objects.  Until a capital-local fencing epoch,
writer takeover protocol, and durable operation binding exist, those facades
must reject *before* inspecting caller input or touching any decision, exit,
bar, or capital store.  Pure pricing/mechanical resolvers and read-only lot
origin queries are intentionally outside this boundary.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pytest

from src.screening.offensive.v3.execution.shadow_lifecycle import (
    ShadowProxyLifecycle,
)
from src.screening.offensive.v3.execution.shadow_proxy import (
    ShadowProxyAdapter,
    ShadowProxyError,
)
from src.screening.offensive.v3.capital.repository import CapitalRepository
from src.screening.offensive.v3.gateway.exits import ExitLane
from src.screening.offensive.v3.orchestration import replay


UTC = timezone.utc
NOW = datetime(2026, 8, 13, tzinfo=UTC)
ERROR_CODE = "shadow_capital_fence_authority_unavailable"


class _Poison:
    """Explodes on every form of observation used by these facades."""

    def __getattribute__(self, name: str):  # noqa: ANN204
        raise AssertionError(f"input observed before capital fence: {name}")

    def __iter__(self):  # noqa: ANN204
        raise AssertionError("input iterated before capital fence")

    def __getitem__(self, key):  # noqa: ANN204
        raise AssertionError(f"input indexed before capital fence: {key!r}")

    def __fspath__(self) -> str:
        raise AssertionError("path resolved before capital fence")


def _adapter() -> ShadowProxyAdapter:
    # Constructor setup is irrelevant to the public mutation boundary.  An
    # uninitialized instance also proves the guard does not read local state.
    return object.__new__(ShadowProxyAdapter)


def _lifecycle() -> ShadowProxyLifecycle:
    return object.__new__(ShadowProxyLifecycle)


def _capital_mutation_calls() -> tuple[tuple[str, Callable[[], object]], ...]:
    poison = _Poison()
    adapter = _adapter()
    lifecycle = _lifecycle()
    return (
        (
            "adapter.reserve_committed_pair",
            lambda: adapter.reserve_committed_pair(poison, poison),  # type: ignore[arg-type]
        ),
        (
            "adapter.execute_entries",
            lambda: adapter.execute_entries(
                poison,  # type: ignore[arg-type]
                poison,  # type: ignore[arg-type]
                mechanical_bindings=poison,  # type: ignore[arg-type]
                bars=poison,  # type: ignore[arg-type]
                scenario=poison,  # type: ignore[arg-type]
                command_at=poison,  # type: ignore[arg-type]
                send_deadline=poison,  # type: ignore[arg-type]
                target_session=poison,  # type: ignore[arg-type]
            ),
        ),
        (
            "adapter.settle_exit_line",
            lambda: adapter.settle_exit_line(
                poison,  # type: ignore[arg-type]
                repository=poison,  # type: ignore[arg-type]
                bars=poison,  # type: ignore[arg-type]
                scenario=poison,  # type: ignore[arg-type]
                command_at=poison,  # type: ignore[arg-type]
                send_deadline=poison,  # type: ignore[arg-type]
            ),
        ),
        (
            "lifecycle.advance_session",
            lambda: lifecycle.advance_session(poison, poison),  # type: ignore[arg-type]
        ),
        (
            "lifecycle.derive_exits",
            lambda: lifecycle.derive_exits(poison, poison),  # type: ignore[arg-type]
        ),
        (
            "lifecycle.execute_due_exits",
            lambda: lifecycle.execute_due_exits(
                poison, poison, poison, poison  # type: ignore[arg-type]
            ),
        ),
        (
            "lifecycle.close_valuation",
            lambda: lifecycle.close_valuation(
                poison, poison, poison  # type: ignore[arg-type]
            ),
        ),
        (
            "lifecycle.finalize_session",
            lambda: lifecycle.finalize_session(poison, poison),  # type: ignore[arg-type]
        ),
        (
            "replay.reserve_pair",
            lambda: replay.reserve_pair(
                input=poison,  # type: ignore[arg-type]
                arms=poison,  # type: ignore[arg-type]
                replay_store=poison,  # type: ignore[arg-type]
                lease=poison,
                pair_key=poison,  # type: ignore[arg-type]
            ),
        ),
        (
            "replay.drive_session_lifecycle",
            lambda: replay.drive_session_lifecycle(
                input=poison,  # type: ignore[arg-type]
                arms=poison,  # type: ignore[arg-type]
                replay_store=poison,  # type: ignore[arg-type]
                lease=poison,
                pair_key=poison,  # type: ignore[arg-type]
                session=poison,  # type: ignore[arg-type]
                facts=poison,  # type: ignore[arg-type]
                scenario_cost=poison,  # type: ignore[arg-type]
                clock=poison,  # type: ignore[arg-type]
            ),
        ),
        (
            "replay.apply_corporate_action",
            lambda: replay.apply_corporate_action(
                arms=poison,  # type: ignore[arg-type]
                action=poison,  # type: ignore[arg-type]
                as_of=NOW,
            ),
        ),
        (
            "replay.apply_restatement",
            lambda: replay.apply_restatement(
                arms=poison,  # type: ignore[arg-type]
                restatement=poison,  # type: ignore[arg-type]
                clock=poison,  # type: ignore[arg-type]
            ),
        ),
    )


def test_every_public_shadow_capital_mutation_rejects_before_input_access() -> None:
    # Keep this as one pytest item: the repository-wide offensive autouse
    # cache fixture is intentionally expensive and the table itself supplies
    # precise per-surface failure labels.
    for name, invoke in _capital_mutation_calls():
        with pytest.raises(ShadowProxyError) as rejected:
            invoke()

        assert rejected.value.code == ERROR_CODE, name
        assert rejected.value.details == {}, name


def _first_executable_statement(function: Callable[..., object]) -> ast.stmt:
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    node = tree.body[0]
    assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    statements = list(node.body)
    if (
        statements
        and isinstance(statements[0], ast.Expr)
        and isinstance(statements[0].value, ast.Constant)
        and isinstance(statements[0].value.value, str)
    ):
        statements.pop(0)
    assert statements
    return statements[0]


def test_capital_mutation_guard_is_the_first_executable_statement() -> None:
    """A later validation cannot accidentally move ahead of the fence."""

    functions = (
        ShadowProxyAdapter.reserve_committed_pair,
        ShadowProxyAdapter.execute_entries,
        ShadowProxyAdapter.settle_exit_line,
        ShadowProxyLifecycle.advance_session,
        ShadowProxyLifecycle.derive_exits,
        ShadowProxyLifecycle.execute_due_exits,
        ShadowProxyLifecycle.close_valuation,
        ShadowProxyLifecycle.finalize_session,
        replay.reserve_pair,
        replay.drive_session_lifecycle,
        replay.apply_corporate_action,
        replay.apply_restatement,
    )
    for function in functions:
        statement = _first_executable_statement(function)
        assert isinstance(statement, ast.Expr), function.__qualname__
        assert isinstance(statement.value, ast.Call), function.__qualname__
        assert isinstance(statement.value.func, ast.Name), function.__qualname__
        assert (
            statement.value.func.id == "_reject_shadow_capital_mutation"
        ), function.__qualname__
        assert statement.value.args == [], function.__qualname__
        assert statement.value.keywords == [], function.__qualname__


def test_read_only_and_pure_surfaces_are_not_mislabeled_as_mutations() -> None:
    """The stopgap is narrow: it does not erase read-only/pure primitives."""

    source = Path(inspect.getsourcefile(ShadowProxyAdapter) or "").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    adapter = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ShadowProxyAdapter"
    )
    lot_origin = next(
        node
        for node in adapter.body
        if isinstance(node, ast.FunctionDef) and node.name == "lot_origin"
    )
    assert not (
        isinstance(_first_non_docstring(lot_origin), ast.Expr)
        and isinstance(_first_non_docstring(lot_origin).value, ast.Call)
        and isinstance(_first_non_docstring(lot_origin).value.func, ast.Name)
        and _first_non_docstring(lot_origin).value.func.id
        == "_reject_shadow_capital_mutation"
    )


def test_authoritative_generic_exit_and_correction_apis_are_not_gated() -> None:
    """The stopgap never becomes an AccountCapitalTruth entry kill switch."""

    generic_authoritative_methods = (
        ExitLane.derive_exit_mandates,
        ExitLane.claim_due_exit_work,
        ExitLane.record_exit_attempt,
        CapitalRepository.apply_split_merge,
        CapitalRepository.close_valuation,
        CapitalRepository.restate_valuation,
        CapitalRepository.reopen_exit_obligations,
    )
    for method in generic_authoritative_methods:
        assert "_reject_shadow_capital_mutation" not in inspect.getsource(
            method
        ), method.__qualname__


def _first_non_docstring(node: ast.FunctionDef) -> ast.stmt:
    statements = list(node.body)
    if (
        statements
        and isinstance(statements[0], ast.Expr)
        and isinstance(statements[0].value, ast.Constant)
        and isinstance(statements[0].value.value, str)
    ):
        statements.pop(0)
    assert statements
    return statements[0]
