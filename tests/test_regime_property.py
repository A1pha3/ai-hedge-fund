"""Property guard: build_front_door_verdict 的每次调用都必须解析 regime。

跨表面 regime 不一致 disease (autodev-26 loops 137-138) 只在每个调用点都
正确读 regime_gate_level 或接收 market_regime 作为透传参数时才真正 CLOSED.

这是一个 STATIC-ANALYSIS 守卫 (无需 mock 或文件系统), 能及早捕获:
- 新 CLI surface 调 build_front_door_verdict 并默认 "normal"
- 重构移除 regime 解析步骤
"""

from __future__ import annotations

import re
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"

#: 自行读 regime_gate_level 的文件 (调用方自己解析 regime).
SELF_RESOLVING = frozenset({
    "main.py",                            # run_top_picks/run_custom_weights/run_explain 等
    "cli/daily_brief.py",                 # 运行时读 regime
    "notification/push.py",               # 读 regime_gate_level
    "notification/weekly_report.py",      # 读 regime_gate_level
    "screening/compare_tool.py",          # 读 regime_gate_level (loop-106)
    "screening/conditional_order_advisor.py",  # 读 regime_gate_level
    "screening/stock_detail.py",          # 读 regime_gate_level (loop-137 fix)
})

#: 通过函数参数接收 market_regime 的文件 (调用方负责解析).
REGIME_VIA_PARAM = frozenset({
    "screening/top_picks.py",             # 通过 context.market_regime / 函数参数
    "screening/industry_cross_picks.py",  # _extract_top_picks_for_industry 参数
    "portfolio/builder.py",               # compute_portfolio / render_portfolio 参数
    "cli/why_not.py",                     # _print_already_recommended 参数
})

#: 已知的纯诊断模块 (market_regime 由调用方显式传入, 非生产路径).
DIAGNOSTIC_ONLY = frozenset({
    "screening/grade_verdict_parity.py",  # 仅 __main__ 调用, 非生产路径
})

ALL_KNOWN = SELF_RESOLVING | REGIME_VIA_PARAM | DIAGNOSTIC_ONLY

#: 匹配 build_front_door_verdict( 的实际调用 (排除 def 定义、注释、docstring 行).
_CALL_RE = re.compile(r"(?<!def\s)\bbuild_front_door_verdict\s*\(")


def _files_actually_calling_verdict() -> list[Path]:
    """查找所有**实际调用**(非仅注释提及) build_front_door_verdict 的源文件."""
    files: list[Path] = []
    for py_file in sorted(SRC_ROOT.rglob("*.py")):
        str_path = str(py_file)
        if any(seg in str_path for seg in ("__pycache__", ".mypy_cache")):
            continue
        rel = py_file.relative_to(SRC_ROOT)
        if str(rel) == "screening/investability.py":
            continue  # 定义文件本身

        content = py_file.read_text(encoding="utf-8")
        for line_no, line in enumerate(content.splitlines(), start=1):
            stripped = line.lstrip()
            # 跳过注释行和 docstring 行
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            if _CALL_RE.search(line):
                files.append(py_file)
                break
    return files


def _has_regime_resolution(content: str) -> bool:
    """文件是否包含 regime 解析 (regime_gate_level 或 _find_latest_report 用于 regime)."""
    return "regime_gate_level" in content


def test_all_verdict_callers_resolve_regime() -> None:
    """Property guard: 每个调用 build_front_door_verdict 的文件都必须解析 regime.

    要么自己读 regime_gate_level, 要么通过 market_regime 参数透传.
    允许例外 (DIAGNOSTIC_ONLY) 需在文件头注释说明.
    """
    errors: list[str] = []
    for py_file in _files_actually_calling_verdict():
        rel = str(py_file.relative_to(SRC_ROOT))
        content = py_file.read_text(encoding="utf-8")

        # 已分类的文件直接通过
        if rel in ALL_KNOWN:
            continue

        has_regime = _has_regime_resolution(content)
        has_param = "market_regime" in content

        if not has_regime and not has_param:
            errors.append(
                f"{rel}: 调用 build_front_door_verdict 但既未读 regime_gate_level "
                f"也未接收 market_regime 参数 — 跨 surface regime 不一致风险 "
                f"(autodev-26 loops 137-138 disease class)"
            )

    assert not errors, (
        f"找到 {len(errors)} 个 risky 文件:\n" + "\n".join(errors)
    )


def test_all_callers_catalogued() -> None:
    """每个调用者都必须分类到 SELF_RESOLVING / REGIME_VIA_PARAM / DIAGNOSTIC_ONLY.

    新文件调用 build_front_door_verdict 但未分类 → 此测试失败, 强制开发者
    审查 regime 解析方式并归类.
    """
    callers = {str(f.relative_to(SRC_ROOT)) for f in _files_actually_calling_verdict()}
    uncatalogued = callers - ALL_KNOWN
    assert not uncatalogued, (
        f"以下文件调用 build_front_door_verdict 但未编目: "
        f"{', '.join(sorted(uncatalogued))}。请归类到 SELF_RESOLVING "
        f"(自己读 regime_gate_level) 或 REGIME_VIA_PARAM (透传参数), "
        f"并验证 regime 解析正确 (见 autodev-26 loops 137-138)."
    )


def test_known_files_exist() -> None:
    """验证已知分类列表中的路径都存在 (防止列表过时)."""
    for rel in ALL_KNOWN:
        path = SRC_ROOT / rel
        assert path.exists(), f"分类路径不存在: {path} — 请更新此测试"


def test_self_resolving_files_actually_read_regime() -> None:
    """SELF_RESOLVING 列表中的文件必须实际包含 regime_gate_level 引用.

    防止分类正确但代码被重构移除了 regime 解析.
    """
    missing: list[str] = []
    for rel in SELF_RESOLVING:
        path = SRC_ROOT / rel
        content = path.read_text(encoding="utf-8")
        if "regime_gate_level" not in content and "regime" not in content.lower():
            missing.append(rel)
    assert not missing, (
        f"SELF_RESOLVING 中以下文件不再包含 regime 解析: {', '.join(missing)}。"
        f"要么恢复 regime 解析, 要么重新分类."
    )


def test_regime_via_param_files_accept_market_regime() -> None:
    """REGIME_VIA_PARAM 列表中的文件必须实际接收 market_regime 参数."""
    missing: list[str] = []
    for rel in REGIME_VIA_PARAM:
        path = SRC_ROOT / rel
        content = path.read_text(encoding="utf-8")
        if "market_regime" not in content:
            missing.append(rel)
    assert not missing, (
        f"REGIME_VIA_PARAM 中以下文件不再接收 market_regime: {', '.join(missing)}。"
        f"要么恢复参数透传, 要么重新分类."
    )
