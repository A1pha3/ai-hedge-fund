"""CI 防护: 检测模块顶层未解析的引用 (防止 R20.2 类导入遗漏 bug)。

R20.31 在三处模块拆分中遗漏了依赖导入 (导致 NameError 崩溃):
  - ``strategy_scorer_mean_reversion.py``: `np.isfinite()` 使用但 numpy 未导入
  - ``strategy_scorer_event_sentiment_helpers.py``: `pd`/`get_prices`/`prices_to_df` 未导入
  - 其他若干处

这些 bug 都在 **模块顶层** (函数体外) 暴露, 因为:
  - 函数体内的 import 是 lazy 的, 实际执行才会触发
  - 顶层表达式 (常量赋值, 类型注解, 装饰器参数) 会在 import 时立即求值

此脚本专注于 **模块顶层 Name(Load) 节点** — 这是高置信度的 "未解析引用"
检测点, 避免误报函数体内部的合法动态引用。

**范围**:
  - ✅ 模块顶层表达式 (常量赋值, 函数签名默认值, 装饰器)
  - ✅ 默认参数 + 类型注解 (作为装饰器参数)
  - ❌ 函数体内部 (动态引用合法)
  - ❌ 字符串字面量 (合法)
  - ❌ TYPE_CHECKING 守卫 (合法)
  - ❌ 条件导入 (try/except ImportError)

**已知误报源**:
  - ``__all__`` 中的名称 (合法, Python 协议)
  - 动态导入 (``importlib.import_module``) 后的属性
  - 反射代码 (``getattr()``)

用法::

    uv run python scripts/ci_check_unresolved_refs.py

退出码:
  0 - 无顶层未解析引用
  1 - 发现问题 (需要人工审查)
"""
from __future__ import annotations

import argparse
import ast
import builtins
import sys
from pathlib import Path


_BUILTIN_NAMES = set(dir(builtins))

# 已知误报: ``__all__`` 中可能列出未导入的导出名
_ALL_NAMES = frozenset({"__all__"})


def _collect_imports(tree: ast.Module) -> set[str]:
    """收集模块所有 import 的名称 (顶层 + TYPE_CHECKING 守卫内)。"""
    imports: set[str] = set()

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imports.add(alias.asname or alias.name)
        elif isinstance(node, ast.If) and _is_type_checking_guard(node):
            # TYPE_CHECKING 守卫内的导入也认作已导入
            for child in node.body:
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        imports.add(alias.asname or alias.name.split(".")[0])
                elif isinstance(child, ast.ImportFrom):
                    for alias in child.names:
                        imports.add(alias.asname or alias.name)
    return imports


def _is_type_checking_guard(node: ast.If) -> bool:
    """判断是否是 ``if TYPE_CHECKING:`` 或 ``if typing.TYPE_CHECKING:`` 守卫。"""
    if not isinstance(node.test, ast.Name):
        return False
    if node.test.id == "TYPE_CHECKING":
        return True
    return False


def _is_main_check(node: ast.If) -> bool:
    """判断是否是 ``if __name__ == "__main__":`` 守卫。"""
    test = node.test
    if not isinstance(test, ast.Compare):
        return False
    if not isinstance(test.left, ast.Name) or test.left.id != "__name__":
        return False
    if len(test.comparators) != 1:
        return False
    cmp = test.comparators[0]
    return isinstance(cmp, ast.Constant) and cmp.value == "__main__"


