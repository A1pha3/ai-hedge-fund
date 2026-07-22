"""Adversarial dependency-direction checks for the lowest v3 contract layer."""

from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[4]
CONTRACTS = ROOT / "src/screening/offensive/v3/contracts"
FORBIDDEN_ROOTS = {
    "aiohttp",
    "httpx",
    "numpy",
    "pandas",
    "requests",
    "socket",
    "sqlalchemy",
    "sqlite3",
    "urllib",
}
FORBIDDEN_V3_SEGMENTS = {
    "broker",
    "capital.repository",
    "cli",
    "dispatcher",
    "execution",
    "gateway",
    "repository",
    "services",
    "storage",
}
FORBIDDEN_ANNOTATIONS = {
    "Any",
    "Connection",
    "Cursor",
    "DataFrame",
    "Dict",
    "List",
    "Mapping",
    "MutableMapping",
    "Session",
    "Set",
    "dict",
    "list",
    "set",
}
CONTRACTS_PACKAGE = ("src", "screening", "offensive", "v3", "contracts")
PROJECT_LOCAL_ROOTS = {"app", "scripts", "src", "tests"}


def _file_package(root: Path, path: Path) -> tuple[str, ...]:
    relative = path.relative_to(root)
    parent_parts = relative.parent.parts if relative.parent != Path(".") else ()
    return CONTRACTS_PACKAGE + parent_parts


def _resolved_import_targets(
    node: ast.Import | ast.ImportFrom,
    *,
    package: tuple[str, ...],
) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)

    if node.level:
        parents_to_remove = node.level - 1
        if parents_to_remove >= len(package):
            return ("<invalid-relative-import>",)
        base_parts = package[: len(package) - parents_to_remove]
    else:
        base_parts = ()
    if node.module:
        base_parts += tuple(node.module.split("."))

    targets = []
    for alias in node.names:
        alias_parts = () if alias.name == "*" else tuple(alias.name.split("."))
        targets.append(".".join(base_parts + alias_parts))
    return tuple(targets)


def _contains_path_pattern(parts: list[str], pattern: str) -> bool:
    pattern_parts = tuple(pattern.split("."))
    width = len(pattern_parts)
    return any(
        tuple(parts[index : index + width]) == pattern_parts
        for index in range(len(parts) - width + 1)
    )


def _scan_contract_imports(root: Path) -> list[str]:
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        package = _file_package(root, path)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for target in _resolved_import_targets(node, package=package):
                target_parts = tuple(target.split("."))
                root_name = target_parts[0]
                if root_name in FORBIDDEN_ROOTS:
                    violations.append(f"{path.relative_to(root)}:{node.lineno}: {target}")
                    continue
                if target == "<invalid-relative-import>":
                    violations.append(
                        f"{path.relative_to(root)}:{node.lineno}: {target}"
                    )
                    continue
                if root_name in PROJECT_LOCAL_ROOTS:
                    if target_parts[: len(CONTRACTS_PACKAGE)] != CONTRACTS_PACKAGE:
                        violations.append(
                            f"{path.relative_to(root)}:{node.lineno}: "
                            f"project boundary {target}"
                        )
                        continue
                lowered_parts = [part.lower() for part in target_parts]
                if any(
                    _contains_path_pattern(lowered_parts, pattern)
                    for pattern in FORBIDDEN_V3_SEGMENTS
                ):
                    violations.append(f"{path.relative_to(root)}:{node.lineno}: {target}")
    return violations


def _annotation_names(annotation: ast.expr) -> set[str]:
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            annotation = ast.parse(annotation.value, mode="eval").body
        except SyntaxError:
            return {annotation.value}
    names: set[str] = set()
    for node in ast.walk(annotation):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def test_contract_imports_are_storage_network_cli_broker_and_v2_free() -> None:
    assert _scan_contract_imports(CONTRACTS) == []


