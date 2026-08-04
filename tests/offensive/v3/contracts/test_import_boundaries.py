"""Adversarial dependency-direction checks for the lowest v3 contract layer."""

from __future__ import annotations

import ast
import io
from pathlib import Path
import re
import subprocess
import sys
import tokenize
import unicodedata

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / "src"
CONTRACTS = ROOT / "src/screening/offensive/v3/contracts"
POLICY = ROOT / "src/screening/offensive/v3/policy"
V3_SOURCE = ROOT / "src/screening/offensive/v3"
REVISION1_SOURCE_EXCLUSIONS = frozenset(
    {
        Path("screening/offensive/v3/contracts/revision1.py"),
        Path("screening/offensive/v3/contracts/revision1_primitives.py"),
    }
)
FORBIDDEN_PROJECT_SEGMENTS = {
    "broker",
    "capital.repository",
    "cli",
    "dispatcher",
    "gateway",
    "repository",
    "services",
    "storage",
    "v2",
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
POLICY_PACKAGE = ("src", "screening", "offensive", "v3", "policy")
TRUST_PACKAGE = ("src", "screening", "offensive", "v3", "trust")
PROJECT_LOCAL_ROOTS = {"app", "scripts", "src", "tests"}
CONTRACT_EXTERNAL_ROOTS = {
    "__future__",
    "base64",
    "binascii",
    "collections",
    "datetime",
    "decimal",
    "enum",
    "hashlib",
    "json",
    "math",
    "pydantic",
    "re",
    "types",
    "typing",
}
POLICY_EXTERNAL_ROOTS = {
    "__future__",
    "collections",
    "contextlib",
    "datetime",
    "decimal",
    "enum",
    "json",
    "os",
    "pathlib",
    "pydantic",
    "stat",
    "typing",
}
OBSOLETE_INTERFACE_NAMES = {
    "CapitalAuthorization",
    "CapitalAuthorizationBinding",
    "CapitalViewPort",
    "DecisionInput",
    "DecisionSeal",
    "DecisionSealBinding",
    "EdgeAuthorization",
    "ExplorationAuthorization",
    "PublishDecisionCommand",
    "RecoveryAuthorization",
    "SealedOrderLine",
    "SealWriterPort",
}
CONTROL_DOCUMENTS = (
    ROOT / "AGENTS.md",
    ROOT / "docs/superpowers/specs/2026-07-19-evidence-gated-growth-kernel-design.md",
    ROOT / "docs/superpowers/plans/2026-07-19-growth-kernel-roadmap.md",
    *tuple(
        ROOT
        / f"docs/superpowers/plans/2026-07-19-growth-kernel-{number:02d}-{suffix}.md"
        for number, suffix in (
            (1, "contracts-policy-trust"),
            (2, "sealed-capital-ledger"),
            (3, "evidence-stat-governance"),
            (4, "kernel-proxy-execution"),
            (5, "services-cli-reporting"),
            (6, "migration-shadow-canary"),
            (7, "broker-gateway"),
        )
    ),
)


def _file_package(
    root: Path,
    path: Path,
    *,
    package_root: tuple[str, ...] = CONTRACTS_PACKAGE,
) -> tuple[str, ...]:
    relative = path.relative_to(root)
    parent_parts = relative.parent.parts if relative.parent != Path(".") else ()
    return package_root + parent_parts


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


def _scan_layer_imports(
    root: Path,
    *,
    package_root: tuple[str, ...],
    allowed_project_prefixes: tuple[tuple[str, ...], ...],
    allowed_external_roots: frozenset[str] | set[str],
) -> list[str]:
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        is_revision1_module = package_root == CONTRACTS_PACKAGE and relative in {
            Path("revision1.py"),
            Path("revision1_primitives.py"),
        }
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        package = _file_package(root, path, package_root=package_root)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for target in _resolved_import_targets(node, package=package):
                target_parts = tuple(target.split("."))
                root_name = target_parts[0]
                if target == "<invalid-relative-import>":
                    violations.append(
                        f"{path.relative_to(root)}:{node.lineno}: {target}"
                    )
                    continue
                if any(
                    part in {"revision1", "revision1_primitives"}
                    for part in target_parts
                ):
                    if not is_revision1_module:
                        violations.append(
                            f"{path.relative_to(root)}:{node.lineno}: "
                            f"obsolete compatibility import {target}"
                        )
                    continue
                if root_name in PROJECT_LOCAL_ROOTS:
                    if not any(
                        target_parts[: len(prefix)] == prefix
                        for prefix in allowed_project_prefixes
                    ):
                        violations.append(
                            f"{path.relative_to(root)}:{node.lineno}: "
                            f"project boundary {target}"
                        )
                        continue
                    lowered_parts = [part.lower() for part in target_parts]
                    if any(
                        _contains_path_pattern(lowered_parts, pattern)
                        for pattern in FORBIDDEN_PROJECT_SEGMENTS
                    ):
                        violations.append(
                            f"{path.relative_to(root)}:{node.lineno}: {target}"
                        )
                    continue
                if root_name not in allowed_external_roots:
                    violations.append(
                        f"{path.relative_to(root)}:{node.lineno}: "
                        f"external import is not allowlisted: {target}"
                    )
    return violations


def _scan_contract_imports(root: Path) -> list[str]:
    return _scan_layer_imports(
        root,
        package_root=CONTRACTS_PACKAGE,
        allowed_project_prefixes=(CONTRACTS_PACKAGE,),
        allowed_external_roots=CONTRACT_EXTERNAL_ROOTS,
    )


def _assignment_names(target: ast.expr) -> tuple[str, ...]:
    if isinstance(target, ast.Name):
        return (target.id,)
    if isinstance(target, (ast.List, ast.Tuple)):
        return tuple(
            name for element in target.elts for name in _assignment_names(element)
        )
    return ()


def _scan_obsolete_interfaces(
    root: Path,
    *,
    exclusions: frozenset[Path],
) -> list[str]:
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if relative in exclusions:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            found: tuple[str, ...] = ()
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                found = (node.name,)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                module_parts = (
                    tuple(node.module.split("."))
                    if isinstance(node, ast.ImportFrom) and node.module
                    else ()
                )
                imported_modules = module_parts + tuple(
                    part for alias in node.names for part in alias.name.split(".")
                )
                if any(
                    part in {"revision1", "revision1_primitives"}
                    for part in imported_modules
                ):
                    imported_names = ", ".join(alias.name for alias in node.names)
                    violations.append(
                        f"{relative}:{node.lineno}: revision1 module import: "
                        f"{imported_names}"
                    )
                    continue
                found = tuple(
                    name
                    for alias in node.names
                    for name in (alias.name.rsplit(".", 1)[-1], alias.asname)
                    if name is not None
                )
            elif isinstance(node, ast.Attribute):
                found = (node.attr,)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                found = (node.id,)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                found = tuple(
                    name
                    for name in OBSOLETE_INTERFACE_NAMES
                    if re.search(
                        rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])",
                        node.value,
                    )
                )
            elif isinstance(node, ast.Assign):
                found = tuple(
                    name
                    for target in node.targets
                    for name in _assignment_names(target)
                )
            elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
                found = _assignment_names(node.target)
            for name in found:
                if name in OBSOLETE_INTERFACE_NAMES:
                    violations.append(f"{relative}:{node.lineno}: {name}")
    return violations


