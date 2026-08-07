"""Plan 05 Task 9 S3/S4: V3 shadow CLI 接线 — config 加载 + shadow 编排入口。

本模块是 CLI↔v3 的【库层编排】接线点 (owner 批准方案 A)。两个窄入口:
``run_v3_shadow_daily_action`` / ``run_v3_shadow_auto`` 在 ``--daily-action`` /
``--auto`` 的 v2 渲染后被薄 hook 调用 (dispatcher.py / main.py), 按 policy
``runtime_mode`` 决定是否跑 v3 shadow 编排:

- ``OFF``: 零 v3 调用、零 v3 输出 (v2 行为完全不变)。
- 超前 mode (``BTST_CANARY`` / ``AUTHORITATIVE``, 超前于 Plan 05 的 off|shadow):
  打印 warning + 按 flow 内建行为放行 (只读观测步照常、shadow 管线 skip)。
- ``SHADOW``: 构造库层服务跑编排 (DailyActionFlow / AutoFlow) +
  ``ReportingService`` 投影 → ``render_text`` 中文操作员输出 + ``render_json``
  工件落 v3 namespace。

任何 v3 失败打印 ``⚠ v3 shadow 编排失败`` (整体 try/except), 不影响 v2 退出码
(dispatch handler 异常会改写 rc=1; 故 v3 异常绝不漏出)。

-------------------------------------------------------------------------------
安全边界 (shadow-only 阶段, in-process 偏差)
-------------------------------------------------------------------------------
Plan Architecture 要求 "privileged worker 独立进程 + CLI 不持 writable DSN";
Plan 05 实际是【库层】编排 (Task 1-8 无 FastAPI/uvicorn server 进程层, UDS
worker 留 Plan 06+)。CLI 进程内构造服务持有 capital sqlite 句柄 (shadow 只读),
严格说不满足进程级 writable-DSN 隔离 — owner 知情批准。补偿控制 (AST 守卫锁定,
见 S5 集成测试): (1) 本模块不 import governance/authority 写面、不 import
execution proxy/manual; (2) 不调用 activate_*/publish_entry/claim_send/
record_fill 等 authority 写方法; (3) 证据 signer 用进程内 ephemeral key
(``Ed25519PrivateKey.generate()``, 不读持久化签名材料 — 与 plan 全局约束一致)。

【privileged service-owned】路径 (capital ledger 真实激活态 / signer keystore /
governance authority / broker credential) 刻意不在本模块构造 — 本模块只构造
shadow 观测所需的 v3 namespace 临时树 + ephemeral 身份。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from src.screening.offensive.v3.kernel.sizing import SizingConfig


def _repo_root() -> Path:
    """返回 repo root (含 ``pyproject.toml`` 的目录; 不依赖 cwd)。

    向上 walk 找 ``pyproject.toml``, 比硬编码 ``parents[N]`` 稳健 (层级调整
    无需改 N)。CLI 可从 cron/任意目录运行, 路径解析必须锚定 repo root。
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    # 不可达: 本文件必在 repo 内。fail-closed 不静默回退 cwd。
    raise V3ShadowConfigError(
        "cannot locate repo root (pyproject.toml not found above"
        f" {here})"
    )


class V3ShadowConfigError(ValueError):
    """配置加载/校验失败 (缺字段 / 非法 toml / 文件不存在)。fail-closed。"""


@dataclass(frozen=True)
class V3ShadowConfig:
    """V3 shadow CLI 接线配置 (toml 加载结果, 路径已解析为绝对路径)。

    所有 Path 字段相对 repo root 解析 (不依赖 cwd)。``sizing`` 是 kernel
    ``SizingConfig`` (policy JSON 无对应物, 独立配)。
    """

    portfolio_id: str
    evidence_database: Path
    blob_root: Path
    capital_ledger: Path
    gateway_database: Path
    shadow_artifacts_dir: Path
    policy_path: Path
    sizing: SizingConfig