def test_import_scanner_catches_nested_relative_aliases(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir(parents=True)
    (nested / "leak.py").write_text(
        "from .. import storage\nfrom ... import daily_action\n",
        encoding="utf-8",
    )

    violations = _scan_contract_imports(tmp_path)

    assert len(violations) == 2
    assert "nested/leak.py:1" in violations[0]
    assert "src.screening.offensive.v3.contracts.storage" in violations[0]
    assert "nested/leak.py:2" in violations[1]
    assert "src.screening.offensive.v3.daily_action" in violations[1]


def test_import_scanner_rejects_all_project_siblings_and_allows_contracts(
    tmp_path: Path,
) -> None:
    (tmp_path / "root_relative.py").write_text(
        "from ..kernel import decide as run\n"
        "from ..policy import loader as policy_loader\n",
        encoding="utf-8",
    )
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "relative_escape.py").write_text(
        "from ...kernel import decide as run\n"
        "from ...policy import loader as policy_loader\n",
        encoding="utf-8",
    )
    (tmp_path / "absolute_siblings.py").write_text(
        "from src.screening.offensive.v3.kernel import decide as run\n"
        "import src.screening.offensive.v3.policy.loader as policy_loader\n"
        "from src.screening.offensive import daily_action as legacy\n",
        encoding="utf-8",
    )
    (tmp_path / "legal_contracts.py").write_text(
        "from . import base as base_contract\n"
        "from .decision import DecisionSeal as Seal\n"
        "from src.screening.offensive.v3.contracts import CapitalSnapshot as Snapshot\n",
        encoding="utf-8",
    )
    (nested / "legal_contracts.py").write_text(
        "from .. import base as base_contract\n"
        "from ..trust import Capability as RequiredCapability\n"
        "from ..kernel import KernelInput as Input\n"
        "from ..policy import PolicySnapshot as Policy\n",
        encoding="utf-8",
    )

    violations = _scan_contract_imports(tmp_path)

    assert len(violations) == 7
    rendered = "\n".join(violations)
    for module in (
        "src.screening.offensive.v3.kernel",
        "src.screening.offensive.v3.policy",
        "src.screening.offensive.daily_action",
    ):
        assert module in rendered
    assert "legal_contracts.py" not in rendered


def test_import_scanner_rejects_every_project_local_root(tmp_path: Path) -> None:
    (tmp_path / "project_local.py").write_text(
        "from src.tools.api import get_data as fetch\n"
        "from app.backend.auth import utils as auth_utils\n"
        "from .....tools import api as relative_api\n"
        "from scripts.setup_research import run as research_run\n"
        "from tests.offensive import helpers as test_helpers\n",
        encoding="utf-8",
    )
    (tmp_path / "legal_nonlocal.py").write_text(
        "import os\n"
        "from datetime import datetime as Instant\n"
        "from pydantic import BaseModel as Model\n"
        "from .base import CanonicalModel as Contract\n",
        encoding="utf-8",
    )

    violations = _scan_contract_imports(tmp_path)

    assert len(violations) == 5
    rendered = "\n".join(violations)
    for module in (
        "src.tools.api",
        "app.backend.auth.utils",
        "scripts.setup_research.run",
        "tests.offensive.helpers",
    ):
        assert module in rendered
    assert rendered.count("src.tools.api") == 2
    assert "legal_nonlocal.py" not in rendered


def test_dotted_forbidden_pattern_matches_complete_path_segments_only(
    tmp_path: Path,
) -> None:
    (tmp_path / "dotted.py").write_text(
        "from vendor.capital.repository import Store as Exact\n"
        "from vendor.capital.repository_helpers import Store as Helper\n",
        encoding="utf-8",
    )

    violations = _scan_contract_imports(tmp_path)

    assert len(violations) == 1
    assert "vendor.capital.repository.Store" in violations[0]
    assert "repository_helpers" not in violations[0]


def test_annotation_scanner_catches_attribute_and_string_forms() -> None:
    source = """
class BadPort:
    def one(self, value: pandas.DataFrame) -> None: ...
    def two(self, value: 'list[domain.Row]') -> None: ...
"""
    tree = ast.parse(source)
    annotations = [
        argument.annotation
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        for argument in (*node.args.args, *node.args.kwonlyargs)
        if argument.arg != "self" and argument.annotation is not None
    ]
    names = set().union(*(_annotation_names(annotation) for annotation in annotations))
    assert {"DataFrame", "list"} <= names


