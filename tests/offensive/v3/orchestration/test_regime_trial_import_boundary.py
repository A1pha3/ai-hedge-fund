"""Plan Task 14 Step 3: source-tree boundary test for the Trial path.

The paired-trial runtime is the shadow-only forward measurement system: its
orchestrator, replay engine, proxy adapter, lifecycle, and CLI must never
reach broker packages, Gateway authority/decision writers,
``CapitalAuthorizationEnvelope``/``ExecutionPermit`` (even as imports of
contract data classes — the Trial path must not *name* the executable
authorization surface), activation methods, outbox/send claims, environment
policy overrides, legacy court/backtest imports, or the Plan 05
``shadow_trust`` composition helper (which manufactures synthetic
authorization envelopes for the executable daily-action flow).

The scan covers imports AND attribute calls, so a bare ``from ... import``
or a ``publish_entry(...)`` call is caught even when the payload is never
used. Registry files under ``tests/offensive/v3/contracts/`` and the
read-only compatibility layer are excluded by design (they must keep reading
old bytes); the production trial path itself must stay clean.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]

_TRIAL_MODULES = (
    "src/screening/offensive/v3/orchestration/paired_trial.py",
    "src/screening/offensive/v3/orchestration/replay.py",
    "src/screening/offensive/v3/execution/shadow_proxy.py",
    "src/screening/offensive/v3/execution/shadow_lifecycle.py",
    "src/cli/v3_regime_trial.py",
    "scripts/v3_regime_trial.py",
)

#: Broker packages and production adapters; the shadow path never imports
#: them, not even for type-only references. ``gateway.exits`` is the one
#: exception: the shadow exit lane is a durable, authority-free obligation
#: store that the lifecycle drives under the trial writer lease (the same
#: lease fences every exit-claim side effect); the Gateway *authority* and
#: *decision* writers stay forbidden.
_FORBIDDEN_EXACT_MODULES = (
    "src.screening.offensive.v3.execution.proxy",
    "src.screening.offensive.v3.execution.manual",
    "src.screening.offensive.v3.services.capital_gateway_api",
    "src.screening.offensive.v3.services.governance_api",
    "src.screening.offensive.v3.services.authorizer_api",
    "src.screening.offensive.v3.gateway.authority",
    "src.screening.offensive.v3.gateway.decisions",
)

#: Allowed gateway submodules (the exit-lane obligation store only).
_ALLOWED_GATEWAY_MODULES = ("src.screening.offensive.v3.gateway.exits",)

#: Substring markers for packages/types that must never appear at all.
_FORBIDDEN_IMPORT_MARKERS = (
    "broker.",
    "outbox",
    "shadow_trust",
)

#: The executable authorization surface (contracts included). The Trial
#: path must not name these types at all.
_FORBIDDEN_TYPE_MARKERS = (
    "CapitalAuthorizationEnvelope",
    "ExecutionPermit",
    "LineageGrant",
    "PolicyActivation",
    "ActivationEvidence",
)

#: Authority/outbox/legacy writes must never be called.
_FORBIDDEN_CALL_MARKERS = (
    "activate_",
    "publish_entry",
    "issue_permit",
    "claim_send",
    "make_outbox_durable",
    "record_delivery_outcome",
    "cancel_unclaimed_entry",
    "activate_policy_and_envelope",
    "activate_trust_bundle",
    "raise_entry_fence",
    "acknowledge_fence",
)

#: Legacy court/backtest imports are forbidden in the Trial path.
_FORBIDDEN_LEGACY_MARKERS = (
    "court",
    "backtest",
)


@pytest.mark.parametrize("module", _TRIAL_MODULES)
def test_trial_module_imports_no_forbidden_surface(module: str) -> None:
    path = _REPO_ROOT / module
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    segments: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                segments.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                segments.append(node.module)
    exact_violations = [
        name
        for name in segments
        if name in _FORBIDDEN_EXACT_MODULES
        or (
            name.startswith("src.screening.offensive.v3.gateway.")
            and name not in _ALLOWED_GATEWAY_MODULES
        )
    ]
    assert not exact_violations, (
        f"{module} imports a forbidden capability surface:\n  "
        + "\n  ".join(exact_violations)
    )
    haystack = " ".join(segments)
    violations = [m for m in _FORBIDDEN_IMPORT_MARKERS if m in haystack]
    assert not violations, (
        f"{module} imports a forbidden capability surface:\n  "
        + "\n  ".join(violations)
    )


@pytest.mark.parametrize("module", _TRIAL_MODULES)
def test_trial_module_has_no_forbidden_calls_or_types(module: str) -> None:
    path = _REPO_ROOT / module
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    call_haystack = "".join(
        ast.get_source_segment(source, node) or ""
        for node in ast.walk(tree)
        if isinstance(node, (ast.Call, ast.Import, ast.ImportFrom))
    )
    violations = [m for m in _FORBIDDEN_CALL_MARKERS if m in call_haystack]
    assert not violations, (
        f"{module} calls a forbidden capability surface:\n  "
        + "\n  ".join(violations)
    )
    name_haystack = "".join(
        ast.get_source_segment(source, node) or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
    )
    type_violations = [
        m for m in _FORBIDDEN_TYPE_MARKERS if m in name_haystack
    ]
    assert not type_violations, (
        f"{module} names a forbidden executable-authority type:\n  "
        + "\n  ".join(type_violations)
    )


@pytest.mark.parametrize("module", _TRIAL_MODULES)
def test_trial_module_has_no_legacy_court_or_backtest_imports(
    module: str,
) -> None:
    path = _REPO_ROOT / module
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    haystack = "".join(
        ast.get_source_segment(source, node) or ""
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    )
    violations = [m for m in _FORBIDDEN_LEGACY_MARKERS if m in haystack]
    assert not violations, (
        f"{module} imports a legacy court/backtest surface:\n  "
        + "\n  ".join(violations)
    )


def test_trial_modules_exist() -> None:
    """The boundary scan guards real files; a renamed module must fail RED."""
    for module in _TRIAL_MODULES:
        assert (_REPO_ROOT / module).is_file(), f"missing module: {module}"
