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

import datetime as dt
import json
import math
import re
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
# 文件名日期段形状守卫 (R109 Op2): 『字典序 = 时间序』前提只对 YYYYMMDD
# 命名成立 — glob 同前缀的 backup/editor 杂文件 ('b' > '2' 排在日期之后)
# 会被 sorted[-1] 误当最新报告, PoC 实锤可劫持披露行渲染假证据。
_DATED_SUFFIX_RE = re.compile(r"_(\d{8})$")


def report_filename_date(path: str | Path) -> str | None:
    """报告文件名日期段 (YYYYMMDD) 的单一提取谓词 (R137 Op1)。

    读取体形状守卫与 scripts 侧 typed reason 共用同一定义 — 日期提取逻辑
    漂移会让两侧行为分叉 (一侧拒一侧收)。
    """
    matched = _DATED_SUFFIX_RE.search(Path(path).stem)
    return matched.group(1) if matched else None


def _today() -> "dt.date":
    """本机今日 (可测试缝): 守卫只依赖它做未来判定, 测试可注入。"""
    return dt.date.today()


def latest_decomposition_report(
    reports_dir: str | Path = Path("data/reports"),
) -> tuple[Path, dict] | None:
    """最新分解报告的唯一读取家 (R109 Op2 收敛 gap 参考行与先验漂移行的同族读取)。

    只接受文件名日期段为 \\d{8} 的报告 (形状守卫); 新鲜度 = 日期字典序最大者。
    文件缺失/不可读/非法 JSON/顶层非对象 → None (fail-open, 不假装有证据);
    损坏的最新报告不回退旧报告 — 以 None 示警, 不以陈旧数字冒充当前证据。

    未来日期绊线 (R137 Op1, R136 Op2 登记开放项收口): 选中报告日期晚于今日
    即拒绝 — 合法管道只在当日写报告, 未来日期只能来自手工放置/时钟错乱;
    与损坏同款不回退次新 (目录处于异常状态时静默展示旧证据 = 假冒当前)。
    """
    return _latest_dated_report(reports_dir, _REPORT_GLOB)


def _latest_dated_report(
    reports_dir: str | Path,
    report_glob: str,
) -> tuple[Path, dict] | None:
    """按日期段形状守卫取字典序最新报告 (两读取家共享实现, 防漂移)。"""
    directory = Path(reports_dir)
    try:
        dated = sorted(
            path
            for path in directory.glob(report_glob)
            if report_filename_date(path) is not None
        )
    except OSError:
        return None
    if not dated:
        return None
    path = dated[-1]
    report_date = report_filename_date(path) or ""
    if report_date > _today().strftime("%Y%m%d"):
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return path, payload


_COHORT_REPORT_GLOB = "signal_day_cohort_*.json"

# cohort 规模分桶 (R123 Op1 定义, R125 Op3 上移单一实现家): 左闭右闭日数
# 边界, 显式边界不玩 cut 花活。脚本 (scripts/btst_signal_day_cohort) 与
# 操作员渲染行共用 — 两侧口径不可漂移。
COHORT_BUCKET_EDGES: tuple[tuple[int, int], ...] = (
    (1, 1),
    (2, 3),
    (4, 9),
    (10, 19),
    (20, math.inf),
)
COHORT_BUCKET_LABELS: tuple[str, ...] = ("1", "2-3", "4-9", "10-19", "20+")


def cohort_size_bucket(n_days_members: int) -> str:
    """cohort 规模 (当日事件数) → 分桶标签。

    非整数/非正数 fail-closed (bool 是 int 子类, 显式拒) — 分桶口径由
    构造保证, 绝不静默归桶。
    """
    if not isinstance(n_days_members, int) or isinstance(n_days_members, bool):
        raise TypeError(f"cohort size must be int, got {type(n_days_members).__name__}")
    if n_days_members <= 0:
        raise ValueError(f"cohort size must be positive, got {n_days_members}")
    for (lo, hi), label in zip(COHORT_BUCKET_EDGES, COHORT_BUCKET_LABELS):
        if lo <= n_days_members <= hi:
            return label
    raise ValueError(f"cohort size {n_days_members} outside predefined edges")


def latest_signal_day_cohort_report(
    reports_dir: str | Path = Path("data/reports"),
) -> tuple[Path, dict] | None:
    """最新信号日 cohort 分解报告的唯一读取家 (R125 Op3)。

    与 latest_decomposition_report 同构 (形状守卫/字典序新鲜/损坏 None
    不回退旧报告 — 不以陈旧数字冒充当前证据), 经 _latest_dated_report
    单一实现只换 glob。
    """
    return _latest_dated_report(reports_dir, _COHORT_REPORT_GLOB)


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
    found = latest_decomposition_report(reports_dir)
    if found is None:
        return None
    _path, payload = found
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
        "evidence_date": _path.stem.rsplit("_", 1)[-1],
        "n_hi": int(hi_n),
        "e_hi": hi_we / hi_n,
        "n_lo": int(lo_n),
        "e_lo": lo_we / lo_n,
        "split_stable": split_stable,
        "total_n": total_n,
    }