def test_ports_expose_no_forbidden_annotations_or_method_implementation() -> None:
    path = CONTRACTS / "ports.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    protocol_names = {
        "CapitalViewPort",
        "EvidenceQueryPort",
        "SealWriterPort",
        "CapabilityVerifier",
    }
    found: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name not in protocol_names:
            continue
        found.add(node.name)
        for method in (item for item in node.body if isinstance(item, ast.FunctionDef)):
            annotation_nodes = [
                argument.annotation
                for argument in (
                    *method.args.posonlyargs,
                    *method.args.args,
                    *method.args.kwonlyargs,
                )
                if argument.arg != "self" and argument.annotation is not None
            ]
            if method.returns is not None:
                annotation_nodes.append(method.returns)
            names = set().union(
                *(_annotation_names(annotation) for annotation in annotation_nodes)
            )
            forbidden = sorted(names & FORBIDDEN_ANNOTATIONS)
            if forbidden:
                violations.append(f"{node.name}.{method.name}: {forbidden}")
            executable = [
                item
                for item in method.body
                if not (
                    isinstance(item, ast.Expr)
                    and isinstance(item.value, ast.Constant)
                    and item.value.value in {Ellipsis, None}
                )
            ]
            if executable:
                violations.append(f"{node.name}.{method.name}: method body")
    assert found == protocol_names
    assert violations == []


def test_protocol_hints_resolve_in_both_fresh_import_orders() -> None:
    script = """
from pathlib import Path
import importlib
import inspect
import sys
from typing import get_type_hints

order = sys.argv[1]
root = Path(sys.argv[2]).resolve()
if order == 'contracts-first':
    contracts = importlib.import_module('src.screening.offensive.v3.contracts')
    assert 'src.screening.offensive.v3.trust' not in sys.modules
    trust = importlib.import_module('src.screening.offensive.v3.trust')
else:
    trust = importlib.import_module('src.screening.offensive.v3.trust')
    contracts = importlib.import_module('src.screening.offensive.v3.contracts')

assert Path(contracts.__file__).resolve() == root / 'src/screening/offensive/v3/contracts/__init__.py'
assert Path(trust.__file__).resolve() == root / 'src/screening/offensive/v3/trust/__init__.py'
assert contracts.ArtifactKind is trust.ArtifactKind
assert contracts.Capability is trust.Capability
assert contracts.SignedEnvelope is trust.SignedEnvelope
assert contracts.VerifiedIssuer is trust.VerifiedIssuer

protocols = (
    contracts.CapitalViewPort,
    contracts.EvidenceQueryPort,
    contracts.SealWriterPort,
    contracts.CapabilityVerifier,
)
for protocol in protocols:
    for name, method in inspect.getmembers(protocol, inspect.isfunction):
        if name.startswith('_'):
            continue
        hints = get_type_hints(method)
        assert hints, (protocol.__name__, name)
"""
    for order in ("contracts-first", "trust-first"):
        result = subprocess.run(
            [sys.executable, "-I", "-c", script, order, str(ROOT)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, f"{order}: {result.stderr or result.stdout}"


def test_contract_runtime_import_does_not_load_optional_runtime_layers() -> None:
    script = """
from pathlib import Path
import sys
import src.screening.offensive.v3.contracts as contracts

root = Path(sys.argv[1]).resolve()
assert Path(contracts.__file__).resolve() == root / 'src/screening/offensive/v3/contracts/__init__.py'
forbidden = (
    'src.screening.offensive.v3.trust',
    'sqlalchemy', 'pandas', 'numpy', 'requests', 'httpx', 'sqlite3',
    'src.cli.dispatcher',
)
loaded = sorted(name for name in sys.modules if any(name == item or name.startswith(item + '.') for item in forbidden))
assert loaded == [], loaded
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(ROOT)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
