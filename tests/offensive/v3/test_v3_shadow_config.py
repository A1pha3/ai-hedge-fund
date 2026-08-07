"""Plan 05 Task 9 S3 (RED): V3 shadow CLI 配置加载器测试。

被测对象 ``src/cli/v3_shadow.py`` (函数 ``load_v3_shadow_config`` 与
dataclass ``V3ShadowConfig``) 尚未实现; 本文件应整体 RED, 预期::

    ModuleNotFoundError: No module named 'src.cli.v3_shadow'

由主代理在 S4 实现 GREEN。

语义契约 (供主代理对齐; 详见 task 描述):
- 用 ``tomllib`` parse toml。
- 相对路径相对【repo root】解析 (由 ``Path(__file__)`` 推导, 不依赖 cwd);
  绝对路径原样保留。所有 Path 字段返回时已是绝对路径。
- 缺任一必填字段 / 缺 [policy] 或 [sizing] 段 / 文件不存在 / toml 语法错误
  一律 fail-closed 抛异常。
- sizing 段 5 个 int 字段必填, 构造 ``SizingConfig(...)``;
  ``min_lot_units`` 有默认值, 不在 toml 内。
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.cli.v3_shadow import load_v3_shadow_config, V3ShadowConfig
from src.screening.offensive.v3.kernel.sizing import SizingConfig


def _repo_root() -> Path:
    """从本测试文件向上 walk 找 pyproject.toml 所在 repo root。

    比 ``parents[N]`` 更稳健: 不依赖测试文件具体层级 (本文件在
    ``<repo>/tests/offensive/v3/`` 下, parents[3] 即 repo root, 但 walk-up
    在层级调整时无需改 N)。
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise RuntimeError("无法定位 repo root (pyproject.toml 未找到)")


REPO_ROOT: Path = _repo_root()
EXAMPLE_TOML: Path = REPO_ROOT / "config" / "services" / "v3" / "services.example.toml"

# 相对 toml 解析后期望的 evidence_database 绝对路径 (repo root 锚定)。
EXPECTED_EVIDENCE_DB: Path = REPO_ROOT / "data" / "v3_shadow" / "evidence.sqlite3"


def _write_toml(tmp_path: Path, name: str, content: str) -> Path:
    """在 tmp_path 写一个 toml 文件并返回其路径; content 经 textwrap.dedent。"""
    path = tmp_path / name
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


# 一份字段齐全的 toml 模板, 便于 fail-closed 用例只删一行。
_FULL_TOML_TEMPLATE: str = """
    [paths]
    portfolio_id = "paper-v3"
    evidence_database = "data/v3_shadow/evidence.sqlite3"
    blob_root = "data/v3_shadow/blobs"
    capital_ledger = "data/v3_shadow/capital.sqlite3"
    gateway_database = "data/v3_shadow/gateway.sqlite3"
    shadow_artifacts_dir = "data/v3_shadow/artifacts"

    [policy]
    path = "config/policies/v3/policy-v1.json"

    [sizing]
    per_ticker_gross_cap_cents = 500000
    per_industry_gross_cap_cents = 1500000
    per_day_gross_cap_cents = 3000000
    portfolio_gross_cap_cents = 5000000
    worst_case_fee_ppm = 3000
"""


# ─────────────────────────────────────────────────────────────────────────────
# 1. happy path
# ─────────────────────────────────────────────────────────────────────────────


def test_load_example_toml_returns_v3_shadow_config() -> None:
    """真实 services.example.toml 加载返回 V3ShadowConfig 实例, portfolio_id 原样。"""
    config = load_v3_shadow_config(EXAMPLE_TOML)
    assert isinstance(config, V3ShadowConfig)
    assert config.portfolio_id == "paper-v3"


def test_load_example_toml_all_paths_are_absolute_under_repo_root() -> None:
    """真实 example.toml: 所有 Path 字段是绝对路径且归属 repo root。"""
    config = load_v3_shadow_config(EXAMPLE_TOML)
    repo_root_str = str(REPO_ROOT.resolve())
    path_fields = (
        ("evidence_database", config.evidence_database),
        ("blob_root", config.blob_root),
        ("capital_ledger", config.capital_ledger),
        ("gateway_database", config.gateway_database),
        ("shadow_artifacts_dir", config.shadow_artifacts_dir),
        ("policy_path", config.policy_path),
    )
    for label, value in path_fields:
        resolved = Path(value).resolve()
        assert resolved.is_absolute(), f"{label}={value} 不是绝对路径"
        assert str(resolved).startswith(repo_root_str + "/") or str(resolved) == repo_root_str, f"{label}={value} 不归属 repo root {REPO_ROOT}"


def test_load_example_toml_evidence_database_exact_path() -> None:
    """真实 example.toml: evidence_database 精确指向 <repo>/data/v3_shadow/evidence.sqlite3。"""
    config = load_v3_shadow_config(EXAMPLE_TOML)
    assert Path(config.evidence_database).resolve() == EXPECTED_EVIDENCE_DB.resolve()


def test_load_example_toml_policy_path_points_to_policy_v1() -> None:
    """真实 example.toml: policy_path 指向 config/policies/v3/policy-v1.json。"""
    config = load_v3_shadow_config(EXAMPLE_TOML)
    assert config.policy_path.name == "policy-v1.json"
    assert config.policy_path.parent.name == "v3"
    assert config.policy_path.parent.parent.name == "policies"


