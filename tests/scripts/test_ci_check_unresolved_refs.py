"""Tests for CI check_unresolved_refs script."""
import sys
from pathlib import Path

# Ensure scripts/ci_check_unresolved_refs is importable as a module
SCRIPTS_FILE = Path(__file__).parent.parent.parent / "scripts" / "ci_check_unresolved_refs.py"
import importlib.util

_spec = importlib.util.spec_from_file_location("ci_check_unresolved_refs", SCRIPTS_FILE)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

_collect_imports = _module._collect_imports
_collect_top_level_defs = _module._collect_top_level_defs
_collect_top_level_name_loads = _module._collect_top_level_name_loads
_find_unresolved_refs = _module._find_unresolved_refs
_is_main_check = _module._is_main_check
_is_type_checking_guard = _module._is_type_checking_guard
main = _module.main


def test_detects_top_level_n_undefined(tmp_path: Path):
    """The R20.2 bug pattern: top-level use of undefined name."""
    f = tmp_path / "buggy.py"
    f.write_text("X = np.isfinite(0.5)\n")  # np not imported
    issues = _find_unresolved_refs(f)
    assert ("np" in [n for _, n in issues]) or any("np" in str(i) for i in issues)


def test_no_issues_with_correct_imports(tmp_path: Path):
    f = tmp_path / "good.py"
    f.write_text("import numpy as np\nX = np.isfinite(0.5)\n")
    issues = _find_unresolved_refs(f)
    assert issues == []


def test_no_issues_with_for_loop_vars(tmp_path: Path):
    f = tmp_path / "for_loop.py"
    f.write_text("""
for i in range(10):
    X = i * 2

for _name, _val in [("a", 1)]:
    Y = _val
""")
    issues = _find_unresolved_refs(f)
    assert issues == []


def test_no_issues_with_comprehension_vars(tmp_path: Path):
    f = tmp_path / "comp.py"
    f.write_text("""
X = [x * 2 for x in range(10)]
Y = {k: v for k, v in [("a", 1)]}
""")
    issues = _find_unresolved_refs(f)
    assert issues == []


def test_no_issues_with_main_block(tmp_path: Path):
    f = tmp_path / "script.py"
    f.write_text("""
def helper():
    return 42

if __name__ == "__main__":
    # These are legitimate script entry points
    import sys
    sys.exit(helper())
""")
    issues = _find_unresolved_refs(f)
    # sys not imported at top — but the if __name__ block is skipped
    assert issues == []


def test_detects_decorator_undefined(tmp_path: Path):
    f = tmp_path / "decorated.py"
    f.write_text("""
@my_decorator  # my_decorator not imported!
def foo():
    pass
""")
    issues = _find_unresolved_refs(f)
    assert any("my_decorator" in str(i) for i in issues)


def test_detects_default_arg_undefined(tmp_path: Path):
    f = tmp_path / "defarg.py"
    f.write_text("""
def foo(x=UNDEFINED_CONST):
    pass
""")
    issues = _find_unresolved_refs(f)
    assert any("UNDEFINED_CONST" in str(i) for i in issues)


def test_detects_type_checking_guard_undefined(tmp_path: Path):
    """Even with TYPE_CHECKING guard, names referenced in the guard
    should be importable (the guard imports them)."""
    f = tmp_path / "tc.py"
    f.write_text("""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from foo import Bar  # Bar is in scope

X = Bar  # OK, Bar is imported via TYPE_CHECKING
""")
    issues = _find_unresolved_refs(f)
    assert issues == []


def test_is_main_check():
    import ast
    tree = ast.parse("if __name__ == '__main__':\n    pass\n")
    if_node = tree.body[0]
    assert _is_main_check(if_node) is True


def test_is_type_checking_guard():
    import ast
    tree = ast.parse("if TYPE_CHECKING:\n    pass\n")
    if_node = tree.body[0]
    assert _is_type_checking_guard(if_node) is True


def test_main_runs_without_error():
    """End-to-end: run main() on src/ and ensure it doesn't crash."""
    from pathlib import Path
    src = Path("src")
    if not src.exists():
        return  # Skip if src not found
    # We just want to ensure no exception, exit code may be 0 or 1
    result = main() if False else None
    # Manually invoke with mocked argv
    import sys
    old_argv = sys.argv
    try:
        sys.argv = ["ci_check_unresolved_refs.py", "src"]
        try:
            main()
        except SystemExit:
            pass  # Expected exit
    finally:
        sys.argv = old_argv
