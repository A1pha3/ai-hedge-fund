"""强度分量级解剖 — trigger_strength 五分量的事件级证据面 (R152 Op1, R153 Op1 扩区间).

动机: 0.50 门槛与 ≥0.70 阈值锚的全部既有证据都建在 trigger_strength
聚合层 (R141-R149 分解/触发器/近期窗), 「池内哪个分量在做功」从未被
度量 — day_feature_attribution (R133) 是日层聚合 (结论: 无日层特征
具备判别资格), 本工具是事件级分量视图, 与其互补不重叠。

R153 Op1: hi−lo 差从点估计升级为配对 (按日联合重采样) 聚类 bootstrap
双侧区间 (cluster_boot_delta_ci, 单一实现落 winrate_payoff_decomposition)
— 兑现 R152 Op1 docstring 预注册的「配对 bootstrap 属后续 op」。

Observe 期真实 court 数据快查实证 (生产对齐 n=1677 全成熟, T+10,
20260909): ≥0.50 池 (n=1147, E=+1.49%) 内低波分量反向区分
(score<0.5: n=703 E=+2.45% vs ≥0.5: n=444 E=-0.04%), 压缩/量能正向,
board_score 池内反向但 n=75 小样本 — 分量结构与聚合层梯度不同构。

纪律 (宪法 #2):
- 纯诊断披露 — 分量级读数是 owner 阈值/公式权重判读的输入, 不进入
  任何评分/排序/仓位/触发器判定路径; 任何据此的公式变化 = 新证据世代
  owner 决策 (预注册 champion/challenger)。
- 探索性 in-sample: 0.5 分界与三池划分选自同一次观测数据 (镜像 R92
  gap 桶标注), 边界敏感性未做, 单读数不冒充结论。
- 单一实现复用 (R17 收敛纪律): production_aligned/net_returns/
  win_loss_stats (含 per-call seeded 聚类 CI)/MIN_CELL_N/
  court_window_from_events/COURT_TABLE/REPORT_DIR 全部 import 自
  winrate_payoff_decomposition, 本模块零新 RNG 零口径 fork。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd

_SCRIPTS = str(Path(__file__).resolve().parent)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from winrate_payoff_decomposition import (  # noqa: E402
    COURT_TABLE,
    MIN_CELL_N,
    REPORT_DIR,
    cluster_boot_delta_ci,
    court_window_from_events,
    net_returns,
    production_aligned,
    win_loss_stats,
)

# 五分量 (生产序, 镜像 src daily_action._STRENGTH_COMPONENT_LABELS 的键序;
# 中文标签独立维护 — src 是展示面, 本模块是诊断面, 值域语义同源)。
COMPONENTS: tuple[tuple[str, str], ...] = (
    ("board_score", "上市板"),
    ("low_vol_score", "低波"),
    ("squeeze_score", "压缩"),
    ("volume_score", "量能"),
    ("range_score", "振幅"),
)

# 0.5 分界 — 预注册探索性 (选自同一次观测数据, 边界敏感性未做, R92 先例)。
COMPONENT_SPLIT = 0.5
COMPONENT_BUCKETS: tuple[str, ...] = ("<0.50", "≥0.50", "unknown")

# 池划分 (触发器锚同源): all=生产对齐全样本; ge050=生产入场池 (0.50 门槛);
# ge070=阈值上调讨论锚 (≥0.70 触发器条件①桶)。
POOLS: tuple[tuple[str, float], ...] = (
    ("all", float("-inf")),
    ("ge050", 0.50),
    ("ge070", 0.70),
)


def component_bucket(value: object) -> str:
    """分量值 → 桶 (非数值/NaN/inf → unknown, 不虚构归属)。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "unknown"
    if not math.isfinite(float(value)):
        return "unknown"
    return "<0.50" if float(value) < COMPONENT_SPLIT else "≥0.50"


def _pool_frame(work: "pd.DataFrame", floor: float) -> "pd.DataFrame":
    """trigger_strength ≥ floor 的行 (NaN 比较为 False 自然排除)。"""
    if floor == float("-inf"):
        return work
    return work[work["trigger_strength"] >= floor]


def _hi_lo_delta(lo: dict, hi: dict) -> float | None:
    """hi−lo 期望差点估计 (两侧 expectancy 均 None 才 None, 不重算)。"""
    e_lo = lo.get("expectancy")
    e_hi = hi.get("expectancy")
    if e_lo is None or e_hi is None:
        return None
    return e_hi - e_lo


