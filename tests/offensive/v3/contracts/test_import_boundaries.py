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


def _modules(node: ast.Import | ast.ImportFrom) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    return (node.module or "",)


def _inside_type_checking(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, ast.If):
            test = current.test
            if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
                return True
        current = parents.get(current)
    return False


def test_contract_imports_are_storage_network_cli_broker_and_v2_free() -> None:
    violations: list[str] = []
    for path in sorted(CONTRACTS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for module in _modules(node):
                root = module.split(".", 1)[0]
                if root in FORBIDDEN_ROOTS:
                    violations.append(f"{path.name}:{node.lineno}: {module}")
                lowered = module.lower()
                if any(segment in lowered for segment in FORBIDDEN_V3_SEGMENTS):
                    violations.append(f"{path.name}:{node.lineno}: {module}")
                if module.startswith("src.screening.offensive.") and ".v3." not in module:
                    violations.append(f"{path.name}:{node.lineno}: v2 runtime {module}")
                if "trust" in module and not _inside_type_checking(node, parents):
                    violations.append(
                        f"{path.name}:{node.lineno}: runtime trust dependency {module}"
                    )
    assert violations == []


def test_ports_expose_no_forbidden_boundary_annotations_or_method_implementation() -> None:
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
                arg.annotation
                for arg in (*method.args.posonlyargs, *method.args.args, *method.args.kwonlyargs)
                if arg.arg != "self" and arg.annotation is not None
            ]
            if method.returns is not None:
                annotation_nodes.append(method.returns)
            names = {
                item.id
                for annotation in annotation_nodes
                for item in ast.walk(annotation)
                if isinstance(item, ast.Name)
            }
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


def test_contract_runtime_import_does_not_load_trust_or_optional_runtime_layers() -> None:
    script = """
import sys
import src.screening.offensive.v3.contracts  # noqa: F401
forbidden = (
    'src.screening.offensive.v3.trust',
    'sqlalchemy', 'pandas', 'numpy', 'requests', 'httpx', 'sqlite3',
    'src.cli.dispatcher',
)
loaded = sorted(name for name in sys.modules if any(name == item or name.startswith(item + '.') for item in forbidden))
assert loaded == [], loaded
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
