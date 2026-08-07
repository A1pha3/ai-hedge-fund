"""Plan 05 Task 9 S4b: v3_shadow CLI 入口单元测试 (mode gating + rc 保护)。

覆盖两个入口的控制流契约 (完整端到端在 S5 集成测试):
1. OFF → 零 v3 输出 (stdout 空、无 shadow 工件目录)、无异常、返回 None。
2. 超前 mode (BTST_CANARY) → 打印 warning + 继续按 flow 内建行为 (不抛)。
3. SHADOW → 编排跑通 (graceful capital: 无 ledger 也产出 projection + JSON 工件)。
4. rc 保护: 编排强制失败 → 打印 ⚠ 编排失败、不抛异常 (v2 rc 不受影响)。
5. fail-safe OFF: config/policy 不可用 → 静默返回 (v3 可选层不打扰 v2)。
6. 同契约作用于 run_v3_shadow_auto。

policy JSON 用 repo 内 policy-v1.json 模板改 runtime_mode (off 模板全 0 caps,
非 OFF mode 无 0-cap 约束)。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.cli.v3_shadow import (
    run_v3_shadow_auto,
    run_v3_shadow_daily_action,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_POLICY_TEMPLATE = _REPO_ROOT / "config/policies/v3/policy-v1.json"

SIGNAL_DATE = date(2026, 8, 5)
NOW = datetime(2026, 8, 6, 9, 0, tzinfo=timezone.utc)  # signal_date 收盘后, 证据窗口内


def _policy_json(runtime_mode: str) -> str:
    """从 repo off 模板派生指定 runtime_mode 的 PolicySnapshot JSON。"""
    template = json.loads(_POLICY_TEMPLATE.read_text(encoding="utf-8"))
    template["runtime_mode"] = runtime_mode
    return json.dumps(template, ensure_ascii=False)


def _write_config(tmp_path: Path, *, runtime_mode: str) -> Path:
    """写一份指向 tmp 树的最小 services.toml + 对应 mode 的 policy JSON。

    全部绝对路径 (config loader 相对路径锚定 repo root, 测试须绕开); 无
    capital ledger (真实运行常态) → 编排走 graceful capital 降级路径。
    """
    policy = tmp_path / "policy.json"
    policy.write_text(_policy_json(runtime_mode), encoding="utf-8")
    shadow = tmp_path / "shadow"
    config = tmp_path / "services.toml"
    config.write_text(
        "\n".join(
            [
                "[paths]",
                'portfolio_id = "paper-v3"',
                f'evidence_database = "{shadow / "evidence.sqlite3"}"',
                f'blob_root = "{shadow / "blobs"}"',
                f'capital_ledger = "{shadow / "capital.sqlite3"}"',
                f'gateway_database = "{shadow / "gateway.sqlite3"}"',
                f'shadow_artifacts_dir = "{shadow / "artifacts"}"',
                "[policy]",
                f'path = "{policy}"',
                "[sizing]",
                "per_ticker_gross_cap_cents = 500000",
                "per_industry_gross_cap_cents = 1500000",
                "per_day_gross_cap_cents = 3000000",
                "portfolio_gross_cap_cents = 5000000",
                "worst_case_fee_ppm = 3000",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config


def _fixed_clock():
    return NOW


# --------------------------------------------------------------------------
# OFF 模式: 零 v3 输出
# --------------------------------------------------------------------------


@pytest.mark.parametrize("entry", [run_v3_shadow_daily_action, run_v3_shadow_auto])
def test_off_mode_zero_v3_output(tmp_path, capsys, entry):
    """OFF → stdout 空、无 shadow 工件目录、无异常 (v2 行为完全不变)。"""
    config = _write_config(tmp_path, runtime_mode="off")
    entry(
        signal_date=SIGNAL_DATE,
        reports_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        config_path=config,
        clock=_fixed_clock,
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert not (tmp_path / "shadow").exists()


@pytest.mark.parametrize("entry", [run_v3_shadow_daily_action, run_v3_shadow_auto])
def test_fail_safe_off_when_config_unavailable(tmp_path, capsys, entry):
    """config 不存在 → 静默返回 (fail-safe OFF, v3 可选层不打扰 v2)。"""
    entry(
        signal_date=SIGNAL_DATE,
        reports_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        config_path=tmp_path / "missing.toml",
        clock=_fixed_clock,
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


# --------------------------------------------------------------------------
# 超前 mode: warning + 内建行为
# --------------------------------------------------------------------------


@pytest.mark.parametrize("entry", [run_v3_shadow_daily_action, run_v3_shadow_auto])
def test_ahead_mode_warns_and_proceeds(tmp_path, capsys, entry):
    """BTST_CANARY → 打印超前 warning + 继续编排 (不抛, v2 rc 安全)。"""
    config = _write_config(tmp_path, runtime_mode="btst_canary")
    entry(
        signal_date=SIGNAL_DATE,
        reports_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        config_path=config,
        clock=_fixed_clock,
    )
    captured = capsys.readouterr()
    assert "超前" in captured.out
    assert captured.err == ""


# --------------------------------------------------------------------------
# SHADOW 模式: 编排跑通 (graceful capital, 无 ledger)
# --------------------------------------------------------------------------


def test_shadow_daily_action_produces_projection_and_artifact(tmp_path, capsys):
    """SHADOW + 无 capital ledger → flow 优雅降级但编排完成: stdout 有 projection,
    JSON 工件落 v3 namespace, 无异常 (rc 保护)。"""
    config = _write_config(tmp_path, runtime_mode="shadow")
    run_v3_shadow_daily_action(
        signal_date=SIGNAL_DATE,
        reports_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        config_path=config,
        clock=_fixed_clock,
    )
    captured = capsys.readouterr()
    assert captured.out != ""
    artifact = tmp_path / "shadow" / "artifacts" / f"daily-action-{SIGNAL_DATE.isoformat()}.json"
    assert artifact.is_file()
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["portfolio_id"] == "paper-v3"
    assert payload["signal_session"] == SIGNAL_DATE.isoformat()


def test_shadow_auto_runs_and_reports_statuses(tmp_path, capsys):
    """SHADOW auto → 打印 v3 auto 状态行 (三步 statuses), 无异常。"""
    config = _write_config(tmp_path, runtime_mode="shadow")
    run_v3_shadow_auto(
        signal_date=SIGNAL_DATE,
        reports_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        config_path=config,
        clock=_fixed_clock,
    )
    captured = capsys.readouterr()
    assert "v3 shadow auto:" in captured.out
    assert captured.err == ""


# --------------------------------------------------------------------------
# rc 保护: 编排失败绝不影响 v2 退出码
# --------------------------------------------------------------------------


def test_composition_failure_is_swallowed_not_raised(tmp_path, capsys, monkeypatch):
    """编排强制失败 → 打印 ⚠ 编排失败 + 不抛异常 (dispatch rc=1 的唯一来源被隔离)。"""
    config = _write_config(tmp_path, runtime_mode="shadow")

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    from src.cli import v3_shadow as shadow_mod

    monkeypatch.setattr(shadow_mod, "_compose_daily_action_services", _boom)
    # 入口不应抛; rc 保护 = 异常在入口内被吞掉。
    run_v3_shadow_daily_action(
        signal_date=SIGNAL_DATE,
        reports_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        config_path=config,
        clock=_fixed_clock,
    )
    captured = capsys.readouterr()
    assert "编排失败" in captured.out
    assert "boom" in captured.out
