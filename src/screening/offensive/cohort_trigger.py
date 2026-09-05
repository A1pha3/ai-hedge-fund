"""日层 cohort 触发器账本只读取面 (R126 Op1) — 强度阈值触发器
(threshold_trigger) 的日层同构族。

单一实现: 判定快照的**落账**在 ``scripts/btst_signal_day_cohort.py``
(数据增长耦合: court 重建 → 夜刷 cohort 刷新 → 账本追加, 镜像 R84 强度
族路径); 本模块提供跨消费者共享的读取面 — JSONL 装载经
``threshold_trigger.load_trigger_ledger`` 单一实现 (损坏行 advisory 跳过,
日期升序), 连亮计数为本族字段语义。两族账本文件互不混写: 强度族
``threshold_trigger_ledger.jsonl`` 键空间 (condition_1/2/3) 与日层族
``signal_day_cohort_trigger_ledger.jsonl`` 键空间 (strong_bucket /
mid_buckets) 独立演化, 读取侧互不解读对方记录。

诚实边界 (与 threshold_trigger 同纪律):
- 连亮多少次才算稳定 (阈值 K) 属 owner 预注册范围 — 本模块只计数不判定;
- 账本缺失/损坏行 advisory 跳过 (诊断面语义), 不假装有判定记录;
- 条件/合取的判定语义 (lit/armed) 由落账侧冻结, 读取侧不重推导 — 账本里
  是什么就披露什么 (与『配置不是权限』纪律一致: 披露 ≠ 任何行为改变)。
"""

from __future__ import annotations

from pathlib import Path

from src.screening.offensive.threshold_trigger import (
    condition_lit,
    load_trigger_ledger,
)

COHORT_TRIGGER_LEDGER_PATH = Path(
    "data/reports/signal_day_cohort_trigger_ledger.jsonl"
)


def load_cohort_trigger_ledger(
    ledger_path: Path | str | None = None,
) -> list[dict]:
    """读日层 cohort 触发器账本 (threshold_trigger.load_trigger_ledger
    单一装载实现, 独立默认路径)。损坏行 advisory 跳过; 按日期升序。"""
    path = (
        Path(ledger_path) if ledger_path is not None
        else COHORT_TRIGGER_LEDGER_PATH
    )
    return load_trigger_ledger(path)


def cohort_trigger_stability(records: list[dict]) -> dict[str, object]:
    """日层 cohort 触发器连亮计数 (R126 Op1; 语义镜像
    threshold_trigger.trigger_stability, 字段为本族命名):

    ``strong_bucket_streak`` / ``mid_buckets_streak`` / ``conjunction_streak``
    = **最新锚定**连亮 (从最新记录向前数, 未点亮/未判定/缺键断链 — 保守:
    未知不延长连亮); ``max_conjunction_streak`` = **全历史**最大连续武装段
    (独立正向扫描, 断链不吞历史 — R85 Op2 修复语义)。

    本族账本自 R126 起积累, 无旧形态兼容负担; 记录缺键 (手工构造/未来
    字段演化) 一律按未点亮断链。R126 Op2 形状守卫: 行内条件值
    (strong_bucket/mid_buckets) 非 dict 形态 (手编账本/损坏写入/形态演化)
    与缺键同语义 — 断链 + last_lit None (advisory), 绝不让毒化行以裸
    AttributeError 炸掉消费面 (R115 Op1 家族纪律: 证据面损坏不得阻断
    披露/生产面); R127 Op2 起守卫经 ``condition_lit`` 单一实现委托。
    只计数不判定 — 『稳定』阈值属 owner。
    """
    dates = [str(r.get("date")) for r in records]
    out: dict[str, object] = {
        "records": len(records),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "strong_bucket_streak": 0,
        "strong_bucket_last_lit": None,
        "mid_buckets_streak": 0,
        "mid_buckets_last_lit": None,
        "conjunction_streak": 0,
        "conjunction_last_armed": None,
        "max_conjunction_streak": 0,
    }
    if not records:
        return out

    latest = records[-1]
    # R127 Op2: 形状守卫委托 threshold_trigger.condition_lit 单一实现
    # (R126 Op2 本模块私有 _lit 的语义逐字节保留, 双实现收敛)。
    out["strong_bucket_last_lit"] = condition_lit(latest, "strong_bucket")
    out["mid_buckets_last_lit"] = condition_lit(latest, "mid_buckets")
    out["conjunction_last_armed"] = latest.get("conjunction_armed")
    run_c1 = run_c2 = run_and = True
    for rec in reversed(records):
        lit1 = condition_lit(rec, "strong_bucket") is True
        lit2 = condition_lit(rec, "mid_buckets") is True
        armed = rec.get("conjunction_armed") is True
        if run_c1 and lit1:
            out["strong_bucket_streak"] = int(out["strong_bucket_streak"]) + 1
        else:
            run_c1 = False
        if run_c2 and lit2:
            out["mid_buckets_streak"] = int(out["mid_buckets_streak"]) + 1
        else:
            run_c2 = False
        if run_and and armed:
            out["conjunction_streak"] = int(out["conjunction_streak"]) + 1
        else:
            run_and = False
    # 全历史最大武装段: 独立正向扫描, 与最新锚定循环解耦 (R85 Op2 语义)
    historical_max = 0
    current_run = 0
    for rec in records:
        if rec.get("conjunction_armed") is True:
            current_run += 1
            historical_max = max(historical_max, current_run)
        else:
            current_run = 0
    out["max_conjunction_streak"] = historical_max
    return out


__all__ = [
    "COHORT_TRIGGER_LEDGER_PATH",
    "load_cohort_trigger_ledger",
    "cohort_trigger_stability",
]
