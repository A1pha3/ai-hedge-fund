#!/usr/bin/env python3
"""Within-pool factor attribution 就绪检查 (loop 48, c316).

R6 关闭后, 真正的北极星难题是 within-pool RANKING (循环 40-42 结论性发现
"无干净 current-data signal": recommendation_score IC 弱, price 是 pool 放大伪象).
循环 42 想做 factor-level 分析 (score_decomposition 按 per-factor 贡献分高低组算
winrate 倒挂), 但被数据阻塞 — score_decomposition 当时覆盖 0/8025.

c316 发现 blocker 正在解除: _inject_score_decomposition (8a5d54e8) 已上线, 最近
3 天 100% 覆盖, 每天 ~10-12 条. factor_attribution 需 min_n*3=45 条最小样本.

本脚本: 让 owner/autodev 知道数据何时够 + 何时可跑 within-pool factor attribution,
而非干等或反复手动查. 也直接跑 compute_factor_attribution_from_loaded 探针 (即使
insufficient 也显示状态).

纯 helper attribution_readiness: 覆盖率统计 + 就绪判读 + ETA (TDD-covered).
误判就绪会跑出 insufficient 浪费精力; 误判未就绪会干等过久 — 都要避免.
"""
from __future__ import annotations

import json
import logging
import math
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger("within_pool_readiness")


