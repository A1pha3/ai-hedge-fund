"""stop_loss_enablement_pack 正确性回归网 (R193 Op1, fixture 驱动 slot 自足).

固化两面装配决策包的判定契约 (R10 纪律: 隔离 slot 无 data/ 工件, 全部
fixture 注入; 真实数据冒烟属宿主侧证据进 receipt):

1. face A 读数与 stop_direction_clause 同守卫同选择 (best_stop_tier 单一
   实现): 形状毒化/零样本/非有限 Δ → None, 不假装有证据;
2. face B 读数消费 backtest --json 排放: schema/sha256/样本守卫, 固定档
   Δ 相对 no_stop 重构后经同一 best_stop_tier 选择 (浅档平局纪律同源);
3. 合取判定 = 两面齐备的机械事实 (缺哪面具名), 不是启用建议 (宪法 #2);
4. 渲染 fail-open: 畸形 payload 整节省略不崩溃 (R85/R115/R119 家族);
5. 输出确定性: 同输入同字节 (无墙钟; as-of 显式声明)。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

import scripts.stop_loss_enablement_pack as pack  # noqa: E402
from scripts.stop_loss_enablement_pack import (  # noqa: E402
    assemble_pack,
    render_md,
    sample_direction_reading,
    stop_direction_reading,
)


# ---------------------------------------------------------------------------
# fixtures: 与真实产物同形的载荷
# ---------------------------------------------------------------------------


def _anatomy_payload(
    regime: str = "crisis",
    n: int = 132,
    base_mean: float = -0.0551,
    grid: dict | None = None,
) -> dict:
    if grid is None:
        grid = {
            "-5%": {"delta_vs_base": 0.0090, "mean_net": -0.0460, "n_stopped": 114, "n_gap_through": 49},
            "-8%": {"delta_vs_base": -0.0042, "mean_net": -0.0593, "n_stopped": 80, "n_gap_through": 19},
        }
    return {
        "production": {
            "by_regime": {
                regime: {
                    "n_included": n,
                    "base": {"mean_net": base_mean},
                    "stop_grid": grid,
                }
            }
        }
    }


def _backtest_payload(
    *,
    no_stop_e: float = 0.02,
    tiers: dict[str, float] | None = None,
    n: int = 1,
    journal_sha: str = "a" * 64,
) -> dict:
    if tiers is None:
        tiers = {"-5%": -0.05, "-8%": -0.08}
    strategies: list[dict] = [
        {"label": "no_stop (T+10 收盘)", "stop_mode": "none", "stop_param": None, "n": n, "E": no_stop_e, "stop_trig": 0}
    ]
    for tier, param in tiers.items():
        strategies.append(
            {
                "label": f"fixed {tier}",
                "stop_mode": "fixed_pct",
                "stop_param": param,
                "n": n,
                "E": no_stop_e - 0.03,
                "stop_trig": n,
            }
        )
    return {
        "schema": "backtest_exit_strategies_json_v1",
        "journal": "/x/journal.jsonl",
        "journal_sha256": journal_sha,
        "n_trades": n,
        "time_exit": 10,
        "strategies": strategies,
        "baseline_excluded": {},
    }


def _full_pack_payload() -> dict:
    face_a = stop_direction_reading(_anatomy_payload(), "crisis", "20260911")
    face_b = sample_direction_reading(_backtest_payload())
    return assemble_pack(
        as_of="20260912",
        crisis_streak=(3, datetime(2026, 9, 11).date()),
        drawdown=-0.05,
        face_a=face_a,
        face_b=face_b,
        stop_mode="none",
        drawdown_ref=-0.15,
    )


# ---------------------------------------------------------------------------
# face A: stop_direction_reading
# ---------------------------------------------------------------------------


def test_face_a_reading_happy_path():
    reading = stop_direction_reading(_anatomy_payload(), "crisis", "20260911")
    assert reading is not None
    assert reading["as_of"] == "20260911"
    assert reading["regime"] == "crisis"
    assert reading["n"] == 132
    assert reading["base_mean"] == pytest.approx(-0.0551)
    assert reading["best_tier"] == "-5%"
    assert reading["best_delta"] == pytest.approx(0.0090)
    assert reading["n_stopped"] == 114
    assert reading["n_gap_through"] == 49


def test_face_a_reading_tie_prefers_shallower():
    grid = {
        "-5%": {"delta_vs_base": 0.01},
        "-12%": {"delta_vs_base": 0.01},
    }
    reading = stop_direction_reading(_anatomy_payload(grid=grid), "crisis", "20260911")
    assert reading is not None and reading["best_tier"] == "-5%"


@pytest.mark.parametrize(
    "payload,label,date",
    [
        (None, "crisis", "20260911"),
        ("not-a-dict", "crisis", "20260911"),
        ({}, "crisis", "20260911"),
        ({"production": {"by_regime": {"crisis": {"n_included": 0, "base": {"mean_net": -0.05}, "stop_grid": {"-5%": {"delta_vs_base": 0.01}}}}}}, "crisis", "20260911"),
        (_anatomy_payload(base_mean=None), "crisis", "20260911"),
        (_anatomy_payload(grid={}), "crisis", "20260911"),
        (_anatomy_payload(grid={"garbage": {"delta_vs_base": 0.01}}), "crisis", "20260911"),
        (_anatomy_payload(grid={"-5%": {"delta_vs_base": True}}), "crisis", "20260911"),
        (_anatomy_payload(), "risk_on", "20260911"),
        (_anatomy_payload(), "crisis", ""),
        (_anatomy_payload(), "crisis", None),
    ],
)
def test_face_a_reading_poison_returns_none(payload, label, date):
    assert stop_direction_reading(payload, label, date) is None


def test_face_a_reading_omits_optional_fields_when_absent():
    reading = stop_direction_reading(
        _anatomy_payload(grid={"-5%": {"delta_vs_base": 0.01}}), "crisis", "20260911"
    )
    assert reading is not None
    assert "best_mean" not in reading
    assert "n_stopped" not in reading
    assert "n_gap_through" not in reading


# ---------------------------------------------------------------------------
# face B: sample_direction_reading
# ---------------------------------------------------------------------------


def test_face_b_reading_happy_path():
    reading = sample_direction_reading(_backtest_payload(no_stop_e=0.02))
    assert reading is not None
    assert reading["journal_sha256"] == "a" * 64
    assert reading["n_trades"] == 1
    assert reading["no_stop_e"] == pytest.approx(0.02)
    # 每个 fixed 档 E = no_stop - 0.03 → Δ = -0.03, 全体平局 → 浅档 -5% 胜出
    assert reading["best_tier"] == "-5%"
    assert reading["best_delta"] == pytest.approx(-0.03)
    assert [row["tier"] for row in reading["tiers"]] == ["-5%", "-8%"]


def test_face_b_reading_prefers_positive_delta():
    payload = _backtest_payload(no_stop_e=0.01, tiers={"-5%": -0.05, "-8%": -0.08})
    payload["strategies"][1]["E"] = 0.01  # -5% 档与 no_stop 持平 → Δ=0
    reading = sample_direction_reading(payload)
    assert reading is not None
    assert reading["best_tier"] == "-5%"
    assert reading["best_delta"] == pytest.approx(0.0)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: {**p, "schema": "other_v1"},
        lambda p: {**p, "journal_sha256": ""},
        lambda p: {**p, "journal_sha256": 123},
        lambda p: {**p, "n_trades": 0},
        lambda p: {**p, "n_trades": True},
        lambda p: {**p, "strategies": []},
        lambda p: {**p, "strategies": "nope"},
        lambda p: {k: v for k, v in p.items() if k != "strategies"},
    ],
)
def test_face_b_reading_poison_returns_none(mutate):
    assert sample_direction_reading(mutate(_backtest_payload())) is None


def test_face_b_reading_no_no_stop_row_returns_none():
    payload = _backtest_payload()
    payload["strategies"] = [r for r in payload["strategies"] if r["stop_mode"] != "none"]
    assert sample_direction_reading(payload) is None


def test_face_b_reading_zero_n_rows_do_not_count():
    payload = _backtest_payload()
    for row in payload["strategies"]:
        row["n"] = 0
        row["E"] = None
    assert sample_direction_reading(payload) is None


def test_face_b_reading_non_fixed_rows_skipped():
    payload = _backtest_payload()
    payload["strategies"].append(
        {"label": "ATR 2.0x", "stop_mode": "atr", "stop_param": 2.0, "n": 1, "E": 0.5, "stop_trig": 1}
    )
    reading = sample_direction_reading(payload)
    assert reading is not None
    assert [row["tier"] for row in reading["tiers"]] == ["-5%", "-8%"]


# ---------------------------------------------------------------------------
# assemble_pack: 机械合取判定
# ---------------------------------------------------------------------------


def test_assemble_both_faces_ready():
    payload = _full_pack_payload()
    assert payload["faces_ready"] is True
    assert payload["missing_faces"] == []
    assert payload["crisis_streak"] == {"streak": 3, "anchor": "20260911"}
    assert payload["drawdown"]["value"] == -0.05
    assert payload["drawdown"]["margin_pp"] == pytest.approx(10.0)


def test_assemble_missing_faces_named():
    only_b = assemble_pack(
        as_of="20260912", crisis_streak=None, drawdown=None,
        face_a=None, face_b=sample_direction_reading(_backtest_payload()),
        stop_mode="none", drawdown_ref=-0.15,
    )
    assert only_b["faces_ready"] is False
    assert only_b["missing_faces"] == ["face_a_current"]
    only_a = assemble_pack(
        as_of="20260912", crisis_streak=None, drawdown=None,
        face_a=stop_direction_reading(_anatomy_payload(), "crisis", "20260911"),
        face_b=None, stop_mode="none", drawdown_ref=-0.15,
    )
    assert only_a["missing_faces"] == ["face_b_sample"]
    both = assemble_pack(
        as_of="20260912", crisis_streak=None, drawdown=None,
        face_a=None, face_b=None, stop_mode="none", drawdown_ref=-0.15,
    )
    assert both["missing_faces"] == ["face_a_current", "face_b_sample"]
    assert "crisis_streak" not in both
    assert "drawdown" not in both


def test_assemble_poisoned_drawdown_omitted():
    payload = assemble_pack(
        as_of="20260912", crisis_streak=None, drawdown=True,
        face_a=None, face_b=None, stop_mode="none", drawdown_ref=-0.15,
    )
    assert "drawdown" not in payload


def test_assemble_deterministic_bytes():
    a = json.dumps(_full_pack_payload(), ensure_ascii=False, sort_keys=True)
    b = json.dumps(_full_pack_payload(), ensure_ascii=False, sort_keys=True)
    assert a == b


# ---------------------------------------------------------------------------
# render_md: fail-open 渲染
# ---------------------------------------------------------------------------


def test_render_md_full_payload_key_lines():
    md = render_md(_full_pack_payload())
    assert md.startswith("# 止损启用两面证据决策包（as-of 20260912）")
    assert "结论：两面齐备 = 是" in md
    assert "Regime：连续 crisis 3 日（截至 0911）" in md
    assert "回撤：-5.0%（距 -15% 降仓参考线，余量 +10.0pp）" in md
    assert "止损执行模式：none（登记: 不启用）" in md
    assert "exit_anatomy 20260911 · 生产表/crisis/全候选 · n=132" in md
    assert "最佳止损档 -5%（Δ+0.90pp" in md
    assert "no_stop E=+2.00%" in md
    assert "最佳固定档：-5%（Δ-3.00pp）" in md
    assert "启用判定属 owner" in md


def test_render_md_missing_face_named():
    payload = assemble_pack(
        as_of="20260912", crisis_streak=None, drawdown=None,
        face_a=None, face_b=sample_direction_reading(_backtest_payload()),
        stop_mode="none", drawdown_ref=-0.15,
    )
    md = render_md(payload)
    assert "结论：两面齐备 = 否（缺：当期方向）" in md
    assert "缺失：当期方向证据未就绪" in md


def test_render_md_poison_omits_not_crashes():
    payload = _full_pack_payload()
    payload["face_a_current"] = {"best_tier": "-5%"}  # 缺 best_delta → 整节缺失分支
    payload["face_b_sample"] = {"journal_sha256": "a" * 64}  # 缺 tiers → 整节缺失分支
    payload["crisis_streak"] = {"streak": "x"}  # 非有限 → 子句省略
    payload["drawdown"] = {"value": "x", "ref": -0.15}
    md = render_md(payload)
    assert "缺失：当期方向证据未就绪" in md
    assert "缺失：样本期方向证据未就绪" in md
    assert "Regime：" not in md
    assert "回撤：" not in md


@pytest.mark.parametrize("bad", [None, "str", 42, {}])
def test_render_md_structural_poison(bad):
    assert render_md(bad) == ""


def test_render_md_weird_faces_ready_returns_empty():
    payload = _full_pack_payload()
    payload["faces_ready"] = "yes"
    assert render_md(payload) == ""


# ---------------------------------------------------------------------------
# CLI 端到端 (注入 seam, 确定性)
# ---------------------------------------------------------------------------


def _run_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> int:
    reports = tmp_path / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "exit_anatomy_20260911.json").write_text(
        json.dumps(_anatomy_payload()), encoding="utf-8"
    )
    bt = tmp_path / "bt.json"
    bt.write_text(json.dumps(_backtest_payload(no_stop_e=0.02)), encoding="utf-8")
    history = {"20260909": "risk_off", "20260910": "crisis", "20260911": "crisis"}
    monkeypatch.setattr(pack, "_load_regime_history", lambda: history)
    monkeypatch.setattr(
        pack, "_current_cn_datetime", lambda: datetime(2026, 9, 12, 10, 0, 0)
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "stop_loss_enablement_pack.py",
            "--as-of",
            "20260911",
            "--reports-dir",
            str(reports),
            "--backtest-json",
            str(bt),
            "--drawdown",
            "-0.05",
            "--out-dir",
            str(tmp_path / "out"),
        ]
        + argv,
    )
    return pack.main()


def test_cli_end_to_end_writes_deterministic_pack(tmp_path, monkeypatch):
    rc1 = _run_cli(tmp_path, monkeypatch, [])
    rc2 = _run_cli(tmp_path, monkeypatch, [])
    assert rc1 == rc2 == 0
    j1 = tmp_path / "out" / "stop_loss_enablement_pack_20260911.json"
    m1 = tmp_path / "out" / "stop_loss_enablement_pack_20260911.md"
    assert j1.exists() and m1.exists()
    payload = json.loads(j1.read_text(encoding="utf-8"))
    assert payload["schema"] == "stop_loss_enablement_pack_v1"
    assert payload["as_of"] == "20260911"
    assert payload["faces_ready"] is True
    assert payload["face_a_current"]["best_tier"] == "-5%"
    assert payload["face_b_sample"]["no_stop_e"] == pytest.approx(0.02)
    md = m1.read_text(encoding="utf-8")
    assert "结论：两面齐备 = 是" in md
    assert "Regime：连续 crisis 2 日（截至 0911）" in md
    # 确定性: 同输入同字节 (两次覆盖写一致)
    first = j1.read_bytes()
    _run_cli(tmp_path, monkeypatch, [])
    assert j1.read_bytes() == first


def test_cli_missing_face_a_pack_still_written(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    # 无 exit_anatomy 报告 → face A 缺失, pack 仍产出并具名
    bt = tmp_path / "bt.json"
    bt.write_text(json.dumps(_backtest_payload()), encoding="utf-8")
    monkeypatch.setattr(pack, "_load_regime_history", lambda: {"20260911": "crisis"})
    monkeypatch.setattr(
        pack, "_current_cn_datetime", lambda: datetime(2026, 9, 12, 10, 0, 0)
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "stop_loss_enablement_pack.py",
            "--as-of",
            "20260911",
            "--reports-dir",
            str(reports),
            "--backtest-json",
            str(bt),
            "--out-dir",
            str(tmp_path / "out"),
        ],
    )
    assert pack.main() == 0
    payload = json.loads(
        (tmp_path / "out" / "stop_loss_enablement_pack_20260911.json").read_text(encoding="utf-8")
    )
    assert payload["faces_ready"] is False
    assert payload["missing_faces"] == ["face_a_current"]
    assert "结论：两面齐备 = 否（缺：当期方向）" in (
        (tmp_path / "out" / "stop_loss_enablement_pack_20260911.md").read_text(encoding="utf-8")
    )


def test_cli_backtest_guard_failure_faces_ready_false(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "exit_anatomy_20260911.json").write_text(
        json.dumps(_anatomy_payload()), encoding="utf-8"
    )
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "wrong"}), encoding="utf-8")
    monkeypatch.setattr(pack, "_load_regime_history", lambda: {"20260911": "crisis"})
    monkeypatch.setattr(
        pack, "_current_cn_datetime", lambda: datetime(2026, 9, 12, 10, 0, 0)
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "stop_loss_enablement_pack.py",
            "--as-of",
            "20260911",
            "--reports-dir",
            str(reports),
            "--backtest-json",
            str(bad),
            "--out-dir",
            str(tmp_path / "out"),
        ],
    )
    assert pack.main() == 0
    payload = json.loads(
        (tmp_path / "out" / "stop_loss_enablement_pack_20260911.json").read_text(encoding="utf-8")
    )
    assert payload["faces_ready"] is False
    assert payload["missing_faces"] == ["face_b_sample"]
