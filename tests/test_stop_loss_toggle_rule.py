"""stop_loss_toggle_rule 正确性回归网 (R195 Op1, fixture 驱动 slot 自足).

固化注册 tri-state / 严格校验 / 武装判定 / packet 守卫的契约 (阈值 K 机器
R112-R129 的 D 面镜像)。
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

import scripts.stop_loss_toggle_rule_packet as packet  # noqa: E402
from src.screening.offensive import stop_loss_toggle_rule as rule_mod  # noqa: E402
from src.screening.offensive.stop_loss_toggle_rule import (  # noqa: E402
    arming_reading,
    consecutive_non_crisis,
    load_rule,
    validate_rule,
)


def _valid_rule() -> dict:
    return {
        "schema": "stop_loss_toggle_rule_v1",
        "registered_date": "20260912",
        "k_crisis_sessions": 5,
        "n_normal_sessions_to_disable": 5,
        "require_delta_positive": True,
        "note": "owner 预注册 (示例)",
    }


# ---------------------------------------------------------------------------
# validate_rule 严格校验
# ---------------------------------------------------------------------------


def test_validate_rule_happy_path():
    rule, errors = validate_rule(_valid_rule())
    assert errors == [] and rule is not None
    assert rule["k_crisis_sessions"] == 5


@pytest.mark.parametrize(
    "mutate,expected_error",
    [
        (lambda r: {**r, "schema": "v2"}, "schema_mismatch"),
        (lambda r: {**r, "k_crisis_sessions": True}, "invalid_k_crisis_sessions"),
        (lambda r: {**r, "k_crisis_sessions": 0}, "invalid_k_crisis_sessions"),
        (lambda r: {**r, "k_crisis_sessions": "5"}, "invalid_k_crisis_sessions"),
        (lambda r: {**r, "n_normal_sessions_to_disable": -1}, "invalid_n_normal_sessions_to_disable"),
        (lambda r: {**r, "registered_date": "2026-09-12"}, "invalid_registered_date"),
        (lambda r: {**r, "registered_date": 20260912}, "invalid_registered_date"),
        (lambda r: {**r, "require_delta_positive": "yes"}, "invalid_require_delta_positive"),
        (lambda r: {**r, "note": ""}, "invalid_note"),
        (lambda r: {**r, "extra": 1}, "unknown_fields"),
        (lambda r: {k: v for k, v in r.items() if k != "note"}, "invalid_note"),
    ],
)
def test_validate_rule_poison(mutate, expected_error):
    rule, errors = validate_rule(mutate(_valid_rule()))
    assert rule is None
    assert any(expected_error in e for e in errors)


def test_validate_rule_non_dict():
    for bad in (None, "str", 42, []):
        rule, errors = validate_rule(bad)
        assert rule is None and errors == ["rule_not_object"]


# ---------------------------------------------------------------------------
# load_rule tri-state
# ---------------------------------------------------------------------------


def test_load_rule_absent():
    rule, reason = load_rule(Path("/nonexistent/rule.json"))
    assert rule is None and reason is None


def test_load_rule_valid(tmp_path):
    path = tmp_path / "rule.json"
    path.write_text(json.dumps(_valid_rule()), encoding="utf-8")
    rule, reason = load_rule(path)
    assert reason is None and rule is not None and rule["k_crisis_sessions"] == 5


def test_load_rule_corrupt_fail_closed(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    rule, reason = load_rule(path)
    assert rule is None and reason == "rule_unreadable"

    path2 = tmp_path / "invalid.json"
    path2.write_text(json.dumps({**_valid_rule(), "schema": "wrong"}), encoding="utf-8")
    rule2, reason2 = load_rule(path2)
    assert rule2 is None and reason2.startswith("rule_invalid:")


# ---------------------------------------------------------------------------
# consecutive_non_crisis
# ---------------------------------------------------------------------------


def test_consecutive_non_crisis_counts_trailing():
    history = {
        "20260901": "normal", "20260902": "crisis", "20260903": "crisis",
        "20260904": "normal", "20260905": "normal",
    }
    assert consecutive_non_crisis(history, date(2026, 9, 5)) == 2
    assert consecutive_non_crisis(history, date(2026, 9, 3)) == 0  # 当日 crisis
    assert consecutive_non_crisis(history, date(2026, 9, 1)) == 1


def test_consecutive_non_crisis_poison_and_empty():
    history = {"bad_key": "normal", 20260902: "crisis", "20260903": "normal"}
    # int 键 str 化 "20260902" 可解析 → 参与计数 (与 _crisis_streak 同语义);
    # 尾部 0903 normal 计 1, 0902 crisis 即停; "bad_key" 毒化键跳过不计数
    assert consecutive_non_crisis(history, date(2026, 9, 3)) == 1
    assert consecutive_non_crisis({"xxx": "normal"}, date(2026, 9, 3)) == 0
    assert consecutive_non_crisis({}, date(2026, 9, 3)) == 0
    assert consecutive_non_crisis(None, date(2026, 9, 3)) == 0


# ---------------------------------------------------------------------------
# arming_reading
# ---------------------------------------------------------------------------


def test_arming_all_conditions_met():
    reading = arming_reading(
        _valid_rule(), crisis_streak=5, current_delta=0.009,
        consecutive_non_crisis=0, stop_mode="none",
    )
    assert reading["registered"] is True
    assert reading["enable_armed"] is True
    assert reading["disable_due"] is False
    assert any("enable_armed" in r for r in reading["enable_reasons"])


def test_arming_streak_short_named():
    reading = arming_reading(
        _valid_rule(), crisis_streak=3, current_delta=0.009,
        consecutive_non_crisis=0, stop_mode="none",
    )
    assert reading["enable_armed"] is False
    assert "crisis_streak 3/5" in reading["enable_reasons"]


def test_arming_delta_missing_and_nonpositive():
    reading = arming_reading(
        _valid_rule(), crisis_streak=6, current_delta=None,
        consecutive_non_crisis=0, stop_mode="none",
    )
    assert reading["enable_armed"] is False
    assert "current_delta_missing" in reading["enable_reasons"]

    reading2 = arming_reading(
        _valid_rule(), crisis_streak=6, current_delta=-0.01,
        consecutive_non_crisis=0, stop_mode="none",
    )
    assert reading2["enable_armed"] is False
    assert any("≤ 0" in r for r in reading2["enable_reasons"])


def test_arming_no_delta_requirement():
    rule = {**_valid_rule(), "require_delta_positive": False}
    reading = arming_reading(
        rule, crisis_streak=6, current_delta=None,
        consecutive_non_crisis=0, stop_mode="none",
    )
    assert reading["enable_armed"] is True


def test_arming_regime_history_missing_named():
    reading = arming_reading(
        _valid_rule(), crisis_streak=None, current_delta=0.01,
        consecutive_non_crisis=None, stop_mode="none",
    )
    assert reading["enable_armed"] is False
    assert "regime_history_missing" in reading["enable_reasons"]
    assert reading["disable_due"] is False  # 非危机计数缺失 → 不冒充


def test_arming_disable_due_requires_active_stop():
    reading = arming_reading(
        _valid_rule(), crisis_streak=0, current_delta=None,
        consecutive_non_crisis=5, stop_mode="fixed -5%",
    )
    assert reading["disable_due"] is True

    reading2 = arming_reading(
        _valid_rule(), crisis_streak=0, current_delta=None,
        consecutive_non_crisis=5, stop_mode="none",
    )
    assert reading2["disable_due"] is False

    reading3 = arming_reading(
        _valid_rule(), crisis_streak=0, current_delta=None,
        consecutive_non_crisis=5, stop_mode=None,
    )
    assert reading3["disable_due"] is False  # 执行模式缺失不冒充


def test_arming_rule_not_loaded():
    reading = arming_reading(None, crisis_streak=5, current_delta=0.01,
                             consecutive_non_crisis=0, stop_mode="none")
    assert reading == {"registered": False, "reason": "rule_not_loaded"}


# ---------------------------------------------------------------------------
# packet CLI (注入 seam)
# ---------------------------------------------------------------------------


def _run_cli(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["stop_loss_toggle_rule_packet.py", *argv])
    return packet.main()


def test_preview_zero_write_deterministic(tmp_path, monkeypatch):
    out_marker = tmp_path / "side_effect.json"
    monkeypatch.setattr(packet, "_load_regime_history", lambda: {
        "20260910": "crisis", "20260911": "crisis", "20260912": "crisis",
    })
    monkeypatch.setattr(packet, "_execution_stop_mode", lambda: "none")
    rc = _run_cli(monkeypatch, ["preview", "--k", "2", "--n", "5",
                                "--rule-path", str(out_marker)])
    assert rc == 0
    assert not out_marker.exists()  # preview 零写入


def test_write_then_refuse_overwrite(tmp_path, monkeypatch):
    rule_path = tmp_path / "rule.json"
    argv = ["--write", "--k", "3", "--n", "4", "--no-require-delta",
            "--note", "owner 注册", "--rule-path", str(rule_path),
            "--registered-date", "20260912"]
    assert _run_cli(monkeypatch, argv) == 0
    written = json.loads(rule_path.read_text(encoding="utf-8"))
    assert written["k_crisis_sessions"] == 3 and written["require_delta_positive"] is False
    # 拒覆写
    assert _run_cli(monkeypatch, argv) == 2
    # note 必填
    assert _run_cli(monkeypatch, ["--write", "--k", "3", "--n", "4",
                                  "--rule-path", str(tmp_path / "r2.json")]) == 2
    # 负 k 拒绝
    assert _run_cli(monkeypatch, ["--write", "--k", "-1", "--n", "4", "--note", "x",
                                  "--rule-path", str(tmp_path / "r3.json")]) == 2


def test_status_tri_states(tmp_path, monkeypatch):
    rule_path = tmp_path / "rule.json"
    monkeypatch.setattr(packet, "_load_regime_history", lambda: {
        "20260909": "crisis", "20260910": "crisis", "20260911": "crisis",
        "20260912": "normal",
    })
    monkeypatch.setattr(packet, "_execution_stop_mode", lambda: "none")
    monkeypatch.setattr(
        packet, "_current_direction_delta",
        lambda reports_dir, label: (0.009, None),
    )
    # 未注册 → rc 0
    argv = ["status", "--as-of", "20260912", "--rule-path", str(rule_path),
            "--reports-dir", str(tmp_path)]
    assert _run_cli(monkeypatch, argv) == 0
    # 已注册 → JSON 读数
    rule_path.write_text(json.dumps(_valid_rule()), encoding="utf-8")
    assert _run_cli(monkeypatch, argv) == 0
    # 损坏 → rc 2 fail-closed
    rule_path.write_text("{broken", encoding="utf-8")
    assert _run_cli(monkeypatch, argv) == 2


# ---------------------------------------------------------------------------
# R195 Op2: would-have-armed 推演直接单元覆盖 (P11 定谳为等价变异——CLI note
# 检查与 validate_rule invalid_note 双重防御, 删一层行为不变)
# ---------------------------------------------------------------------------


def test_would_have_armed_dates_k2():
    """假想推演: 窗口内 crisis streak ≥ k 的日期逐日列出 (preview 的直接语义)。"""
    history = {
        "20260901": "normal", "20260902": "crisis", "20260903": "crisis",
        "20260904": "crisis", "20260905": "normal", "20260906": "crisis",
    }
    as_of = date(2026, 9, 6)
    # k=2: 0903 (streak 2) 与 0904 (streak 3) 武装; 0902 (streak 1) 与 0906 (streak 1) 不武装
    armed = packet._would_have_armed_dates(history, as_of, 2)
    assert armed == ["20260903", "20260904"]
    # k=3: 仅 0904
    assert packet._would_have_armed_dates(history, as_of, 3) == ["20260904"]
    # k=4: 无
    assert packet._would_have_armed_dates(history, as_of, 4) == []
    # 毒化键跳过不参与窗口
    history["bad_key"] = "crisis"
    assert packet._would_have_armed_dates(history, as_of, 2) == ["20260903", "20260904"]


# ---------------------------------------------------------------------------
# R203 Op1: stop_mode_note 单一实现 — 止损执行模式子句的作用域真相
# ---------------------------------------------------------------------------


def test_stop_mode_note_none_discloses_production_has_no_stop_face():
    """mode=none: 「登记: 不启用」+ 生产 v2 无止损执行面披露 (预设前告知)。"""
    note = rule_mod.stop_mode_note("none")
    assert note is not None
    assert "登记: 不启用" in note
    assert "生产 v2 台账无止损执行面" in note
    assert "退出仅 T+10 强制" in note


def test_stop_mode_note_enabled_scopes_to_research_journal_only():
    """mode!=none: 「已设」必须限定 legacy journal 研究口径, 禁无限定「已启用」。"""
    note = rule_mod.stop_mode_note("atr_k2")
    assert note is not None
    assert "已设" in note
    assert "仅作用 legacy journal 研究口径" in note
    assert "生产 v2 台账无止损执行面" in note
    assert "退出仍仅 T+10 强制" in note
    # 无限定宣称禁现 — 旧渲染「已启用」是对生产风险控制的虚假宣称 (R203 缺陷本体)
    assert "已启用" not in note


def test_stop_mode_note_poisoned_inputs_return_none():
    """毒化输入 → None (fail-open 家族), 调用方省略子句。"""
    assert rule_mod.stop_mode_note(None) is None
    assert rule_mod.stop_mode_note("") is None
    assert rule_mod.stop_mode_note("   ") is None
    assert rule_mod.stop_mode_note(7) is None
    assert rule_mod.stop_mode_note(["atr_k2"]) is None


def test_stop_mode_note_exact_values_pinned():
    """精确值钉死 (渲染契约, 防措辞漂移松动作用域真相)。"""
    assert rule_mod.stop_mode_note("none") == (
        "登记: 不启用 · 生产 v2 台账无止损执行面，退出仅 T+10 强制"
    )
    assert rule_mod.stop_mode_note("fixed8") == (
        "已设，仅作用 legacy journal 研究口径 · "
        "生产 v2 台账无止损执行面，退出仍仅 T+10 强制"
    )


# ---------------------------------------------------------------------------
# R203 Op2: 对抗审查 BLIND 钉 — packet preview 接线与渲染回退分支
# ---------------------------------------------------------------------------


def test_packet_preview_discloses_mode_scope(monkeypatch, capsys):
    """M11 钉: preview 的执行模式子句必须经 stop_mode_note 作用域真相 —

    note 接线被静默拆除 (回退裸 mode / 旧「已启用」三元) 时本测当场红。
    preview 是交付面之一, 拆线 = 作用域真相从该面静默消失。
    """
    import argparse

    monkeypatch.setattr(packet, "_load_regime_history", lambda: {"20260910": "crisis"})
    monkeypatch.setattr(packet, "_execution_stop_mode", lambda: "atr_k2")
    args = argparse.Namespace(as_of="20260911", k=5, n=5, require_delta=True)
    assert packet._preview(args) == 0
    out = capsys.readouterr().out
    assert "执行模式 atr_k2（已设，仅作用 legacy journal 研究口径" in out
    assert "生产 v2 台账无止损执行面，退出仍仅 T+10 强制）" in out
    assert "已启用" not in out


def test_packet_preview_none_mode_keeps_scope_clause(monkeypatch, capsys):
    """none 态 preview 同样携带作用域 (预设前告知), 不退回旧「登记: 不启用」。"""
    import argparse

    monkeypatch.setattr(packet, "_load_regime_history", lambda: {"20260910": "normal"})
    monkeypatch.setattr(packet, "_execution_stop_mode", lambda: "none")
    args = argparse.Namespace(as_of="20260911", k=5, n=5, require_delta=True)
    assert packet._preview(args) == 0
    out = capsys.readouterr().out
    assert "执行模式 none（登记: 不启用 · 生产 v2 台账无止损执行面，退出仅 T+10 强制）" in out


# ---------------------------------------------------------------------------
# R204 Op1: 非交易日 as-of 的当期方向 Δ 经 anchor 标签解析 (pack face A 同族)
# ---------------------------------------------------------------------------


def _anatomy_for_status() -> dict:
    return {
        "production": {
            "by_regime": {
                "crisis": {
                    "n_included": 132,
                    "base": {"mean_net": -0.0551},
                    "stop_grid": {
                        "-5%": {
                            "delta_vs_base": 0.0090,
                            "mean_net": -0.0460,
                            "n_stopped": 114,
                            "n_gap_through": 49,
                        },
                    },
                }
            }
        }
    }


def test_status_weekend_as_of_current_delta_uses_anchor_label(
    tmp_path, monkeypatch, capsys
):
    """宿主 PoC 镜像面: 注册规则在场时, 周末 as-of 的 Δ 输入此前因
    history.get(墙钟今天)=None 误报 regime_label_missing — 武装判定的 Δ
    条件周末永不可满足, 与 pack face A 同族。修复 = 标签经 anchor 解析。"""
    rule_path = tmp_path / "rule.json"
    rule_path.write_text(json.dumps(_valid_rule()), encoding="utf-8")
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "exit_anatomy_20260911.json").write_text(
        json.dumps(_anatomy_for_status()), encoding="utf-8"
    )
    monkeypatch.setattr(packet, "_load_regime_history", lambda: {
        "20260909": "risk_off", "20260910": "crisis", "20260911": "crisis",
    })
    monkeypatch.setattr(packet, "_execution_stop_mode", lambda: "none")
    argv = [
        "status", "--as-of", "20260913", "--rule-path", str(rule_path),
        "--reports-dir", str(reports),
    ]
    assert _run_cli(monkeypatch, argv) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["current_delta"] == pytest.approx(0.0090)
    assert out["current_delta_missing_reason"] is None
    assert out["crisis_streak"] == 2


def test_status_as_of_before_all_history_delta_still_missing(
    tmp_path, monkeypatch, capsys
):
    """fail-open 守卫: as_of 早于全部有标签日 → anchor None → Δ 缺失理由
    regime_label_missing (修复不改 fail-open 家族语义)。"""
    rule_path = tmp_path / "rule.json"
    rule_path.write_text(json.dumps(_valid_rule()), encoding="utf-8")
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "exit_anatomy_20260911.json").write_text(
        json.dumps(_anatomy_for_status()), encoding="utf-8"
    )
    monkeypatch.setattr(packet, "_load_regime_history", lambda: {
        "20260909": "risk_off", "20260910": "crisis", "20260911": "crisis",
    })
    monkeypatch.setattr(packet, "_execution_stop_mode", lambda: "none")
    argv = [
        "status", "--as-of", "20260101", "--rule-path", str(rule_path),
        "--reports-dir", str(reports),
    ]
    assert _run_cli(monkeypatch, argv) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["current_delta"] is None
    assert out["current_delta_missing_reason"] == "regime_label_missing"
