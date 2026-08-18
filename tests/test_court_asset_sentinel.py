"""court 证据资产哨点回归 — trap 22 的运营覆盖层 (daemon 日链 advisory).

背景 (2026-08-19 autodev op-e0bda08f): court 表龄/公式指纹漂移此前只在下次
评估消费时被 45 天守卫被动拦截 (trap 20 同款盲区: 策略能力与运营覆盖两层)。
本回归网锁定:
1. 纯函数判定: 健康→[]; 指纹漂移→提示陷阱 22 处置 (diff 前置); 表龄超限/
   manifest 缺失/畸形 → 各自明确提示;
2. CLI advisory 语义: exit 恒 0, 输出一行诊断 (告警不阻塞管道)。
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from court_asset_sentinel import court_asset_problems, main  # noqa: E402


def _manifest(fp: str = "aa11", built_at: str = "2026-08-19") -> dict:
    return {
        "formula_fingerprint": {"btst_breakout_sha256": fp},
        "built_at": built_at,
        "window": {"end": "20260818"},
    }


# ---------- 纯函数判定 ----------


def test_healthy_manifest_no_problems():
    assert court_asset_problems(_manifest(), "aa11", date(2026, 8, 19)) == []


def test_formula_drift_points_to_trap22_protocol():
    problems = court_asset_problems(_manifest(fp="aa11"), "bb22", date(2026, 8, 19))
    assert len(problems) == 1
    assert "陷阱 22" in problems[0]
    assert "diff" in problems[0]  # 处置前置: 先逐行 diff 确认变更性质
    assert "rebuild-force" in problems[0]  # 同行为假阳性的逃生门


def test_stale_age_flags_rebuild():
    problems = court_asset_problems(_manifest(built_at="2026-08-01"), "aa11", date(2026, 10, 15))
    assert len(problems) == 1
    assert "表龄" in problems[0] and "75" in problems[0]  # 天数如实入提示


def test_missing_manifest_reported():
    problems = court_asset_problems(None, "aa11", date(2026, 8, 19))
    assert len(problems) == 1
    assert "缺失" in problems[0]


def test_malformed_manifest_without_fingerprint_is_drift():
    # 指纹字段缺失 → 无法证明一致 → 按漂移披露 (fail-closed 方向)
    problems = court_asset_problems({"built_at": "2026-08-19"}, "aa11", date(2026, 8, 19))
    assert len(problems) == 1
    assert "指纹" in problems[0]


def test_age_boundary_inclusive():
    # 表龄 == 上限当天仍健康 (守卫口径: > 才告警)
    assert court_asset_problems(_manifest(built_at="2026-07-05"), "aa11", date(2026, 8, 19)) == []
    problems = court_asset_problems(_manifest(built_at="2026-07-05"), "aa11", date(2026, 8, 20))
    assert len(problems) == 1


# ---------- CLI advisory 语义 ----------


def test_cli_exit_zero_with_healthy_manifest(tmp_path, capsys):
    import hashlib

    setup = tmp_path / "setup.py"
    setup.write_text("# placeholder", encoding="utf-8")
    sha = hashlib.sha256(setup.read_bytes()).hexdigest()
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps(_manifest(fp=sha)), encoding="utf-8")  # fp 与传入 sha 一致才是健康态
    rc = main(["--manifest", str(m), "--setup-sha", sha])
    assert rc == 0
    out = capsys.readouterr().out
    assert "court 资产" in out and "健康" in out


def test_cli_exit_zero_even_with_problems(tmp_path, capsys):
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps(_manifest(fp="aa11")), encoding="utf-8")
    rc = main(["--manifest", str(m), "--setup-sha", "bb22"])
    assert rc == 0  # advisory: 告警不改退出码
    out = capsys.readouterr().out
    assert "⚠" in out