def _require(data: dict, section: str, key: str) -> object:
    """fail-closed 取 ``data[section][key]``; 缺段/缺键抛 ``V3ShadowConfigError``。"""
    section_obj = data.get(section)
    if not isinstance(section_obj, dict):
        raise V3ShadowConfigError(
            f"v3 shadow config missing [{section}] section"
        )
    if key not in section_obj:
        raise V3ShadowConfigError(
            f"v3 shadow config missing [{section}].{key}"
        )
    return section_obj[key]


def _resolve_path(value: object, repo_root: Path) -> Path:
    """把 toml 路径值解析为绝对路径: 绝对路径原样, 相对路径相对 repo root。"""
    if not isinstance(value, str):
        raise V3ShadowConfigError("v3 shadow config path value must be a string")
    p = Path(value)
    return p if p.is_absolute() else (repo_root / p).resolve()


def load_v3_shadow_config(config_path: Path) -> V3ShadowConfig:
    """加载 v3 shadow toml 配置 → ``V3ShadowConfig`` (fail-closed, cwd 无关)。

    相对路径相对 repo root 解析 (非 cwd)。缺任一必填字段、文件不存在、toml
    语法错误均抛 ``V3ShadowConfigError`` (fail-closed — 配置损坏不得静默
    回退默认, 也不得影响 v2 退出码; 调用方 catch 后按 OFF 处理)。
    """
    path = Path(config_path)
    if not path.is_absolute():
        path = _repo_root() / path
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise V3ShadowConfigError(
            f"v3 shadow config not found: {config_path}"
        ) from exc
    except OSError as exc:
        raise V3ShadowConfigError(
            f"v3 shadow config unreadable: {config_path}: {exc}"
        ) from exc
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise V3ShadowConfigError(
            f"v3 shadow config malformed toml: {config_path}: {exc}"
        ) from exc

    repo_root = _repo_root()
    paths_section = data.get("paths")
    if not isinstance(paths_section, dict):
        raise V3ShadowConfigError("v3 shadow config missing [paths] section")
    try:
        portfolio_id = _require(data, "paths", "portfolio_id")
    except V3ShadowConfigError:
        raise
    if not isinstance(portfolio_id, str) or not portfolio_id:
        raise V3ShadowConfigError("[paths].portfolio_id must be a non-empty string")
    evidence_database = _resolve_path(
        _require(data, "paths", "evidence_database"), repo_root
    )
    blob_root = _resolve_path(_require(data, "paths", "blob_root"), repo_root)
    capital_ledger = _resolve_path(
        _require(data, "paths", "capital_ledger"), repo_root
    )
    gateway_database = _resolve_path(
        _require(data, "paths", "gateway_database"), repo_root
    )
    shadow_artifacts_dir = _resolve_path(
        _require(data, "paths", "shadow_artifacts_dir"), repo_root
    )
    policy_path = _resolve_path(_require(data, "policy", "path"), repo_root)

    sizing_section = data.get("sizing")
    if not isinstance(sizing_section, dict):
        raise V3ShadowConfigError("v3 shadow config missing [sizing] section")
    sizing = SizingConfig(
        per_ticker_gross_cap_cents=int(
            _require(data, "sizing", "per_ticker_gross_cap_cents")
        ),
        per_industry_gross_cap_cents=int(
            _require(data, "sizing", "per_industry_gross_cap_cents")
        ),
        per_day_gross_cap_cents=int(
            _require(data, "sizing", "per_day_gross_cap_cents")
        ),
        portfolio_gross_cap_cents=int(
            _require(data, "sizing", "portfolio_gross_cap_cents")
        ),
        worst_case_fee_ppm=int(_require(data, "sizing", "worst_case_fee_ppm")),
    )

    return V3ShadowConfig(
        portfolio_id=portfolio_id,
        evidence_database=evidence_database,
        blob_root=blob_root,
        capital_ledger=capital_ledger,
        gateway_database=gateway_database,
        shadow_artifacts_dir=shadow_artifacts_dir,
        policy_path=policy_path,
        sizing=sizing,
    )


__all__ = [
    "V3ShadowConfig",
    "V3ShadowConfigError",
    "load_v3_shadow_config",
]