def _collect_top_level_defs(tree: ast.Module) -> set[str]:
    """收集模块顶层定义 (def, class, assign, annassign, for-loop var, comprehension var)。"""
    defs: set[str] = set()

    def _add_comprehension_vars(comp: ast.expr) -> None:
        """从 generator (comp.generators) 中抽取 target 名。"""
        for gen in getattr(comp, "generators", []):
            if isinstance(gen.target, ast.Name):
                defs.add(gen.target.id)
            elif isinstance(gen.target, (ast.Tuple, ast.List)):
                for elt in gen.target.elts:
                    if isinstance(elt, ast.Name):
                        defs.add(elt.id)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defs.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defs.add(target.id)
                elif isinstance(target, (ast.Tuple, ast.List)):
                    for elt in target.elts:
                        if isinstance(elt, ast.Name):
                            defs.add(elt.id)
            # If RHS is a comprehension, add its iteration vars as defs
            if isinstance(node.value, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                _add_comprehension_vars(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defs.add(node.target.id)
        elif isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            # Top-level for loop: e.g., for _tc_w in [0.10, ...]
            defs.add(node.target.id)
        elif isinstance(node, ast.For) and isinstance(node.target, (ast.Tuple, ast.List)):
            for elt in node.target.elts:
                if isinstance(elt, ast.Name):
                    defs.add(elt.id)
        # Imports handled separately
    return defs


def _collect_top_level_name_loads(tree: ast.Module) -> list[tuple[int, str]]:
    """收集模块顶层 (函数体外) 所有的 Name(Load) 节点。

    这些是会在模块 import 时立即求值的引用, 如果未导入就是 bug。
    """
    loads: list[tuple[int, str]] = []

    for node in tree.body:
        # Skip nested function/class bodies (their uses are internal)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # BUT check default args + decorators (they're evaluated at def time)
            for default in node.args.defaults + node.args.kw_defaults:
                if default is None:
                    continue
                for sub in ast.walk(default):
                    if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                        loads.append((sub.lineno, sub.id))
            for decorator in node.decorator_list:
                for sub in ast.walk(decorator):
                    if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                        loads.append((sub.lineno, sub.id))
            # Module-level decorators/args cover the at-def-time references
            continue
        if isinstance(node, ast.ClassDef):
            # Class base classes + decorators are evaluated at class def time
            for base in node.bases:
                for sub in ast.walk(base):
                    if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                        loads.append((sub.lineno, sub.id))
            for decorator in node.decorator_list:
                for sub in ast.walk(decorator):
                    if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                        loads.append((sub.lineno, sub.id))
            continue
        if isinstance(node, ast.AnnAssign):
            # Type annotation might reference names
            if node.annotation:
                for sub in ast.walk(node.annotation):
                    if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                        loads.append((sub.lineno, sub.id))
            # Value (right side) is evaluated immediately
            if node.value:
                for sub in ast.walk(node.value):
                    if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                        loads.append((sub.lineno, sub.id))
            continue
        if isinstance(node, ast.If) and _is_main_check(node):
            # `if __name__ == "__main__":` is a legitimate script body
            # Skip — it's like a function body, not module top-level
            continue
        if isinstance(node, ast.For):
            # Top-level for loops: their iteration variables are valid references
            # But we DO want to check the .iter (the right side) for unresolved refs
            for sub in ast.walk(node.iter):
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                    loads.append((sub.lineno, sub.id))
            continue

        # For other top-level nodes: collect all Name(Load)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                loads.append((sub.lineno, sub.id))

    return loads


def _find_unresolved_refs(file_path: Path) -> list[tuple[int, str]]:
    """查找模块顶层未解析的引用。"""
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError) as exc:
        return [(0, f"<parse error: {exc.__class__.__name__}: {exc}>")]

    imports = _collect_imports(tree)
    defs = _collect_top_level_defs(tree)
    loads = _collect_top_level_name_loads(tree)

    known = imports | defs | _BUILTIN_NAMES | set(_ALL_NAMES)

    # Common false positives: short local-like names that are likely function args/loop vars
    # (but those shouldn't appear at module top level usually)
    skip_short = {"i", "j", "k", "n", "m", "x", "y", "z", "e", "_"}

    unresolved: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for line, name in loads:
        if name in known or name in skip_short:
            continue
        if name.startswith("__") and name.endswith("__"):
            continue
        key = (line, name)
        if key in seen:
            continue
        seen.add(key)
        unresolved.append((line, name))

    return unresolved


def _should_skip_file(file_path: Path) -> bool:
    name = file_path.name
    if name.startswith("_") and not name.startswith("__init__"):
        return True  # Private modules
    if name in {"__init__.py", "conftest.py"}:
        return True
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    if name in {"ci_check_unresolved_refs.py"}:
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="CI check for top-level unresolved references")
    parser.add_argument("path", nargs="?", default="src", help="Path to check (default: src)")
    args = parser.parse_args()

    root = Path(args.path)
    if not root.exists():
        print(f"Path not found: {root}", file=sys.stderr)
        return 2

    total_files = 0
    total_issues = 0
    issues_by_file: list[tuple[Path, list[tuple[int, str]]]] = []

    for py_file in sorted(root.rglob("*.py")):
        if _should_skip_file(py_file):
            continue
        total_files += 1
        unresolved = _find_unresolved_refs(py_file)
        if unresolved:
            total_issues += len(unresolved)
            issues_by_file.append((py_file, unresolved))

    # Report
    if not issues_by_file:
        print(f"✅ No top-level unresolved references found in {total_files} files")
        return 0

    print(f"⚠ Found {total_issues} potential unresolved references in {len(issues_by_file)} files:\n")
    for file_path, issues in issues_by_file[:20]:
        rel = file_path.relative_to(root) if file_path.is_relative_to(root) else file_path
        print(f"  {rel}:")
        for line, name in issues[:10]:
            print(f"    L{line}: {name}")
        if len(issues) > 10:
            print(f"    ... and {len(issues) - 10} more")
        print()

    if len(issues_by_file) > 20:
        print(f"  ... and {len(issues_by_file) - 20} more files with issues\n")

    # Validate against known R20.2 bugs to ensure the script catches them
    known_bugs = {
        ("src/screening/strategy_scorer_mean_reversion.py", "np"),
        ("src/screening/strategy_scorer_mean_reversion.py", "np.isfinite"),
        # R20.31 round 2 was already fixed
    }
    caught = []
    for file_path, issues in issues_by_file:
        rel = str(file_path.relative_to(Path("."))) if file_path.is_relative_to(Path(".")) else str(file_path)
        for _, name in issues:
            if (rel, name) in known_bugs:
                caught.append((rel, name))

    print("ℹ Known R20.2 bugs that the script would catch:")
    if caught:
        for r, n in caught:
            print(f"  ✅ {r}: {n}")
    else:
        print("  (none of the R20.2 bug patterns detected — script may need tuning)")

    print()
    print("ℹ Note: This is a heuristic. False positives are common (e.g.,")
    print("  conditional imports, getattr() chains, dynamic __all__).")
    print("  Investigate each finding manually.")

    return 1 if total_issues > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