def _scan_lexical_historical_context(paths: tuple[Path, ...]) -> list[str]:
    english_history_marker = re.compile(
        r"(?<![A-Za-z0-9_])"
        r"(?:revision\s*1|r1|legacy|obsolete|compatibility|historical|history|deprecated)"
        r"(?![A-Za-z0-9_])",
        flags=re.IGNORECASE,
    )
    chinese_history_markers = (
        "旧",
        "历史",
        "兼容",
        "废弃",
    )
    violations: list[str] = []
    for path in paths:
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            names = sorted(
                name
                for name in OBSOLETE_INTERFACE_NAMES
                if re.search(
                    rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])",
                    line,
                )
            )
            has_history_marker = bool(english_history_marker.search(line)) or any(
                marker in line for marker in chinese_history_markers
            )
            if names and not has_history_marker:
                violations.append(
                    f"{path.relative_to(ROOT) if path.is_relative_to(ROOT) else path.name}:"
                    f"{line_number}: {', '.join(names)}"
                )
    return violations


GROWTH_KERNEL_PORT_NAME = "GrowthKernelPort"
GROWTH_KERNEL_ALLOWED_PATHS = frozenset(
    {
        Path("screening/offensive/v3/contracts/ports.py"),
        Path("screening/offensive/v3/contracts/__init__.py"),
    }
)


