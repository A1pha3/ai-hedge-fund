"""Kernel purity boundary guard (Plan 04 Task 9).

The kernel package (admission / risk / sizing / decide / models) is the pure,
deterministic, replayable scoring layer. It must NOT import storage
(SQLAlchemy / sqlite drivers), network clients (HTTP / broker / data
adapters), or the legacy v2 screening layer: those concerns belong to the
capital / gateway / execution adapter layers. Keeping the kernel storage- and
network-free is what makes kernel replay byte-for-byte deterministic and lets
it run with the runtime off.

This guard scans every kernel module's source AST - not a subprocess import -
so it catches a forbidden import the moment it is written, regardless of
whether that code path executes. A failure here means a future edit dragged
storage or network into the pure kernel and the green suite must catch it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


# Located from this test file so the guard does not depend on pytest's cwd.
# Walk up from this file until the kernel package directory is found, so the
# guard survives test-file relocation.
def _find_kernel_dir() -> Path:
    here = Path(__file__).resolve().parent
    for candidate in (here, *here.parents):
        kernel = candidate / "src" / "screening" / "offensive" / "v3" / "kernel"
        if kernel.is_dir():
            return kernel
    raise AssertionError("could not locate src/screening/offensive/v3/kernel")


_KERNEL_DIR = _find_kernel_dir()
# kernel = <repo>/src/screening/offensive/v3/kernel; four parents up is src/,
# used only so violation messages read as repo-relative paths. This is the src
# root, not the repo root - do not treat it as a base for non-src paths.
_SRC_ROOT = _KERNEL_DIR.parent.parent.parent.parent  # .../src

# Module roots the pure kernel must never import directly. Storage and network
# live in the adapter layers; akshare/tushare are the data network adapters.
_FORBIDDEN_ROOTS = frozenset(
    {
        # storage
        "sqlalchemy",
        "sqlite3",
        "aiosqlite",
        "psycopg2",
        "pymysql",
        # network / broker / data adapters
        "requests",
        "httpx",
        "aiohttp",
        "urllib3",
        "httpcore",
        "websockets",
        "akshare",
        "tushare",
    }
)

# Absolute module paths the kernel must never reach into. v2 is the superseded
# screening package; a kernel dependency on it would couple the pure layer to
# the legacy implementation.
_FORBIDDEN_PREFIXES = ("src.screening.offensive.v2",)

_KERNEL_FILES = tuple(sorted(_KERNEL_DIR.glob("*.py")))


def _absolute_imports(tree: ast.Module) -> list[str]:
    """Every absolute (non-relative) module referenced by an import statement."""

    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # Relative imports (level > 0) stay inside the kernel package and
            # are always allowed; only absolute imports can cross the boundary.
            if node.level == 0 and node.module:
                modules.append(node.module)
    return modules


def _forbidden_violation(module_name: str) -> str | None:
    root = module_name.split(".")[0]
    if root in _FORBIDDEN_ROOTS:
        return f"{module_name!r} (forbidden storage/network root {root!r})"
    for prefix in _FORBIDDEN_PREFIXES:
        if module_name == prefix or module_name.startswith(prefix + "."):
            return f"{module_name!r} (forbidden v2 reach-through {prefix!r})"
    return None


@pytest.mark.parametrize("path", _KERNEL_FILES, ids=lambda p: p.name)
def test_kernel_module_imports_no_storage_network_or_v2(path: Path) -> None:
    """Each kernel module's source must be free of storage/network/v2 imports."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations = [
        detail
        for module in _absolute_imports(tree)
        if (detail := _forbidden_violation(module)) is not None
    ]
    assert not violations, (
        f"{path.relative_to(_SRC_ROOT)} imports"
        f" forbidden modules:\n  - " + "\n  - ".join(violations)
    )


def test_kernel_package_is_scanned() -> None:
    """Guard against the parameter list silently going empty (e.g. a path move)."""

    assert _KERNEL_FILES, f"no kernel modules found under {_KERNEL_DIR}"
    assert any(p.name == "__init__.py" for p in _KERNEL_FILES)