def test_load_example_toml_sizing_fields_match_toml() -> None:
    """真实 example.toml: sizing 是 SizingConfig 且 5 个字段值与 toml 一致。"""
    config = load_v3_shadow_config(EXAMPLE_TOML)
    assert isinstance(config.sizing, SizingConfig)
    assert config.sizing.per_ticker_gross_cap_cents == 500000
    assert config.sizing.per_industry_gross_cap_cents == 1500000
    assert config.sizing.per_day_gross_cap_cents == 3000000
    assert config.sizing.portfolio_gross_cap_cents == 5000000
    assert config.sizing.worst_case_fee_ppm == 3000
    # min_lot_units 有默认 (LOT_UNITS=100), 不在 toml, 应保留默认。
    assert config.sizing.min_lot_units == 100


# ─────────────────────────────────────────────────────────────────────────────
# 2. 相对路径 cwd 无关
# ─────────────────────────────────────────────────────────────────────────────


def test_relative_paths_resolve_against_repo_root_not_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """即使 cwd=tmp_path, 相对路径仍相对 repo root 解析 (不依赖 cwd)。"""
    monkeypatch.chdir(tmp_path)
    # 用绝对路径指向 repo 内 example 文件 (排除"找不到文件"的混淆)。
    assert EXAMPLE_TOML.is_absolute()

    config = load_v3_shadow_config(EXAMPLE_TOML)

    resolved = Path(config.evidence_database).resolve()
    # 必须指向 repo_root 下的 evidence.sqlite3, 而非 tmp_path 下。
    assert resolved == EXPECTED_EVIDENCE_DB.resolve()
    tmp_str = str(tmp_path.resolve())
    assert not str(resolved).startswith(tmp_str + "/"), f"evidence_database 误相对 cwd 解析到 tmp_path: {resolved}"


# ─────────────────────────────────────────────────────────────────────────────
# 3-4. fail-closed: 缺字段 / 缺段
# ─────────────────────────────────────────────────────────────────────────────


def test_missing_sizing_field_fails_closed(tmp_path: Path) -> None:
    """缺 sizing.portfolio_gross_cap_cents → fail-closed 抛异常。"""
    toml_path = _write_toml(
        tmp_path,
        "missing_sizing_field.toml",
        _FULL_TOML_TEMPLATE.replace(
            "portfolio_gross_cap_cents = 5000000\n",
            "# portfolio_gross_cap_cents 故意缺失\n",
        ),
    )
    with pytest.raises(Exception):
        load_v3_shadow_config(toml_path)


def test_missing_policy_section_fails_closed(tmp_path: Path) -> None:
    """缺整个 [policy] 段 → fail-closed 抛异常。"""
    content = _FULL_TOML_TEMPLATE.replace(
        """
    [policy]
    path = "config/policies/v3/policy-v1.json"

""",
        "",
    )
    toml_path = _write_toml(tmp_path, "missing_policy_section.toml", content)
    with pytest.raises(Exception):
        load_v3_shadow_config(toml_path)


def test_missing_sizing_section_fails_closed(tmp_path: Path) -> None:
    """缺整个 [sizing] 段 → fail-closed 抛异常。"""
    content = _FULL_TOML_TEMPLATE.replace(
        """
    [sizing]
    per_ticker_gross_cap_cents = 500000
    per_industry_gross_cap_cents = 1500000
    per_day_gross_cap_cents = 3000000
    portfolio_gross_cap_cents = 5000000
    worst_case_fee_ppm = 3000
""",
        "",
    )
    toml_path = _write_toml(tmp_path, "missing_sizing_section.toml", content)
    with pytest.raises(Exception):
        load_v3_shadow_config(toml_path)


def test_missing_paths_field_fails_closed(tmp_path: Path) -> None:
    """缺 [paths] 任一必填键 (evidence_database) → fail-closed 抛异常。"""
    toml_path = _write_toml(
        tmp_path,
        "missing_paths_field.toml",
        _FULL_TOML_TEMPLATE.replace(
            'evidence_database = "data/v3_shadow/evidence.sqlite3"\n',
            "# evidence_database 故意缺失\n",
        ),
    )
    with pytest.raises(Exception):
        load_v3_shadow_config(toml_path)


def test_missing_paths_section_fails_closed(tmp_path: Path) -> None:
    """缺整个 [paths] 段 → fail-closed 抛异常。"""
    content = _FULL_TOML_TEMPLATE.replace(
        """
    [paths]
    portfolio_id = "paper-v3"
    evidence_database = "data/v3_shadow/evidence.sqlite3"
    blob_root = "data/v3_shadow/blobs"
    capital_ledger = "data/v3_shadow/capital.sqlite3"
    gateway_database = "data/v3_shadow/gateway.sqlite3"
    shadow_artifacts_dir = "data/v3_shadow/artifacts"

""",
        "",
    )
    toml_path = _write_toml(tmp_path, "missing_paths_section.toml", content)
    with pytest.raises(Exception):
        load_v3_shadow_config(toml_path)


# ─────────────────────────────────────────────────────────────────────────────
# 5. 文件不存在 fail-closed
# ─────────────────────────────────────────────────────────────────────────────


def test_nonexistent_file_fails_closed(tmp_path: Path) -> None:
    """加载不存在的文件 → fail-closed 抛异常 (FileNotFoundError 或自定义)。"""
    missing = tmp_path / "does-not-exist.toml"
    assert not missing.exists()
    with pytest.raises(Exception):
        load_v3_shadow_config(missing)


# ─────────────────────────────────────────────────────────────────────────────
# 6. toml 语法错误 fail-closed
# ─────────────────────────────────────────────────────────────────────────────


def test_malformed_toml_fails_closed(tmp_path: Path) -> None:
    """toml 语法错误 → fail-closed 抛异常 (tomllib.TOMLDecodeError 或包装异常)。"""
    toml_path = _write_toml(
        tmp_path,
        "malformed.toml",
        """
        [paths  # 缺右括号 = 非法 toml
        portfolio_id = "paper-v3"
        """,
    )
    with pytest.raises(Exception):
        load_v3_shadow_config(toml_path)