def _growth_kernel_allowed_coordinates(
    relative: Path,
    tree: ast.Module,
    tokens: tuple[tokenize.TokenInfo, ...],
    source_lines: tuple[str, ...],
) -> set[tuple[int, int]]:
    if relative not in GROWTH_KERNEL_ALLOWED_PATHS:
        return set()

    def character_coordinate(node: ast.AST) -> tuple[int, int]:
        line = source_lines[node.lineno - 1]
        byte_prefix = line.encode("utf-8")[: node.col_offset]
        return node.lineno, len(byte_prefix.decode("utf-8"))

    def targets_all(node: ast.stmt) -> bool:
        if isinstance(node, ast.Assign):
            return any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            )
        if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            return isinstance(node.target, ast.Name) and node.target.id == "__all__"
        return False

    all_statements = [node for node in tree.body if targets_all(node)]
    if len(all_statements) != 1:
        return set()
    all_statement = all_statements[0]
    if isinstance(all_statement, ast.Assign):
        if (
            len(all_statement.targets) != 1
            or not isinstance(all_statement.targets[0], ast.Name)
            or all_statement.targets[0].id != "__all__"
        ):
            return set()
        all_value = all_statement.value
    elif isinstance(all_statement, ast.AnnAssign):
        if (
            not isinstance(all_statement.target, ast.Name)
            or all_statement.target.id != "__all__"
            or not all_statement.simple
        ):
            return set()
        all_value = all_statement.value
    else:
        return set()
    if not isinstance(all_value, (ast.List, ast.Tuple)):
        return set()
    growth_elements = [
        element
        for element in all_value.elts
        if isinstance(element, ast.Constant)
        and element.value == GROWTH_KERNEL_PORT_NAME
    ]
    if len(growth_elements) != 1:
        return set()

    token_by_start = {token.start: token for token in tokens}
    all_coordinate = character_coordinate(growth_elements[0])
    allowed: set[tuple[int, int]] = {all_coordinate}
    if relative.name == "ports.py":
        classes = [
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == GROWTH_KERNEL_PORT_NAME
        ]
        if len(classes) != 1:
            return set()
        class_node = classes[0]
        class_names = [
            token
            for token in tokens
            if token.start[0] == class_node.lineno
            and token.type == tokenize.NAME
            and token.string == GROWTH_KERNEL_PORT_NAME
        ]
        if len(class_names) != 1:
            return set()
        allowed.add(class_names[0].start)
        return allowed

    imports = [
        (node, alias)
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.level == 1
        and node.module == "ports"
        for alias in node.names
        if alias.name == GROWTH_KERNEL_PORT_NAME and alias.asname is None
    ]
    if len(imports) != 1:
        return set()
    import_coordinate = character_coordinate(imports[0][1])
    import_token = token_by_start.get(import_coordinate)
    if (
        import_token is None
        or import_token.type != tokenize.NAME
        or import_token.string != GROWTH_KERNEL_PORT_NAME
    ):
        return set()
    allowed.add(import_coordinate)
    return allowed


def _is_contract_star_import(relative: Path, node: ast.ImportFrom) -> bool:
    if not any(alias.name == "*" for alias in node.names):
        return False
    relative_package = relative.parent.parts
    package = (
        relative_package
        if relative_package[:1] == ("src",)
        else ("src",) + relative_package
    )
    for target in _resolved_import_targets(node, package=package):
        parts = tuple(part for part in target.split(".") if part)
        if parts[-1:] == ("__init__",):
            parts = parts[:-1]
        if parts in {
            ("src", "screening", "offensive", "v3", "contracts"),
            ("src", "screening", "offensive", "v3", "contracts", "ports"),
        }:
            return True
    return False


def _scan_growth_kernel_port_references(root: Path) -> list[str]:
    """Fail closed on every static production reference outside two exports."""

    violations: list[str] = []
    token_pattern = re.compile(
        rf"(?<![A-Za-z0-9_]){GROWTH_KERNEL_PORT_NAME}(?![A-Za-z0-9_])"
    )
    paths = sorted({*root.rglob("*.py"), *root.rglob("*.pyi")})
    for path in paths:
        relative = path.relative_to(root)
        source = path.read_text(encoding="utf-8")
        try:
            parsed = ast.parse(source, filename=str(path))
            tokens = tuple(tokenize.generate_tokens(io.StringIO(source).readline))
        except (SyntaxError, tokenize.TokenError) as exc:
            line = getattr(exc, "lineno", None) or 1
            violations.append(f"{relative}:{line}: source is not statically scannable")
            continue
        source_lines = tuple(source.splitlines(keepends=True))
        allowed = _growth_kernel_allowed_coordinates(
            relative,
            parsed,
            tokens,
            source_lines,
        )
        emitted: set[tuple[int, int]] = set()

        def emit(line: int, column: int, detail: str) -> None:
            coordinate = (line, column)
            if coordinate in allowed or coordinate in emitted:
                return
            emitted.add(coordinate)
            violations.append(f"{relative}:{line}: {detail}")

        for token in tokens:
            if (
                token.type == tokenize.NAME
                and unicodedata.normalize("NFKC", token.string)
                == GROWTH_KERNEL_PORT_NAME
            ):
                emit(*token.start, "static GrowthKernelPort name")
                continue
            if token.type != tokenize.STRING:
                continue
            try:
                value = ast.literal_eval(token.string)
            except (SyntaxError, ValueError):
                continue
            if isinstance(value, str) and token_pattern.search(value):
                emit(*token.start, "quoted GrowthKernelPort token")

        for node in ast.walk(parsed):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and token_pattern.search(node.value)
            ):
                line = source_lines[node.lineno - 1]
                byte_prefix = line.encode("utf-8")[: node.col_offset]
                emit(
                    node.lineno,
                    len(byte_prefix.decode("utf-8")),
                    "quoted GrowthKernelPort token",
                )
            elif isinstance(node, ast.ImportFrom) and _is_contract_star_import(
                relative, node
            ):
                line = source_lines[node.lineno - 1]
                byte_prefix = line.encode("utf-8")[: node.col_offset]
                emit(
                    node.lineno,
                    len(byte_prefix.decode("utf-8")),
                    "contracts star import",
                )
    return violations