def component_anatomy(
    work: "pd.DataFrame", *, ret_col: str = "net_ret_t10"
) -> dict[str, object]:
    """三池 × 五分量 × 双桶 win_loss_stats 矩阵 (零新口径)。

    每格 (pool, component, bucket) 是独立 win_loss_stats 调用 — 日聚类
    CI 由其内建 n≥MIN_CELL_N 门槛给出, 小样本格诚实 None; unknown 桶
    全量保留 (缺失分量如实显形不剔除)。hi_lo_delta 是点估计;
    hi_lo_delta_ci 是配对 (按日联合重采样) 聚类 bootstrap 双侧区间
    (R153 Op1 — 兑现本函数此前「配对 bootstrap 属后续 op」的预注册),
    双桶 n≥MIN_CELL_N 才给, 否则 None 不冒充; 差值符号判读 (反向分量
    是否可区分于零) 用区间, 点估计只作方向。
    """
    pools: dict[str, object] = {}
    for pool_key, floor in POOLS:
        sub = _pool_frame(work, floor)
        per_component: dict[str, object] = {}
        for comp_key, _label in COMPONENTS:
            buckets: dict[str, object] = {}
            cells: dict[str, "pd.DataFrame"] = {}
            for bucket in COMPONENT_BUCKETS:
                cell = sub[sub[f"_comp_{comp_key}"] == bucket]
                cells[bucket] = cell
                buckets[bucket] = win_loss_stats(
                    cell[ret_col].tolist(),
                    cell["signal_date"].astype(str).tolist(),
                )
            lo_cell, hi_cell = cells["<0.50"], cells["≥0.50"]
            if len(lo_cell) >= MIN_CELL_N and len(hi_cell) >= MIN_CELL_N:
                hi_lo_delta_ci: dict[str, float] | None = cluster_boot_delta_ci(
                    hi_cell[ret_col].tolist(),
                    hi_cell["signal_date"].astype(str).tolist(),
                    lo_cell[ret_col].tolist(),
                    lo_cell["signal_date"].astype(str).tolist(),
                )
            else:
                hi_lo_delta_ci = None
            per_component[comp_key] = {
                "buckets": buckets,
                "hi_lo_delta": _hi_lo_delta(
                    buckets["<0.50"], buckets["≥0.50"]
                ),
                "hi_lo_delta_ci": hi_lo_delta_ci,
            }
        pools[pool_key] = {
            "floor": None if floor == float("-inf") else floor,
            "n": int(len(sub)),
            "components": per_component,
        }
    return pools


def component_split_half(
    work: "pd.DataFrame", *, ret_col: str = "net_ret_t10"
) -> dict[str, object]:
    """逐池逐分量按日序半窗 hi−lo 差的符号一致性 (R133 判据风格)。

    半窗划分镜像 trailing_window (R149 Op1): 有成熟行的信号日全序对分;
    单半内某桶缺 expectancy → 该半 delta None (不冒充); sign_consistent
    仅两半 delta 均 None 才 None, 否则按 (early>0)==(late>0) 判 (恰 0
    归负侧 — 镜像 win_loss_stats 保守侧)。
    """
    valid = work[work[ret_col].notna()].copy()
    all_days = sorted(valid["signal_date"].astype(str).unique())
    if len(all_days) < 2:
        return {"available": False, "reason": "insufficient_days"}
    half = len(all_days) // 2
    day_sets = {
        "early": set(all_days[:half]),
        "late": set(all_days[half:]),
    }
    pools: dict[str, object] = {}
    for pool_key, floor in POOLS:
        sub = _pool_frame(valid, floor)
        per_component: dict[str, object] = {}
        for comp_key, _label in COMPONENTS:
            deltas: dict[str, float | None] = {}
            for label, day_set in day_sets.items():
                cell = sub[sub["signal_date"].astype(str).isin(day_set)]
                lo = win_loss_stats(
                    cell.loc[
                        cell[f"_comp_{comp_key}"] == "<0.50", ret_col
                    ].tolist()
                )
                hi = win_loss_stats(
                    cell.loc[
                        cell[f"_comp_{comp_key}"] == "≥0.50", ret_col
                    ].tolist()
                )
                deltas[label] = _hi_lo_delta(lo, hi)
            early, late = deltas["early"], deltas["late"]
            per_component[comp_key] = {
                "early_delta": early,
                "late_delta": late,
                "sign_consistent": (
                    (early > 0) == (late > 0)
                    if early is not None and late is not None
                    else None
                ),
            }
        pools[pool_key] = per_component
    return {"available": True, "days_early": half, "days_late": len(all_days) - half, "pools": pools}


