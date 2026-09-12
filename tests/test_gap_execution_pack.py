"""gap_execution_pack 正确性回归网 (R194 Op1, fixture 驱动 slot 自足).

固化 gap 执行面判定包的契约: 聚合算术 (桶加权)/R15 判据单一真值转发
(不重推导)/跨强度同向计数守卫/毒化 fail-open/渲染省略/确定性。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

import scripts.gap_execution_pack as pack  # noqa: E402
from scripts.gap_execution_pack import (  # noqa: E402
    aggregate_reading,
    assemble_pack,
    conditional_reading,
    render_md,
    within_strength_reading,
)


def _bucket(label: str, n: int, e: float, ci: float | None = None) -> dict:
    return {
        "bucket": label,
        "n": n,
        "wins": int(n * 0.45),
        "winrate": 0.45,
        "expectancy": e,
        "cluster_ci_low_90": ci,
    }


def _gap_anatomy() -> dict:
    return {
        "gap_high_threshold": 0.05,
        "buckets": [
            _bucket("<-5%", 11, 0.0759),
            _bucket("-5~0", 441, 0.0145),
            _bucket("0~2%", 613, 0.0027),
            _bucket("2~5%", 424, -0.0064),
            _bucket("5~10%", 144, -0.0409),
            _bucket(">10%", 14, -0.0349),
        ],
        "within_strength": [
            {"strength_bucket": "<0.50", "gap_high": {"expectancy": -0.054}, "gap_low": {"expectancy": -0.0157}},
            {"strength_bucket": "0.50-0.60", "gap_high": {"expectancy": -0.0562}, "gap_low": {"expectancy": 0.0064}},
            {"strength_bucket": "0.60-0.70", "gap_high": {"expectancy": -0.0038}, "gap_low": {"expectancy": 0.012}},
            {"strength_bucket": "≥0.70", "gap_high": {"expectancy": -0.0337}, "gap_low": {"expectancy": 0.0202}},
        ],
        "split_half": {
            "split_date": "20260203",
            "judgable_count": 4,
            "consistent_count": 3,
            "verdict_hint": "方向跨半不一致 — gap 条件化证据不足 (过拟合风险, R15 同款判据)",
        },
    }


# ---------------------------------------------------------------------------
# aggregate_reading: 聚合算术
# ---------------------------------------------------------------------------


def test_aggregate_weighted_combination():
    r = aggregate_reading(_gap_anatomy())
    assert r is not None
    # 高开组 = 5~10% + >10%: n=158, E = (144×-0.0409 + 14×-0.0349)/158
    assert r["high"]["n"] == 158
    assert r["high"]["expectancy"] == pytest.approx((144 * -0.0409 + 14 * -0.0349) / 158)
    # 低开组 = 其余: n=11+441+613+424=1489
    assert r["low"]["n"] == 1489
    assert r["penalty"] == pytest.approx(r["low"]["expectancy"] - r["high"]["expectancy"])
    assert r["penalty"] > 0


def test_aggregate_missing_bucket_poison():
    anatomy = _gap_anatomy()
    anatomy["buckets"] = [b for b in anatomy["buckets"] if b["bucket"] != ">10%"]
    # 标签集固定但缺席标签不炸组合: 高开组只组合在场的 5~10% (诚实组合不猜测缺失桶)
    r = aggregate_reading(anatomy)
    assert r is not None and r["high"]["n"] == 144

    anatomy2 = _gap_anatomy()
    anatomy2["buckets"] = [b for b in anatomy2["buckets"] if b["bucket"] not in ("5~10%", ">10%")]
    assert aggregate_reading(anatomy2) is None  # 高开组为空 → None

    anatomy3 = _gap_anatomy()
    anatomy3["buckets"][4]["expectancy"] = None
    assert aggregate_reading(anatomy3) is None  # 任一桶 E 缺失 → 整组 None 不部分猜


def test_aggregate_non_dict_payload():
    assert aggregate_reading(None) is None
    assert aggregate_reading({"buckets": "x"}) is None
    assert aggregate_reading({"buckets": []}) is None
    assert aggregate_reading({"buckets": ["junk", 42]}) is None


# ---------------------------------------------------------------------------
# within_strength_reading: 同向计数
# ---------------------------------------------------------------------------


def test_within_strength_all_four_same_direction():
    r = within_strength_reading(_gap_anatomy())
    assert r == {"buckets_total": 4, "buckets_high_worse": 4}


def test_within_strength_counts_only_valid_pairs():
    anatomy = _gap_anatomy()
    anatomy["within_strength"][1]["gap_high"]["expectancy"] = 0.5  # 反向桶
    del anatomy["within_strength"][2]["gap_low"]  # 畸形桶跳过
    anatomy["within_strength"].append("junk")
    r = within_strength_reading(anatomy)
    # judged = 桶0/桶1(反向)/桶3 = 3; high_worse = 桶0/桶3 = 2 (桶1 已反向, 桶2 畸形跳过)
    assert r == {"buckets_total": 3, "buckets_high_worse": 2}


def test_within_strength_poison():
    assert within_strength_reading(None) is None
    assert within_strength_reading({}) is None
    assert within_strength_reading({"within_strength": []}) is None
    assert within_strength_reading({"within_strength": [{"gap_high": {"expectancy": None}, "gap_low": {"expectancy": 0.1}}]}) is None


# ---------------------------------------------------------------------------
# conditional_reading: R15 单一真值转发
# ---------------------------------------------------------------------------


def test_conditional_relays_verdict_verbatim():
    r = conditional_reading(_gap_anatomy()["split_half"])
    assert r is not None
    assert r["verdict_hint"] == "方向跨半不一致 — gap 条件化证据不足 (过拟合风险, R15 同款判据)"
    assert r["judgable_count"] == 4
    assert r["consistent_count"] == 3


def test_conditional_poison():
    assert conditional_reading(None) is None
    assert conditional_reading({}) is None
    assert conditional_reading({"verdict_hint": ""}) is None
    assert conditional_reading({"verdict_hint": 123}) is None


# ---------------------------------------------------------------------------
# assemble_pack + render_md
# ---------------------------------------------------------------------------


def test_assemble_full_readings_ready():
    payload = assemble_pack(report_date="20260911", gap_anatomy=_gap_anatomy())
    assert payload["schema"] == "gap_execution_pack_v1"
    assert payload["as_of"] == "20260911"
    assert payload["readings_ready"] == 3
    assert payload["missing_readings"] == []
    assert len(payload["bucket_gradient"]) == 6


def test_assemble_missing_readings_named():
    payload = assemble_pack(report_date="20260911", gap_anatomy={"buckets": _gap_anatomy()["buckets"]})
    assert payload["readings_ready"] == 1
    assert payload["missing_readings"] == ["within_strength", "conditional_r15"]
    empty = assemble_pack(report_date="20260911", gap_anatomy=None)
    assert empty["readings_ready"] == 0
    assert empty["missing_readings"] == ["aggregate", "within_strength", "conditional_r15"]


def test_assemble_deterministic_bytes():
    a = json.dumps(assemble_pack(report_date="20260911", gap_anatomy=_gap_anatomy()), ensure_ascii=False, sort_keys=True)
    b = json.dumps(assemble_pack(report_date="20260911", gap_anatomy=_gap_anatomy()), ensure_ascii=False, sort_keys=True)
    assert a == b


def test_render_md_full_payload_key_lines():
    md = render_md(assemble_pack(report_date="20260911", gap_anatomy=_gap_anatomy()))
    assert md.startswith("# gap>5% 执行面判定包（court 证据 as-of 20260911）")
    assert "读数齐备：3/3" in md
    assert "高开≥5%：E -4.04%（n=158）" in md
    assert "罚分" in md
    assert "高开更差桶数：4/4" in md
    assert "方向跨半不一致 — gap 条件化证据不足" in md
    assert "判定汇总 ≠ 剔除决策" in md
    assert "owner gate" in md


def test_render_md_partial_readings():
    payload = assemble_pack(report_date="20260911", gap_anatomy={"buckets": _gap_anatomy()["buckets"]})
    md = render_md(payload)
    assert "读数齐备：1/3" in md
    assert "缺失：跨强度读数不完整" in md
    assert "缺失：R15 判据读数不完整" in md


def test_render_md_poison_omits_not_crashes():
    payload = assemble_pack(report_date="20260911", gap_anatomy=_gap_anatomy())
    payload["aggregate"] = {"high": {"n": "x", "expectancy": -0.04}, "low": {"n": 100, "expectancy": 0.0}, "penalty": 0.04}
    payload["bucket_gradient"] = "not-a-list"
    payload["readings_ready"] = "3"
    assert render_md(payload) == ""  # readings_ready 非有限 → 整体拒绝
    payload["readings_ready"] = 3
    md = render_md(payload)
    assert "缺失：聚合读数不完整" in md
    assert "桶梯度" not in md  # 梯度非列表 → 整节省略


@pytest.mark.parametrize("bad", [None, "str", 42, {}])
def test_render_md_structural_poison(bad):
    assert render_md(bad) == ""


# ---------------------------------------------------------------------------
# CLI 端到端 (注入 seam, 确定性)
# ---------------------------------------------------------------------------


def _write_report(tmp_path: Path) -> Path:
    reports = tmp_path / "reports"
    reports.mkdir(exist_ok=True)
    report = {"universes": {"production_aligned": {"gap_anatomy": _gap_anatomy()}}}
    (reports / "winrate_payoff_decomposition_20260911.json").write_text(
        json.dumps(report), encoding="utf-8"
    )
    return reports


def test_cli_end_to_end_deterministic(tmp_path, monkeypatch):
    reports = _write_report(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "gap_execution_pack.py",
        "--reports-dir", str(reports),
        "--out-dir", str(tmp_path / "out"),
    ])
    assert pack.main() == 0
    j1 = tmp_path / "out" / "gap_execution_pack_20260911.json"
    assert j1.exists()
    payload = json.loads(j1.read_text(encoding="utf-8"))
    assert payload["as_of"] == "20260911"
    assert payload["readings_ready"] == 3
    first = j1.read_bytes()
    assert pack.main() == 0
    assert j1.read_bytes() == first


def test_cli_no_report_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "gap_execution_pack.py",
        "--reports-dir", str(tmp_path / "empty"),
        "--out-dir", str(tmp_path / "out"),
    ])
    assert pack.main() == 2
    assert not (tmp_path / "out").exists()


# ---------------------------------------------------------------------------
# R194 Op2 盲区钉住 (探针 P01/P06/P11 定谳后的复跑 TEETH)
# ---------------------------------------------------------------------------


def test_aggregate_zero_n_bucket_rejected():
    """探针 P01: 零样本桶不得进入加权组合 (n=0 桶冒充证据同 R181 拒绝族)。"""
    anatomy = _gap_anatomy()
    anatomy["buckets"].append(_bucket(">10%", 0, 0.05))
    assert aggregate_reading(anatomy) is None


def test_conditional_bool_counts_rejected():
    """探针 P06: judgable/consistent_count 是计数不是布尔 — bool 毒化时
    该字段整体缺席 (int(True)=1 冒充计数是单一真值转发面的静默改写)。"""
    split_half = _gap_anatomy()["split_half"]
    split_half["judgable_count"] = True
    reading = conditional_reading(split_half)
    assert reading is not None
    assert "judgable_count" not in reading
    assert reading["consistent_count"] == 3


def test_bucket_gradient_non_str_label_skipped():
    """探针 P11: 梯度表桶标签必须为字符串 — 非 str 标签 (毒化/演化形态)
    整行跳过, 不进入渲染面。"""
    anatomy = _gap_anatomy()
    anatomy["buckets"].append({"bucket": 123, "n": 50, "expectancy": 0.01})
    gradient = assemble_pack(report_date="20260911", gap_anatomy=anatomy)["bucket_gradient"]
    assert all(row["bucket"] != 123 for row in gradient)
    assert len(gradient) == 6
