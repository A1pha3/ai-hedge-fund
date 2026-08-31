"""src 触发器账本只读取面测试 (R85 Op1)。

单一实现自 scripts/winrate_payoff_decomposition.py 迁入 (脚本 re-export);
本文件钉死读取面语义与迁移前逐值一致: 排序/损坏行跳过/缺失容忍/连亮计数
保守断链。全部 tmp 账本, 不触真实 data/reports。
"""

from __future__ import annotations

import json

from src.screening.offensive import threshold_trigger as tt


def _rec(day: str, c1_lit=True, c2_lit=False, c1_judged=True, c2_judged=True,
         armed=False, court=None):
    rec = {
        "date": day,
        "anchor": "production_aligned/t10",
        "min_n": 30,
        "condition_1": {"lit": c1_lit, "judged": c1_judged, "n": 315, "stat": 0.0023},
        "condition_2": {"lit": c2_lit, "judged": c2_judged, "n": 303, "stat": 0.0097},
        "conjunction_armed": armed,
    }
    if court is not None:
        rec["court"] = court
    return rec


def _write(tmp_path, records):
    path = tmp_path / "ledger.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    return path


def test_load_missing_file_returns_empty(tmp_path):
    assert tt.load_trigger_ledger(tmp_path / "none.jsonl") == []


def test_load_sorts_by_date_and_skips_corrupt(tmp_path):
    path = _write(tmp_path, [_rec("20260831"), _rec("20260829")])
    # 追加一行垃圾与一行空行 — advisory 跳过
    with path.open("a", encoding="utf-8") as fh:
        fh.write("not-json\n\n")
    records = tt.load_trigger_ledger(path)
    assert [r["date"] for r in records] == ["20260829", "20260831"]


def test_load_tolerates_both_record_forms(tmp_path):
    """R81 旧形态 (无 court) 与 R84 新形态 (带 court) 同账本共存。"""
    path = _write(tmp_path, [
        _rec("20260830"),
        _rec("20260831", court={"built_at": "2026-08-30", "window_end": "20260830",
                                "rows": 1866, "formula_fingerprint": "aa" * 32}),
    ])
    records = tt.load_trigger_ledger(path)
    assert "court" not in records[0]
    assert records[1]["court"]["window_end"] == "20260830"


def test_stability_empty_ledger_zeroes():
    st = tt.trigger_stability([])
    assert st["records"] == 0
    assert st["condition_1_streak"] == 0
    assert st["conjunction_streak"] == 0
    assert st["first_date"] is None and st["last_date"] is None


def test_stability_streaks_and_conservative_break():
    records = [
        _rec("20260829", c1_lit=False),
        _rec("20260830"),
        _rec("20260831"),
    ]
    st = tt.trigger_stability(records)
    assert st["records"] == 3
    assert st["condition_1_streak"] == 2  # 0829 未亮断链
    assert st["condition_2_streak"] == 0
    assert st["conjunction_streak"] == 0
    assert st["condition_1_last_lit"] is True
    assert st["max_conjunction_streak"] == 0


def test_stability_unjudged_breaks_streak():
    records = [
        _rec("20260829"),
        _rec("20260830", c1_judged=False, c1_lit=False),
        _rec("20260831"),
    ]
    assert tt.trigger_stability(records)["condition_1_streak"] == 1


def test_stability_armed_run_accumulates():
    """武装连亮计数 — 冻结语义 (R81 逐值迁移): 断链后 run_and 永久关闭,
    max_conjunction_streak 只反映最新锚定段 (恒等于当前连亮, 永不超过)。
    字段名『历史最多』与该语义的偏差登记为 R85 Op2 对抗审查候选。"""
    records = [
        _rec("20260829", c1_lit=True, c2_lit=True, armed=True),
        _rec("20260830", c1_lit=True, c2_lit=True, armed=True),
        _rec("20260831", c1_lit=True, c2_lit=False, armed=False),
    ]
    st = tt.trigger_stability(records)
    assert st["conjunction_streak"] == 0  # 最新未武装 → 断链
    assert st["max_conjunction_streak"] == 0  # 冻结语义: 断链即停止累积
    # 正向: 最新连续武装时两字段同步增长
    st2 = tt.trigger_stability(records[:2])
    assert st2["conjunction_streak"] == 2
    assert st2["max_conjunction_streak"] == 2