def analyze(ev: "pd.DataFrame") -> dict[str, object]:
    """事件表 → 完整分量解剖 payload (生产对齐 × T+10 主 horizon)。

    列缺失 = 口径理解错误, SystemExit fail-closed (镜像
    production_aligned 的过滤列纪律 — 静默当作缺失列会渲染全 unknown
    假装分析了)。R152 Op2: 必需列全集 = 五分量 + trigger_strength +
    signal_date + gross_ret_t10 — 缺 core 列时此前经 _pool_frame/
    net_returns/component_split_half 裸 KeyError 逃逸 (PoC 实锤),
    与分量列同入 typed 拒绝。ret 列经 net_returns 统一扣成本。
    """
    required = [
        *(c for c, _ in COMPONENTS),
        "trigger_strength",
        "signal_date",
        "gross_ret_t10",
    ]
    missing = [c for c in required if c not in ev.columns]
    if missing:
        raise SystemExit(f"court 事件表缺少必需列: {missing}")
    universe = production_aligned(ev)
    work = universe.copy()
    work["net_ret_t10"] = net_returns(work["gross_ret_t10"].tolist())
    for comp_key, _label in COMPONENTS:
        work[f"_comp_{comp_key}"] = work[comp_key].map(component_bucket)
    return {
        "available": True,
        "n": int(len(work)),
        "min_cell_n": MIN_CELL_N,
        "component_split": COMPONENT_SPLIT,
        "pools": component_anatomy(work),
        "split_half": component_split_half(work),
    }


