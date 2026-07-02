"""Regression guard: scan source files for hardcoded secrets.

Context (c272): `scripts/btst_factor_ic_analysis.py:41` had a hardcoded
TUSHARE_TOKEN fallback default (`os.getenv("TUSHARE_TOKEN", "ab9ec948...")`).
The token was committed to git history (since 613caa5e), making it a real
secret leak. This test prevents re-introduction by scanning for the leaked
token pattern and similar hardcoded credential fallbacks.

Note: full remediation requires owner to rotate the token at tushare.pro and
optionally scrub git history (destructive, owner-only). This test only guards
against re-introduction in current source.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

# The leaked token from scripts/btst_factor_ic_analysis.py (commit 613caa5e).
# Even after rotation, scanning for this exact string prevents re-introduction
# of the same compromised credential.
_LEAKED_TUSHARE_TOKEN = "ab9ec94882de89ccf50a06744281e9f6bdeef378b509b30f8eaef7aa"

# Pattern: getenv("ENV_VAR", "<long hex string>") — hardcoded credential fallback
_HARDCODED_TOKEN_FALLBACK_PATTERN = re.compile(
    r'getenv\s*\(\s*["\'](?:TUSHARE_TOKEN|API_KEY|SECRET|TOKEN|PASSWORD)["\']\s*,\s*["\']([a-f0-9]{20,})["\']',
    re.IGNORECASE,
)

# Directories to scan (skip .venv, .git, node_modules, __pycache__, data caches)
_SCAN_ROOTS = ["src", "scripts", "app"]
_SKIP_DIR_PARTS = {".venv", ".git", "node_modules", "__pycache__", ".pytest_cache", "data"}


def _iter_source_files() -> list[Path]:
    """Yield .py files in scan roots, skipping venv/cache/data dirs."""
    repo_root = Path(__file__).resolve().parent.parent
    files: list[Path] = []
    for root in _SCAN_ROOTS:
        root_path = repo_root / root
        if not root_path.exists():
            continue
        for path in root_path.rglob("*.py"):
            if any(part in _SKIP_DIR_PARTS for part in path.parts):
                continue
            files.append(path)
    return files


def test_no_leaked_tushare_token_in_source() -> None:
    """确认泄露的 TUSHARE_TOKEN 不再出现在任何源文件中 (c272)."""
    offenders: list[str] = []
    for path in _iter_source_files():
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _LEAKED_TUSHARE_TOKEN in content:
            offenders.append(str(path))
    assert not offenders, (
        f"泄露的 TUSHARE_TOKEN 仍出现在源文件中 (c272 回归): {offenders}. "
        f"请用 os.getenv('TUSHARE_TOKEN', '') + 缺失时 raise 替代硬编码 fallback."
    )


def test_no_hardcoded_credential_fallback_in_source() -> None:
    """扫描 getenv('SECRET_ENV', '<long hex>') 硬编码 fallback 模式 (c272).

    防止未来引入新的硬编码凭证 fallback。匹配 20+ 字符的 hex string 作为
    credential heuristic (避开短 default value 如 '' 或 'unknown')。
    """
    offenders: list[str] = []
    for path in _iter_source_files():
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in _HARDCODED_TOKEN_FALLBACK_PATTERN.finditer(content):
            offenders.append(f"{path}: hardcoded credential fallback -> {match.group(0)[:80]}...")
    assert not offenders, (
        f"检测到硬编码凭证 fallback 模式 (c272 防扩散): {offenders}. "
        f"凭证必须通过环境变量管理, 禁止硬编码 fallback default."
    )


def test_tushare_token_documented_in_env_example() -> None:
    """确认 TUSHARE_TOKEN 已在 .env.example 文档化 (c272)."""
    repo_root = Path(__file__).resolve().parent.parent
    env_example = repo_root / ".env.example"
    assert env_example.exists(), ".env.example should exist"
    content = env_example.read_text(encoding="utf-8")
    assert "TUSHARE_TOKEN" in content, (
        "TUSHARE_TOKEN 必须在 .env.example 文档化, 让 operators 知道如何配置"
    )


def test_btst_factor_ic_analysis_raises_without_token(monkeypatch, tmp_path) -> None:
    """btst_factor_ic_analysis 必须在 TUSHARE_TOKEN 缺失时 raise clear error (c272).

    之前用硬编码 token 作为 fallback default — 现在 fallback 是空字符串,
    缺失 env var 时必须 raise 而不是静默用空 token 调用 tushare API。
    """
    import importlib.util
    import sys

    # 移除已加载的模块 (如果之前被 import 过)
    for mod_name in list(sys.modules.keys()):
        if "btst_factor_ic_analysis" in mod_name:
            del sys.modules[mod_name]

    # 确保 TUSHARE_TOKEN 未设置
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)

    script_path = Path(__file__).resolve().parent.parent / "scripts" / "btst_factor_ic_analysis.py"
    assert script_path.exists(), f"script not found: {script_path}"

    spec = importlib.util.spec_from_file_location("_test_btst_ic_analysis", script_path)
    assert spec is not None and spec.loader is not None

    with pytest.raises(RuntimeError, match="TUSHARE_TOKEN"):
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
