"""regime 会话索引算术单一实现测试 (R176 Op1).

三面: ① run_geometry 会话算术逐字语义 (R168/R170 既有形态 + 混合连跑标签);
② 与 daily_action regime gate 常量等值 (披露行形态与 gate 同源性的前提);
③ 脚本零漂移委托 — 三诊断工具 import 面与 src 同一函数/常量对象 (is 身份)。
"""

from __future__ import annotations

from src.screening.offensive.regime_session_geometry import (
    BLOCKED_REGIMES,
    is_blocked,
    run_geometry,
)

_SESSIONS = [
    "20260901",
    "20260902",
    "20260903",
    "20260904",
    "20260907",
    "20260908",
    "20260909",
]
_LABELS_3RUN = {
    "20260901": "normal",
    "20260902": "crisis",
    "20260903": "crisis",
    "20260904": "crisis",
    "20260907": "normal",
    "20260908": "normal",
    "20260909": "normal",
}


# ---------- ① 会话算术语义 ----------


def test_run_geometry_d1_run_three_day_stretch():
    form, dist, run_len, run_labels = run_geometry("20260907", _SESSIONS, _LABELS_3RUN)
    assert (form, dist, run_len) == ("normal", 1, 3)
    assert run_labels == ("crisis", "crisis", "crisis")


def test_run_geometry_d2_and_recovered_day():
    assert run_geometry("20260908", _SESSIONS, _LABELS_3RUN)[:3] == ("normal", 2, 3)
    assert run_geometry("20260909", _SESSIONS, _LABELS_3RUN)[:3] == ("normal", 3, 3)


def test_run_geometry_d1_blip_single_blocked_day():
    labels = dict(_LABELS_3RUN, **{"20260903": "normal", "20260904": "crisis"})
    form, dist, run_len, run_labels = run_geometry("20260907", _SESSIONS, labels)
    assert (form, dist, run_len) == ("normal", 1, 1)
    assert run_labels == ("crisis",)


def test_run_geometry_interrupted_stretch_recounts():
    # n, crisis, normal, crisis, today — 连跑被 normal 打断重新计
    labels = dict(_LABELS_3RUN, **{"20260903": "normal", "20260904": "crisis"})
    _, _, run_len, _ = run_geometry("20260907", _SESSIONS, labels)
    assert run_len == 1


def test_run_geometry_mixed_blocked_stretch_near_to_far():
    # risk_off (远) + crisis (近) 混合连跑: run_labels 自近及远
    labels = dict(_LABELS_3RUN, **{"20260903": "risk_off"})
    form, dist, run_len, run_labels = run_geometry("20260907", _SESSIONS, labels)
    assert (form, dist, run_len) == ("normal", 1, 3)
    assert run_labels == ("crisis", "risk_off", "crisis")


def test_run_geometry_non_normal_forms():
    assert run_geometry("20260904", _SESSIONS, _LABELS_3RUN) == ("blocked", 0, 0, ())
    assert run_geometry("20269999", _SESSIONS, _LABELS_3RUN)[0] == "unknown"
    labels_no_prior = {d: "normal" for d in _SESSIONS}
    assert run_geometry("20260907", _SESSIONS, labels_no_prior) == ("no_prior", 0, 0, ())


# ---------- ② 与 gate 常量等值 ----------


def test_blocked_regimes_tuple_shape_and_gate_equivalence():
    assert BLOCKED_REGIMES == ("crisis", "risk_off")
    assert list(BLOCKED_REGIMES) == ["crisis", "risk_off"]
    from src.screening.offensive import daily_action as da

    assert set(BLOCKED_REGIMES) == set(da._REGIME_GATE_BLOCK_REGIMES)
    assert is_blocked("crisis") and is_blocked("risk_off")
    assert not is_blocked("normal")
    assert not is_blocked("")
    assert not is_blocked(None)


# ---------- ③ 脚本零漂移委托 (is 身份) ----------


def test_scripts_delegate_to_src_single_implementation():
    import scripts.regime_blocked_run_conditioning as blocked_run
    import scripts.regime_proximity_conditioning as proximity
    import scripts.regime_run_contrast_robustness as robustness

    assert blocked_run.run_geometry is run_geometry
    assert robustness.run_geometry is run_geometry
    assert proximity.BLOCKED_REGIMES is BLOCKED_REGIMES
    assert blocked_run.BLOCKED_REGIMES is BLOCKED_REGIMES
    assert robustness.BLOCKED_REGIMES is BLOCKED_REGIMES
    assert blocked_run._is_blocked is is_blocked
    assert proximity._is_blocked is is_blocked