def _fmt(v: object, pct: bool = True) -> str:
    """单元格防御渲染 (镜像分解工具 _fmt): 非有限 → '—' 不渲染垃圾。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return "—"
    if not math.isfinite(float(v)):
        return "—"
    return f"{v:+.2%}" if pct else f"{v:.3f}"


def _fmt_count(v: object) -> str:
    """计数格整数渲染 (R152 Op2: 修复前 n 经 _fmt(pct=False) 渲染 '226.000'
    三位小数 — int 计数被 :.3f 浮点格式化, 真实报告实锤)。"""
    if isinstance(v, bool) or not isinstance(v, int):
        return "—"
    return str(v)


def render_md(payload: object) -> str:
    """payload → MD 报告 (fail-open 家族: 缺键/非 dict 零新增字节不崩)。

    纪律句必在 (探索性 in-sample + 宪法 #2); 每格 _fmt 防御渲染。
    """
    if not isinstance(payload, dict) or payload.get("available") is not True:
        return ""
    lines: list[str] = [
        "# 强度分量级解剖 (trigger_strength 五分量, R152)",
        "",
        (
            f"- 宇宙: production_aligned × T+10 净口径, n={payload.get('n', '—')}"
            f" · 0.5 分界 · MIN_CELL_N={payload.get('min_cell_n', '—')}"
        ),
        (
            "- 纪律: 探索性 in-sample (分界与池划分选自同次观测数据), 只披露"
            "不判定 (宪法 #2); 任何据此的公式/阈值变化 = 新证据世代 owner 决策;"
            " hi−lo 差区间是配对 (按日联合重采样) bootstrap 双侧 90% 估计,"
            " 探索性 read-out, 区间证据与各桶 CI90 下界互为侧面。"
        ),
        "",
    ]
    pools = payload.get("pools")
    split = payload.get("split_half")
    split_pools = split.get("pools") if isinstance(split, dict) else None
    labels = {k: lbl for k, lbl in COMPONENTS}
    if isinstance(pools, dict):
        for pool_key, _floor in POOLS:
            pool = pools.get(pool_key)
            if not isinstance(pool, dict):
                continue
            lines.append(f"## 池 {pool_key} (n={pool.get('n', '—')})")
            lines.append("")
            lines.append("| 分量 | <0.50: n / E / CI90下界 | ≥0.50: n / E / CI90下界 | hi−lo | 半窗符号 |")
            lines.append("|---|---|---|---|---|")
            comps = pool.get("components")
            if not isinstance(comps, dict):
                lines.append("| (缺 components 键) | — | — | — | — |")
            else:
                for comp_key, label in COMPONENTS:
                    cell = comps.get(comp_key)
                    if not isinstance(cell, dict):
                        lines.append(f"| {label} | — | — | — | — |")
                        continue
                    buckets = cell.get("buckets")
                    lo = (
                        buckets.get("<0.50", {})
                        if isinstance(buckets, dict)
                        else {}
                    )
                    hi = (
                        buckets.get("≥0.50", {})
                        if isinstance(buckets, dict)
                        else {}
                    )
                    lo = lo if isinstance(lo, dict) else {}
                    hi = hi if isinstance(hi, dict) else {}
                    sign = "—"
                    if isinstance(split_pools, dict):
                        sp = split_pools.get(pool_key)
                        if isinstance(sp, dict):
                            sc = sp.get(comp_key)
                            if isinstance(sc, dict):
                                raw = sc.get("sign_consistent")
                                if raw is True:
                                    sign = "一致"
                                elif raw is False:
                                    sign = "翻转"
                    raw_ci = cell.get("hi_lo_delta_ci")
                    if isinstance(raw_ci, dict):
                        ci_cell = (
                            f"[{_fmt(raw_ci.get('ci_low'))}"
                            f", {_fmt(raw_ci.get('ci_high'))}]"
                        )
                    else:
                        ci_cell = "—"
                    lines.append(
                        f"| {label} ({comp_key}) "
                        f"| {_fmt_count(lo.get('n'))} / {_fmt(lo.get('expectancy'))}"
                        f" / {_fmt(lo.get('cluster_ci_low_90'))} "
                        f"| {_fmt_count(hi.get('n'))} / {_fmt(hi.get('expectancy'))}"
                        f" / {_fmt(hi.get('cluster_ci_low_90'))} "
                        f"| {_fmt(cell.get('hi_lo_delta'))} {ci_cell} | {sign} |"
                    )
            lines.append("")
    return "\n".join(lines)


def _write_report(payload: dict, json_path: Path, md_path: Path) -> None:
    """双产物落盘 — serialize-first + allow_nan=False + typed fail-closed
    (R148 Op1 门挡池主报告面同款失败契约: 序列化失败零部分产物)。
    """
    try:
        body = json.dumps(payload, ensure_ascii=False, indent=1, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"report_not_serializable: {exc}") from exc
    md = render_md(payload)
    try:
        json_path.write_text(body, encoding="utf-8")
        md_path.write_text(md, encoding="utf-8")
    except OSError as exc:
        # 写盘对失败 → best-effort 清除本运行已落盘产物再 typed 退出
        # (R148 Op2 F-a 同款: 不留新 md 配无/旧 json 的半套对)。
        for p in (json_path, md_path):
            try:
                if p.is_file():
                    os.unlink(p)
            except OSError:
                pass
        raise SystemExit(f"report_write_failed: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--court-table", default=str(COURT_TABLE),
                        help="court 事件表路径 (默认生产 csv.gz; 测试用 fixture)")
    parser.add_argument("--report-dir", default=str(REPORT_DIR),
                        help="报告输出目录 (测试用 tmp)")
    parser.add_argument("--date-str", default=None,
                        help="报告日期串 YYYYMMDD (默认今日; 夜刷链传入)")
    args = parser.parse_args(argv)

    date_str = args.date_str or date.today().strftime("%Y%m%d")
    if not (isinstance(date_str, str) and len(date_str) == 8 and date_str.isdigit()):
        raise SystemExit(f"invalid_date_str: {date_str!r}")

    court_table = Path(args.court_table)
    if not court_table.exists():
        raise SystemExit(f"court 事件表缺失: {court_table}")
    ev = pd.read_csv(court_table)
    payload = analyze(ev)
    payload["court_rows"] = len(ev)
    payload["court_sessions"] = int(ev["signal_date"].nunique())
    payload["court_window"] = court_window_from_events(ev)

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / f"strength_component_decomposition_{date_str}.json"
    md_path = report_dir / f"strength_component_decomposition_{date_str}.md"
    _write_report(payload, json_path, md_path)
    print(f"report: {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