def _is_finite(value: Any) -> bool:
    """A horizon return counts only if it's a finite number (mirrors
    factor_attribution._finite_float)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return False
    return not math.isnan(f) and not math.isinf(f)


def attribution_readiness(
    records: list[dict[str, Any]],
    *,
    min_n: int = 15,
    horizon_field: str = "next_5day_return",
) -> dict[str, Any]:
    """Within-pool factor attribution 是否有足够数据? (pure).

    匹配 factor_attribution.compute_factor_attribution_from_loaded 的过滤: 一条
    record "valid" 当且仅当同时有 score_decomposition (dict) + 有限 horizon return.
    ready 当 valid_count >= min_n*3 (高/中/低 三组各 min_n).

    Returns:
      valid_count: 有效记录数 (sd + horizon return)
      min_required: min_n * 3
      ready: bool
      deficit: max(0, min_required - valid_count)
      factors_present: base_contributions 里出现过的 strategy keys
      accrual_per_day: 最近 7 天 valid 记录的日均 (0 若无近期数据)
      days_to_ready: ceil(deficit / accrual_per_day), 或 None 若 accrual=0, 或 0 若 ready
    """
    # 收集 valid records (镜像 factor_attribution line 83-90 的过滤)
    valid: list[dict[str, Any]] = []
    factors_seen: set[str] = set()
    for rec in records:
        decomp = rec.get("score_decomposition")
        ret = rec.get(horizon_field)
        if decomp is None or not isinstance(decomp, dict):
            continue
        if not _is_finite(ret):
            continue
        valid.append(rec)
        bc = decomp.get("base_contributions")
        if isinstance(bc, dict):
            factors_seen.update(bc.keys())

    min_required = min_n * 3
    valid_count = len(valid)
    ready = valid_count >= min_required
    deficit = max(0, min_required - valid_count)

    # ETA: 最近 7 天的日均 accrual (用 recommended_date)
    date_field = "recommended_date"
    recent_valid_dates = [r.get(date_field) for r in valid if r.get(date_field)]
    if recent_valid_dates:
        # 取最近的 7 个不同日期
        unique_dates = sorted(set(recent_valid_dates), reverse=True)[:7]
        recent_count = sum(1 for d in recent_valid_dates if d in unique_dates)
        accrual_per_day = recent_count / len(unique_dates) if unique_dates else 0.0
    else:
        accrual_per_day = 0.0

    if ready:
        days_to_ready = 0
    elif accrual_per_day > 0:
        days_to_ready = math.ceil(deficit / accrual_per_day)
    else:
        days_to_ready = None  # 无法估算 (停滞)

    return {
        "valid_count": valid_count,
        "min_required": min_required,
        "ready": ready,
        "deficit": deficit,
        "factors_present": sorted(factors_seen),
        "accrual_per_day": round(accrual_per_day, 2),
        "days_to_ready": days_to_ready,
    }


def run(
    tracking_history_path: str = "data/reports/tracking_history.json",
    min_n: int = 15,
    horizon_field: str = "next_5day_return",
) -> None:
    """检查 within-pool factor attribution 就绪状态 + 跑探针."""
    p = Path(tracking_history_path)
    if not p.exists():
        print(f"tracking_history 不存在: {p}")
        return

    raw = json.loads(p.read_text(encoding="utf-8"))
    records = raw.get("records", raw) if isinstance(raw, dict) else raw
    print(f"\nWithin-pool factor attribution 就绪检查")
    print(f"tracking_history: {p} ({len(records)} records)")
    print(f"{'=' * 80}")

    r = attribution_readiness(records, min_n=min_n, horizon_field=horizon_field)
    print(f"horizon: {horizon_field}  min_n: {min_n} (需 {r['min_required']} 条)")
    print(f"有效记录 (sd + {horizon_field}): {r['valid_count']}/{len(records)}")
    # 总体 sd 覆盖 (含无 horizon return 的)
    has_sd = sum(1 for rec in records if rec.get("score_decomposition") is not None)
    pct = 100 * has_sd / max(len(records), 1)
    print(f"score_decomposition 总覆盖: {has_sd}/{len(records)} ({pct:.1f}%)")
    print(f"factors_present: {r['factors_present']}")
    print(f"accrual_per_day (近7日 valid): {r['accrual_per_day']}")
    print()
    if r["ready"]:
        print(f"✅ 就绪! valid={r['valid_count']} >= {r['min_required']} — 可跑 factor attribution.")
    else:
        print(f"⏳ 未就绪: deficit={r['deficit']} (需 {r['min_required']}, 有 {r['valid_count']})")
        if r["days_to_ready"] is not None:
            print(f"   ETA: ~{r['days_to_ready']} 天 (按 {r['accrual_per_day']}/天 valid accrual)")
        else:
            # 二级 blocker 诊断: valid=0 但有 sd 覆盖 → horizon 成熟延迟?
            if has_sd > 0 and r["valid_count"] == 0:
                sd_recs = [rec for rec in records if rec.get("score_decomposition") is not None]
                sd_dates = sorted(set(rec.get("recommended_date", "") for rec in sd_recs if rec.get("recommended_date")))
                latest_sd = sd_dates[-1] if sd_dates else "?"
                print(f"   ⚠️ 二级 blocker: 有 {has_sd} 条 sd 但 0 条 valid (无 {horizon_field})")
                print(f"      → sd 记录最新日期 {latest_sd}; {horizon_field} 需 horizon 个交易日成熟")
                print(f"      → 这是预期的成熟延迟, 非 injection 故障 (injection 已上线, {has_sd} 条证明)")
                # 估算真实 ETA: sd accrual rate + horizon 成熟延迟 + 积累到 min_required
                if sd_dates:
                    sd_accrual = has_sd / len(sd_dates) if sd_dates else 0
                    # 粗略: horizon 天成熟延迟 + (min_required / sd_accrual) 天积累
                    horizon_days = int("".join(c for c in horizon_field if c.isdigit()) or "5")
                    accumulate_days = math.ceil(r["min_required"] / sd_accrual) if sd_accrual > 0 else 0
                    real_eta = horizon_days + accumulate_days
                    print(f"      → sd accrual ~{sd_accrual:.1f}/天; 真实 ETA ≈ {horizon_days}天(成熟) + "
                          f"{accumulate_days}天(积累) ≈ {real_eta}天")
            else:
                print(f"   ETA: 无法估算 (近7日无 accrual — injection 可能停滞, 需排查)")

    print(f"\n{'=' * 80}")
    print("factor attribution 探针 (即使 insufficient 也显示状态):")
    try:
        from src.screening.factor_attribution import (
            compute_factor_attribution_from_loaded,
            render_factor_attribution_line,
        )
        report = compute_factor_attribution_from_loaded(
            records, min_n=min_n, horizon_field=horizon_field
        )
        print(f"  sample_count: {report.sample_count}")
        print(f"  verdict: {report.verdict}")
        line = render_factor_attribution_line(report)
        print(f"  render: {line if line else '(空 — insufficient)'}")
        if report.verdict == "insufficient":
            print(f"\n  → 数据积累中. {r['deficit']} 条后可达最小样本, 可重跑本脚本检查.")
        else:
            print(f"\n  → 有结果! within-pool factor attribution 可用.")
    except Exception as e:
        print(f"  探针失败: {e}")


def main() -> None:
    import argparse
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser(description="Within-pool factor attribution 就绪检查 (c316)")
    ap.add_argument("--tracking-history", default="data/reports/tracking_history.json")
    ap.add_argument("--min-n", type=int, default=15)
    ap.add_argument("--horizon-field", default="next_5day_return")
    a = ap.parse_args()
    run(a.tracking_history, a.min_n, a.horizon_field)


if __name__ == "__main__":
    main()