def _annotation_names(annotation: ast.expr) -> set[str]:
    names: set[str] = set()

    def terminal_name(node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def collect_type_position(node: ast.AST) -> None:
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, str):
                return
            try:
                parsed = ast.parse(node.value, mode="eval").body
            except SyntaxError:
                return
            collect_type_position(parsed)
            return
        if isinstance(node, ast.Name):
            names.add(node.id)
            return
        if isinstance(node, ast.Attribute):
            collect_type_position(node.value)
            names.add(node.attr)
            return
        if isinstance(node, ast.Subscript):
            collect_type_position(node.value)
            arguments = (
                tuple(node.slice.elts)
                if isinstance(node.slice, ast.Tuple)
                else (node.slice,)
            )
            constructor = terminal_name(node.value)
            if constructor == "Literal":
                return
            if constructor == "Annotated":
                if arguments:
                    collect_type_position(arguments[0])
                return
            for argument in arguments:
                collect_type_position(argument)
            return
        for child in ast.iter_child_nodes(node):
            collect_type_position(child)

    collect_type_position(annotation)
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
        "from src.screening.offensive.v3.execution import submit as execute\n"
        "from src.screening.offensive import daily_action as legacy\n",
        encoding="utf-8",
    )
    (tmp_path / "legal_contracts.py").write_text(
        "from . import base as base_contract\n"
        "from .execution import ExecutionRevision as Revision\n"
        "from .decision import PortfolioDecision as Proposal\n"
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

    assert len(violations) == 8
    rendered = "\n".join(violations)
    for module in (
        "src.screening.offensive.v3.kernel",
        "src.screening.offensive.v3.policy",
        "src.screening.offensive.v3.execution",
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
        "import json\n"
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


def test_external_allowlist_matches_complete_root_segments_only(
    tmp_path: Path,
) -> None:
    (tmp_path / "dotted.py").write_text(
        "from json import loads as Allowed\n"
        "from json_helpers import loads as Rejected\n",
        encoding="utf-8",
    )

    violations = _scan_contract_imports(tmp_path)

    assert len(violations) == 1
    assert "json_helpers.loads" in violations[0]
    assert "json.loads" not in violations[0]


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


def test_annotation_scanner_parses_only_nested_forward_reference_type_positions() -> (
    None
):
    source = """
class NestedPort:
    def tuple_forward(self, value: tuple['list[int]', ...]) -> None: ...
    def optional_forward(self, value: typing.Optional['pandas.DataFrame']) -> None: ...
    def literal_value(self, value: Literal['list']) -> None: ...
    def annotated_metadata(self, value: Annotated[str, 'pandas.DataFrame']) -> None: ...
    def annotated_nested(
        self,
        value: typing.Annotated[tuple['list[int]', ...], 'pandas.DataFrame'],
    ) -> None: ...
"""
    tree = ast.parse(source)
    annotations = {
        node.name: next(
            argument.annotation
            for argument in node.args.args
            if argument.arg == "value"
        )
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }

    assert "list" in _annotation_names(annotations["tuple_forward"])
    assert "DataFrame" in _annotation_names(annotations["optional_forward"])
    assert "list" not in _annotation_names(annotations["literal_value"])
    assert "DataFrame" not in _annotation_names(annotations["annotated_metadata"])
    assert "list" in _annotation_names(annotations["annotated_nested"])
    assert "DataFrame" not in _annotation_names(annotations["annotated_nested"])


def test_ports_expose_no_forbidden_annotations_or_method_implementation() -> None:
    path = CONTRACTS / "ports.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    protocol_names = {
        "AuthorizationQueryPort",
        "CapitalGatewayCommandPort",
        "CapitalGatewayReadPort",
        "EvidenceQueryPort",
        "GrowthKernelPort",
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
    contracts.AuthorizationQueryPort,
    contracts.CapitalGatewayCommandPort,
    contracts.CapitalGatewayReadPort,
    contracts.EvidenceQueryPort,
    contracts.GrowthKernelPort,
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
    'src.screening.offensive.v3.execution',
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


def test_final_top_level_omits_revision1_decision_and_seal_apis() -> None:
    import importlib

    from src.screening.offensive.v3 import contracts

    obsolete = {
        "CapitalAuthorizationBinding",
        "CapitalViewPort",
        "DecisionInput",
        "DecisionSeal",
        "DecisionSealBinding",
        "PublishDecisionCommand",
        "SealedOrderLine",
        "SealWriterPort",
    }
    final_replacements = {"ExecutionPermit", "ShadowDecision"}
    assert obsolete.isdisjoint(contracts.__all__)
    assert final_replacements <= set(contracts.__all__)
    assert hasattr(contracts, "CapitalGatewayCommandPort")

    revision1 = importlib.import_module(
        "src.screening.offensive.v3.contracts.revision1"
    )
    revision1_names = obsolete | final_replacements
    assert revision1_names <= set(revision1.__all__)
    for name in revision1_names:
        assert getattr(revision1, name).__module__.startswith(
            "src.screening.offensive.v3.contracts"
        )
    for name in final_replacements:
        assert getattr(contracts, name) is not getattr(revision1, name)


def test_final_proposal_models_do_not_reference_revision1_types() -> None:
    from src.screening.offensive.v3.contracts import PortfolioDecision

    annotations = " ".join(
        str(field.annotation) for field in PortfolioDecision.model_fields.values()
    )
    for obsolete in (
        "CapitalAuthorizationEnvelope",
        "AuthorizationStatus",
        "CapitalRiskSnapshot",
        "DecisionInput",
        "DecisionSeal",
        "PublishDecisionCommand",
        "SealedOrderLine",
    ):
        assert obsolete not in annotations


def test_contract_and_policy_layers_have_only_explicit_domain_dependencies() -> None:
    assert (
        _scan_layer_imports(
            CONTRACTS,
            package_root=CONTRACTS_PACKAGE,
            allowed_project_prefixes=(CONTRACTS_PACKAGE,),
            allowed_external_roots=CONTRACT_EXTERNAL_ROOTS,
        )
        == []
    )
    assert (
        _scan_layer_imports(
            POLICY,
            package_root=POLICY_PACKAGE,
            allowed_project_prefixes=(CONTRACTS_PACKAGE, POLICY_PACKAGE, TRUST_PACKAGE),
            allowed_external_roots=POLICY_EXTERNAL_ROOTS,
        )
        == []
    )


def test_policy_import_scanner_rejects_storage_network_pandas_v2_and_siblings(
    tmp_path: Path,
) -> None:
    (tmp_path / "bad.py").write_text(
        "import pandas\n"
        "from ..storage import repository\n"
        "from vendor.v2 import compatibility\n"
        "from src.screening.offensive.v3.gateway import authority\n"
        "from src.screening.offensive import daily_action\n",
        encoding="utf-8",
    )
    (tmp_path / "good.py").write_text(
        "from ..contracts import PortfolioDecision\n"
        "from ..trust import CapabilityVerifier\n"
        "from .models import PolicySnapshot\n",
        encoding="utf-8",
    )

    violations = _scan_layer_imports(
        tmp_path,
        package_root=POLICY_PACKAGE,
        allowed_project_prefixes=(CONTRACTS_PACKAGE, POLICY_PACKAGE, TRUST_PACKAGE),
        allowed_external_roots=POLICY_EXTERNAL_ROOTS,
    )

    assert len(violations) == 5
    rendered = "\n".join(violations)
    for forbidden in ("pandas", "storage", "vendor.v2", "gateway", "daily_action"):
        assert forbidden in rendered
    assert "good.py" not in rendered


def test_obsolete_interfaces_are_confined_to_exact_revision1_modules() -> None:
    assert REVISION1_SOURCE_EXCLUSIONS == frozenset(
        {
            Path("screening/offensive/v3/contracts/revision1.py"),
            Path("screening/offensive/v3/contracts/revision1_primitives.py"),
        }
    )
    assert (
        _scan_obsolete_interfaces(
            SOURCE,
            exclusions=REVISION1_SOURCE_EXCLUSIONS,
        )
        == []
    )


def test_obsolete_interface_scanner_has_exact_exclusions_and_catches_all_forms(
    tmp_path: Path,
) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "revision1.py").write_text(
        "class DecisionSeal: ...\n",
        encoding="utf-8",
    )
    (contracts / "revision1_primitives.py").write_text(
        "CapitalAuthorization = object\n",
        encoding="utf-8",
    )
    (tmp_path / "adapter.py").write_text(
        "from .contracts.revision1 import DecisionSeal as LegacySeal\n"
        "class SealWriterPort: ...\n"
        "value = compatibility.CapitalAuthorization\n"
        "DecisionInput = object\n",
        encoding="utf-8",
    )

    violations = _scan_obsolete_interfaces(
        tmp_path,
        exclusions=frozenset(
            {
                Path("contracts/revision1.py"),
                Path("contracts/revision1_primitives.py"),
            }
        ),
    )

    assert len(violations) == 4
    rendered = "\n".join(violations)
    assert "revision1.py" not in rendered
    assert "revision1_primitives.py" not in rendered
    for obsolete in (
        "DecisionSeal",
        "SealWriterPort",
        "CapitalAuthorization",
        "DecisionInput",
    ):
        assert obsolete in rendered


def test_obsolete_scanner_rejects_revision1_star_name_annotation_and_getattr(
    tmp_path: Path,
) -> None:
    (tmp_path / "star.py").write_text(
        "from src.screening.offensive.v3.contracts.revision1 import *\n",
        encoding="utf-8",
    )
    (tmp_path / "uses.py").write_text(
        "def consume(value: DecisionSeal) -> CapitalAuthorization:\n"
        "    return DecisionInput(value)\n"
        "legacy = getattr(contracts, 'SealWriterPort')\n",
        encoding="utf-8",
    )

    violations = _scan_obsolete_interfaces(tmp_path, exclusions=frozenset())

    rendered = "\n".join(violations)
    assert "revision1 module import" in rendered
    for obsolete in (
        "DecisionSeal",
        "CapitalAuthorization",
        "DecisionInput",
        "SealWriterPort",
    ):
        assert obsolete in rendered


def test_control_documents_mark_every_obsolete_name_as_historical() -> None:
    assert _scan_lexical_historical_context(CONTROL_DOCUMENTS) == []


def test_document_scanner_requires_lexical_history_marker_not_path_allowlist(
    tmp_path: Path,
) -> None:
    unmarked = tmp_path / "unmarked.md"
    marked = tmp_path / "marked.md"
    unmarked.write_text(
        "The DecisionSeal is the final stable gateway return.\n",
        encoding="utf-8",
    )
    marked.write_text(
        "Revision 1 compatibility retained the legacy DecisionSeal only.\n"
        "历史接口 CapitalAuthorization 不得作为最终授权。\n",
        encoding="utf-8",
    )

    violations = _scan_lexical_historical_context((unmarked, marked))

    assert len(violations) == 1
    assert "unmarked.md:1" in violations[0]
    assert "DecisionSeal" in violations[0]


def test_document_history_markers_are_token_aware(tmp_path: Path) -> None:
    misleading = tmp_path / "misleading.md"
    misleading.write_text(
        "server1 returns DecisionSeal as the final stable receipt.\n",
        encoding="utf-8",
    )

    violations = _scan_lexical_historical_context((misleading,))

    assert len(violations) == 1
    assert "DecisionSeal" in violations[0]


def test_external_imports_are_allowlisted_not_denylisted(tmp_path: Path) -> None:
    forbidden_modules = (
        "urllib3",
        "http.client",
        "boto3",
        "psycopg",
        "redis",
        "ftplib",
        "websockets",
    )
    (tmp_path / "external.py").write_text(
        "\n".join(f"import {module}" for module in forbidden_modules) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "revision.py").write_text(
        "from src.screening.offensive.v3.contracts import revision1\n",
        encoding="utf-8",
    )

    violations = _scan_layer_imports(
        tmp_path,
        package_root=POLICY_PACKAGE,
        allowed_project_prefixes=(CONTRACTS_PACKAGE, POLICY_PACKAGE, TRUST_PACKAGE),
        allowed_external_roots=POLICY_EXTERNAL_ROOTS,
    )

    rendered = "\n".join(violations)
    for module in (*forbidden_modules, "revision1"):
        assert module in rendered


def test_growth_kernel_port_static_references_are_confined_to_exact_exports() -> None:
    assert _scan_growth_kernel_port_references(SOURCE) == []


def test_growth_kernel_port_guard_allows_only_definition_and_explicit_export(
    tmp_path: Path,
) -> None:
    contracts = tmp_path / "screening/offensive/v3/contracts"
    contracts.mkdir(parents=True)
    (contracts / "ports.py").write_text(
        "from typing import Protocol\n"
        "class GrowthKernelPort(Protocol): ...\n"
        "__all__ = ['GrowthKernelPort']\n",
        encoding="utf-8",
    )
    (contracts / "__init__.py").write_text(
        "from .ports import GrowthKernelPort\n__all__ = ['GrowthKernelPort']\n",
        encoding="utf-8",
    )

    assert _scan_growth_kernel_port_references(tmp_path) == []

    with (contracts / "ports.py").open("a", encoding="utf-8") as handle:
        handle.write("LeakedAlias = GrowthKernelPort\n")
    with (contracts / "__init__.py").open("a", encoding="utf-8") as handle:
        handle.write("leaked_text = 'GrowthKernelPort'\n")

    rendered = "\n".join(_scan_growth_kernel_port_references(tmp_path))
    assert "contracts/ports.py:4:" in rendered
    assert "contracts/__init__.py:3:" in rendered


def test_growth_kernel_port_allowed_coordinates_are_strictly_top_level(
    tmp_path: Path,
) -> None:
    contracts = tmp_path / "screening/offensive/v3/contracts"
    contracts.mkdir(parents=True)
    (contracts / "ports.py").write_text(
        "class GrowthKernelPort: leaked = GrowthKernelPort\n"
        "def nested():\n"
        "    class GrowthKernelPort: ...\n"
        "    __all__ = ['GrowthKernelPort']\n"
        "__all__ = {'GrowthKernelPort'}\n",
        encoding="utf-8",
    )
    (contracts / "__init__.py").write_text(
        "def nested():\n"
        "    from .ports import GrowthKernelPort\n"
        "    __all__ = ('GrowthKernelPort',)\n"
        "__all__ = {'GrowthKernelPort'}\n",
        encoding="utf-8",
    )

    rendered = "\n".join(_scan_growth_kernel_port_references(tmp_path))

    for line in (1, 3, 4, 5):
        assert f"contracts/ports.py:{line}:" in rendered
    for line in (2, 3, 4):
        assert f"contracts/__init__.py:{line}:" in rendered


def test_growth_kernel_port_allowed_exports_are_unique_and_unchained(
    tmp_path: Path,
) -> None:
    contracts = tmp_path / "screening/offensive/v3/contracts"
    contracts.mkdir(parents=True)
    (contracts / "ports.py").write_text(
        "class GrowthKernelPort: ...\n"
        "class GrowthKernelPort: ...\n"
        "__all__ = ['GrowthKernelPort']\n"
        "__all__ = ['GrowthKernelPort']\n",
        encoding="utf-8",
    )
    (contracts / "__init__.py").write_text(
        "from .ports import GrowthKernelPort\n"
        "from .ports import GrowthKernelPort\n"
        "leak = __all__ = ['GrowthKernelPort']\n",
        encoding="utf-8",
    )

    rendered = "\n".join(_scan_growth_kernel_port_references(tmp_path))

    for line in range(1, 5):
        assert f"contracts/ports.py:{line}:" in rendered
    for line in range(1, 4):
        assert f"contracts/__init__.py:{line}:" in rendered


def test_growth_kernel_port_guard_normalizes_names_and_coordinates(
    tmp_path: Path,
) -> None:
    (tmp_path / "unicode_name.py").write_text(
        "value = contracts.ＧrowthKernelPort\n",
        encoding="utf-8",
    )
    contracts = tmp_path / "screening/offensive/v3/contracts"
    contracts.mkdir(parents=True)
    (contracts / "ports.py").write_text(
        "变变变变变变变变变变变变变=0;"
        '__all__=["Growth" "KernelPort"];x= GrowthKernelPort\n',
        encoding="utf-8",
    )

    rendered = "\n".join(_scan_growth_kernel_port_references(tmp_path))

    assert "unicode_name.py:1:" in rendered
    assert "contracts/ports.py:1:" in rendered


def test_growth_kernel_port_guard_rejects_every_downstream_static_form(
    tmp_path: Path,
) -> None:
    cases = {
        "imported.py": (
            "from src.screening.offensive.v3.contracts import GrowthKernelPort\n"
        ),
        "attribute.py": "value = contracts.GrowthKernelPort\n",
        "direct.py": ("Alias = GrowthKernelPort[KernelInput, NoTradeDecision]\n"),
        "runtime.py": "check = isinstance(value, GrowthKernelPort)\n",
        "quoted.py": 'value: "GrowthKernelPort[KernelInput, NoTradeDecision]"\n',
        "getattr_case.py": "value = getattr(contracts, 'GrowthKernelPort')\n",
        "constructor.py": "value = globals()['GrowthKernelPort']\n",
        "typevar_case.py": (
            "KernelT = TypeVar('KernelT', bound=GrowthKernelPort[KernelInput, NoTradeDecision])\n"
        ),
        "pep613.py": ("Bad: TypeAlias = 'GrowthKernelPort[Any, NoTradeDecision]'\n"),
        "contract.pyi": "def consume(value: GrowthKernelPort) -> None: ...\n",
    }
    if hasattr(ast, "TypeAlias"):
        cases["pep695.py"] = "type Generic[T, U] = GrowthKernelPort[T, U]\n"
    for filename, source in cases.items():
        (tmp_path / filename).write_text(source, encoding="utf-8")

    rendered = "\n".join(_scan_growth_kernel_port_references(tmp_path))

    for filename in cases:
        assert f"{filename}:1:" in rendered


def test_growth_kernel_port_guard_rejects_contract_star_imports(
    tmp_path: Path,
) -> None:
    (tmp_path / "contracts_star.py").write_text(
        "from src.screening.offensive.v3.contracts import *\n",
        encoding="utf-8",
    )
    (tmp_path / "ports_star.pyi").write_text(
        "from src.screening.offensive.v3.contracts.ports import *\n",
        encoding="utf-8",
    )
    contracts_subpackage = tmp_path / "screening/offensive/v3/contracts/subpackage"
    contracts_subpackage.mkdir(parents=True)
    (contracts_subpackage / "leak.py").write_text(
        "from .. import *\nfrom ..ports import *\n",
        encoding="utf-8",
    )
    v3_package = tmp_path / "screening/offensive/v3"
    (v3_package / "relative_stars.py").write_text(
        "from .contracts import *\nfrom .contracts.ports import *\n",
        encoding="utf-8",
    )
    (v3_package / "init_stars.py").write_text(
        "from .contracts.__init__ import *\n"
        "from src.screening.offensive.v3.contracts.__init__ import *\n",
        encoding="utf-8",
    )

    rendered = "\n".join(_scan_growth_kernel_port_references(tmp_path))

    assert "contracts_star.py:1:" in rendered
    assert "ports_star.pyi:1:" in rendered
    assert "v3/relative_stars.py:1:" in rendered
    assert "v3/relative_stars.py:2:" in rendered
    assert "contracts/subpackage/leak.py:1:" in rendered
    assert "contracts/subpackage/leak.py:2:" in rendered
    assert "v3/init_stars.py:1:" in rendered
    assert "v3/init_stars.py:2:" in rendered


def test_control_documents_publish_the_completed_final_port_boundary() -> None:
    roadmap = (
        ROOT / "docs/superpowers/plans/2026-07-19-growth-kernel-roadmap.md"
    ).read_text(encoding="utf-8")
    plan01 = (
        ROOT
        / "docs/superpowers/plans/2026-07-19-growth-kernel-01-contracts-policy-trust.md"
    ).read_text(encoding="utf-8")
    plan03 = (
        ROOT
        / "docs/superpowers/plans/2026-07-19-growth-kernel-03-evidence-stat-governance.md"
    ).read_text(encoding="utf-8")
    design = (
        ROOT
        / "docs/superpowers/specs/2026-07-19-evidence-gated-growth-kernel-design.md"
    ).read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert (
        "def outcome(self, outcome_id: str, revision: int) "
        "-> EvidenceRecord[OutcomeEvidence]: ..."
    ) in roadmap
    assert "ActiveEvidenceRecord = (" in roadmap
    for payload in (
        "SnapshotEvidence",
        "SignalEvidence",
        "OutcomeEvidence",
        "PlanEvidence",
    ):
        assert f"EvidenceRecord[{payload}]" in roadmap
    assert "current_head: CurrentTrustHeadWitness" in roadmap
    assert "trusted_at: datetime" in roadmap
    assert "GrowthKernelPort[KernelInput, NoTradeDecision]" in roadmap
    assert "current_head=" in plan03
    assert "trusted_at=" in plan03
    assert "required_capability(signed.artifact)" in plan03
    assert "required_capability(signed.kind)" not in plan03
    assert "EvidenceQueryPort.active_revision()/outcome()" in plan03
    assert "-> ActiveEvidenceRecord:" in plan03
    assert "-> EvidenceRecord:" not in plan03
    assert "TypeAdapter(ActiveEvidenceRecord)" in plan03
    assert "strict=True" in plan03
    assert "concrete type" in plan03
    assert "full value" in plan03
    assert "artifact_hash" in plan03
    for forbidden_escape in ("cast(", "model_construct("):
        assert forbidden_escape not in plan03

    task5 = plan01.split("### Task 5:", 1)[1].split("## Completion Gate", 1)[0]
    completion_gate = plan01.split("## Completion Gate", 1)[1]
    assert "**Implemented boundary (2026-08-01):**" in task5
    assert "- [ ]" not in task5
    assert task5.count("- [x]") == 5
    assert completion_gate.count("- [ ]") == 0
    assert completion_gate.count("- [x]") == 6
    assert (
        "- [x] Every Revision 2 schema has strict validation, canonical "
        "serialization, hash, and snapshot tests."
    ) in completion_gate
    assert "checked-in snapshot matrix" in completion_gate
    assert "decision/capital/execution/evidence/trust/policy" in completion_gate
    assert "- [ ] Plan 01 Revision 2 schema/ports implementation" in roadmap
    assert "completion gate 已完成" in roadmap
    assert "独立审阅通过并合并后更新" in roadmap
    assert "Tasks 1–5" in agents
    assert "Task 5 final ports 也尚未实现" not in agents
    assert "Tasks 1–4 candidate contracts/pure verification" not in design
    assert "Plan 01 Revision 2 Tasks 1–4" not in design
    assert "当前实现事实：Revision 1 contracts/policy/trust/ports 已合并" not in plan01
    assert "Plan 01 Task 5" in design
    for document in (design, agents):
        assert "Tasks 1–5 implementation is present" in document
        assert "Plan 01 completion gate is closed" in document
        assert "snapshot matrix" in document
    for document in (plan01, roadmap, design, agents):
        assert "zero static `GrowthKernelPort` references" in document
        assert "no downstream typing or runtime exception" in document
        assert (
            "dynamic or fragmented string construction is outside this static proof"
            in document.lower()
        )
        assert "new RED-to-GREEN TDD" in document
        assert "exact consumer module" in document
        assert (
            "exact `GrowthKernelPort[KernelInput, NoTradeDecision]` signature"
            in document
        )
        assert (
            "alias, runtime-check, and star-import exceptions remain forbidden"
            in document
        )
    assert "screening/offensive/v3/contracts/ports.py" in plan01
    assert "screening/offensive/v3/contracts/__init__.py" in plan01
    assert "`*.py` and `*.pyi`" in plan01
    for document in (plan01, design, agents):
        assert "no capital authority" in document.lower() or "没有资本授权" in document
