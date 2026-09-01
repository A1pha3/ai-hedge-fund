"""执行面缺口披露 (R92 Op3) — gap 判别证据到操作员执行视图的唯一通路。

R92 Op1/Op2 把 T+1 开盘缺口 (gap_t1_open) 的判别证据机制化进诊断报告:
高开 (>5%) 子集期望显著为负且罚分跨半方向稳定 — 而缺口在 9:25 竞价即可
观测, 恰是该证据发挥作用的执行时点。本模块提供:

1. gap 分桶常量与 ``gap_bucket`` 纯函数的单一定义家 (scripts/
   winrate_payoff_decomposition.py 从这里导入, 消除双定义漂移面);
2. ``gap_execution_reference`` — 从最新分解报告 JSON 只读聚合执行面参考
   (高开/低开两侧 n 加权池化 E + split-half 稳定性 + 证据日期)。

纪律: 只读诊断披露, 绝不改变计划创建/评分/仓位/退出 (披露不是行为改变,
镜像 R85 触发器状态行); 报告缺失/损坏/旧形态一律 fail-open 返回 None —
不假装有证据, 也不因诊断面缺失阻断交易流程。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

# 分桶边界预注册于 2026-09-01 (R92 Op1, 探索性 in-sample; 任何政策使用 =
# owner 决策 + 新数据前向验证)。左闭右开, 与 strength_bucket 同侧。
GAP_BUCKETS: tuple[tuple[float, str], ...] = (
    (-0.05, "<-5%"),
    (0.0, "-5~0"),
    (0.02, "0~2%"),
    (0.05, "2~5%"),
    (0.10, "5~10%"),
)
GAP_TOP_BUCKET = ">10%"  # ≥ 0.10 (末界右闭到无穷)
ALL_GAP_BUCKETS: tuple[str, ...] = tuple(lbl for _, lbl in GAP_BUCKETS) + (GAP_TOP_BUCKET,)
# 桶内条件判别的「高开」阈值 — 5~10% 桶下界 (R92 Op1/Op2 同源)
GAP_HIGH_THRESHOLD = 0.05
# 高开侧 = 阈值之上的桶 (池化披露用); 低开侧 = 其余非空桶
_HIGH_GAP_BUCKETS = ("5~10%", GAP_TOP_BUCKET)

_REPORT_GLOB = "winrate_payoff_decomposition_*.json"


def gap_bucket(gap: float | None) -> str:
    """T+1 开盘缺口分桶 — 左闭右开, 缺失诚实 unknown (不假装知道)。"""
    if gap is None or (isinstance(gap, float) and math.isnan(gap)):
        return "unknown"
    g = float(gap)
    for bound, label in GAP_BUCKETS:
        if g < bound:
            return label
    return GAP_TOP_BUCKET


def gap_execution_reference(
    reports_dir: str | Path = Path("data/reports"),
) -> dict[str, object] | None:
    """从最新分解报告聚合执行面缺口参考; 证据不可得 → None (fail-open)。

    聚合口径 (与报告 gap_anatomy 同源): 高开侧 = 5~10% ∪ >10% 两桶的 n
    加权池化期望 (Σn·E/Σn), 低开侧 = 其余非空桶; n 为 0 的桶跳过, 任一
    侧无样本 → None (不渲染半边缺失的参考)。split_stable = split-half
    可判定桶方向全一致 (R15 判据镜像; False 时操作员行如实措辞)。
    """
    directory = Path(reports_dir)
    try:
        candidates = sorted(directory.glob(_REPORT_GLOB))
    except OSError:
        return None
    if not candidates:
        return None
    path = candidates[-1]  # 文件名内嵌 YYYYMMDD, 字典序 = 时间序
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    universes = payload.get("universes") if isinstance(payload, dict) else None
    aligned = universes.get("production_aligned") if isinstance(universes, dict) else None
    gap = aligned.get("gap_anatomy") if isinstance(aligned, dict) else None
    if not isinstance(gap, dict) or gap.get("available") is False:
        return None
    buckets = gap.get("buckets")
    if not isinstance(buckets, list):
        return None
    hi_n = hi_we = lo_n = lo_we = 0.0
    for cell in buckets:
        if not isinstance(cell, dict):
            continue
        n = cell.get("n")
        e = cell.get("expectancy")
        if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
            continue
        if not isinstance(e, (int, float)) or isinstance(e, bool):
            continue
        if cell.get("bucket") in _HIGH_GAP_BUCKETS:
            hi_n += n
            hi_we += n * e
        else:
            lo_n += n
            lo_we += n * e
    if hi_n == 0 or lo_n == 0:
        return None
    split = gap.get("split_half")
    split_stable: bool | None = None
    if isinstance(split, dict):
        judgable = split.get("judgable_count")
        consistent = split.get("consistent_count")
        if isinstance(judgable, int) and isinstance(consistent, int) and judgable > 0:
            split_stable = consistent == judgable
    total_n = None
    horizons = aligned.get("horizons")
    if isinstance(horizons, dict):
        rows = horizons.get("t10")
        if isinstance(rows, list):
            all_row = next((r for r in rows if isinstance(r, dict) and r.get("group") == "ALL"), None)
            if all_row is not None and isinstance(all_row.get("n"), int):
                total_n = all_row["n"]
    return {
        "evidence_date": path.stem.rsplit("_", 1)[-1],
        "n_hi": int(hi_n),
        "e_hi": hi_we / hi_n,
        "n_lo": int(lo_n),
        "e_lo": lo_we / lo_n,
        "split_stable": split_stable,
        "total_n": total_n,
    }
