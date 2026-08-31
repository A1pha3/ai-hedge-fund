"""court 全候选胜率×赔率分解诊断 (只读, 2026-08-22, 第十轮).

背景: BTST 现行先验是全局常数 (court 生产对齐重校准: 净 E=+0.56%/
胜率 46.45%/CI90 [-1.30%,+2.39%] 跨 0) — 胜率与赔率被平均化掩盖了
条件化结构。本工具把 expectancy = p·W − (1−p)·L 做恒等分解:

    ΔE(组 vs 全体) = 胜率贡献 + 赔付贡献   (精确恒等, 无残差)
    胜率贡献 = (p_g − p_b)·(W_b + |L_b|)
    赔付贡献 = p_g·(W_g − W_b) − (1−p_g)·(|L_g| − |L_b|)

回答 "edge 是胜率驱动还是赔付驱动、集中在哪个 regime/强度桶" —
是强度阈值重校准 (panel 已见 0.50-0.60 桶反向) 与 Kelly 先验条件化
的共同地基。

预注册纪律 (先于数据):
- 证据宇宙 = court 全候选执行口径 (含退市者; 宪法 #2: 胜率/赔率只作
  诊断, 绝不替代组合路径证据; 陷阱 19: 不用 journal 成交子集);
- 净收益 = gross − (2×30bps + 5bps)/1e4, 与 btst_court_views.net_ret
  同式 (往返 0.65%);
- 聚类 CI: 按信号日聚类池化 bootstrap (镜像 btst_court_views 修复后
  口径 — 重采样天、池化事件后取逐事件均值, 固定种子可复现);
- 每格 n<30 → 只披露不给判定 (cluster_ci 为 None);
- 无亏损组 payoff 未定义 → None, 不给 inf;
- 本工具是诊断, 不是参数变更提案 — 任何阈值/先验/仓位调整 = 策略
  行为变化 = 新证据世代 (owner 决策)。

写入: data/reports/winrate_payoff_decomposition_YYYYMMDD.{md,json} +
data/reports/threshold_trigger_ledger.jsonl (R81 起逐刷新判定快照,
R84 起绑定 court 身份并走数据前进门)。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from src.screening.offensive.threshold_trigger import (  # noqa: E402
    load_trigger_ledger,
    trigger_stability,
)

COURT_TABLE = Path("data/research/btst_court/event_tables/event_table_v1.csv.gz")
TABLE_DIR = COURT_TABLE.parent  # manifest_v1.json 同目录 — 判定绑定的身份源
REPORT_DIR = Path("data/reports")

SLIPPAGE_BPS = 30.0
SELL_STAMP_BPS = 5.0
ROUNDTRIP_COST = (2 * SLIPPAGE_BPS + SELL_STAMP_BPS) / 1e4  # 0.65%
MIN_CELL_N = 30  # 与 panel_health_check / panel_signal_decomposition 一致
N_BOOT = 10_000
BOOT_SEED = 20260822  # 每次调用新建 seeded RNG — 可复现与进程历史/行序无关 (R13)
PRIMARY_HORIZON = 10  # BTST 固定合约
TRIGGER_LEDGER_PATH = Path("data/reports/threshold_trigger_ledger.jsonl")
CONTRAST_HORIZONS = (5,)
# 预注册阈值触发器判定门槛 (AGENTS.md 项1; R10/R77 判定纪律同款)
THRESHOLD_TRIGGER_MIN_N = MIN_CELL_N
THRESHOLD_TRIGGER_ANCHOR = "production_aligned/t10"

STRENGTH_BUCKETS: tuple[tuple[float, str], ...] = (
    (0.50, "0.50-0.60"),
    (0.60, "0.60-0.70"),
    (0.70, "≥0.70"),
)
# 全桶序 (含 <0.50 与 unknown) — 分组/切片视图共用的单一序, 防两侧漂移
ALL_STRENGTH_BUCKETS: tuple[str, ...] = ("<0.50", "0.50-0.60", "0.60-0.70", "≥0.70", "unknown")


def production_aligned(ev) -> "pd.DataFrame":
    """生产对齐宇宙 — 复用 review_btst_prior_court 单一实现 (防口径漂移)。

    candidate_universe (fillable & !gate_blocked & ret 非空) 再排除
    degraded/ST/行业缺失/排除名单/price<3; 过滤列缺失 = 口径理解错误,
    fail-closed 不静默当作不过滤 (镜像 review 纪律)。
    """
    import sys as _sys
    _scripts = str(Path(__file__).resolve().parent)
    if _scripts not in _sys.path:
        _sys.path.insert(0, _scripts)
    from review_btst_prior_court import (  # noqa: E402
        PRODUCTION_EXCLUDE_COLS,
        candidate_universe,
    )

    required = ["fillable", "gate_blocked", "price_ge_3", *PRODUCTION_EXCLUDE_COLS]
    missing = [c for c in required if c not in ev.columns]
    if missing:
        raise SystemExit(f"court 事件表缺少生产过滤列: {sorted(missing)}")
    universe = candidate_universe(ev)
    excluded_any = universe[list(PRODUCTION_EXCLUDE_COLS)].any(axis=1) | (
        universe["price_ge_3"] != True  # noqa: E712
    )
    return universe.loc[~excluded_any].copy()


def net_returns(gross: list[float | None]) -> list[float | None]:
    """gross → 净收益 (None 透传; 与 btst_court_views.net_ret 同式)。"""
    return [
        None if g is None or (isinstance(g, float) and math.isnan(g))
        else g - ROUNDTRIP_COST
        for g in gross
    ]


def strength_bucket(strength: float | None) -> str:
    """0.50/0.60/0.70 左闭右开 (与 panel_signal_decomposition 同侧)。"""
    if strength is None or (isinstance(strength, float) and math.isnan(strength)):
        return "unknown"
    if strength < 0.50:
        return "<0.50"
    if strength < 0.60:
        return "0.50-0.60"
    if strength < 0.70:
        return "0.60-0.70"
    return "≥0.70"


def win_loss_stats(
    rets: list[float],
    days: list[str] | None = None,
) -> dict[str, object]:
    """n/胜率/avg_win/avg_loss/payoff/expectancy + (n≥MIN_CELL_N) 聚类 CI 下界。

    expectancy 是逐事件均值的恒等重写 (p·W − (1−p)·L); 恰 0 净收益记
    负侧 (保守)。cluster_ci_low_90 只在样本足够时给出, 否则 None。
    """
    n = len(rets)
    if n == 0:
        return {
            "n": 0, "wins": 0, "winrate": None, "avg_win": None,
            "avg_loss": None, "payoff": None, "expectancy": None,
            "cluster_ci_low_90": None,
        }
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    p = len(wins) / n
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0  # 负值或 0(无亏损)
    payoff = (avg_win / abs(avg_loss)) if (losses and avg_loss < 0) else None
    stats: dict[str, object] = {
        "n": n,
        "wins": len(wins),
        "winrate": p,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff": payoff,
        "expectancy": p * avg_win + (1 - p) * avg_loss,
        "cluster_ci_low_90": None,
    }
    if days is not None and n >= MIN_CELL_N and len(set(days)) >= 2:
        stats["cluster_ci_low_90"] = cluster_boot_ci_low(rets, days)
    return stats


def cluster_boot_ci_low(
    rets: list[float],
    days: list[str],
    ci: float = 0.90,
    n_boot: int = N_BOOT,
) -> float:
    """按信号日聚类池化 bootstrap (镜像 btst_court_views 修复后口径:
    重采样天 → 池化被抽中天的全部事件 → 逐事件均值)。

    每次调用以 BOOT_SEED 新建 RNG — 同输入恒同输出, 与进程内调用历史、
    行序、并行的其它调用全部无关 (R13 修复: 模块级全局 RNG 曾使同进程
    第二次调用 CI 漂移, "固定种子可复现"承诺只对全新进程成立)。
    """
    rng = np.random.default_rng(BOOT_SEED)
    by_day: dict[str, list[float]] = {}
    for r, d in zip(rets, days):
        by_day.setdefault(d, []).append(r)
    pools = [np.asarray(v) for v in by_day.values()]
    k = len(pools)
    means = np.empty(n_boot)
    for i in range(n_boot):
        pick = rng.integers(0, k, k)
        means[i] = np.concatenate([pools[j] for j in pick]).mean()
    return float(np.quantile(means, 1 - ci))


def attribution(group: dict[str, object], base: dict[str, object]) -> dict[str, float]:
    """ΔE 的精确恒等分解: 胜率贡献 + 赔付贡献 == ΔE (无残差)。

    base 需含非 None 的 winrate/avg_win/avg_loss (基准=全体)。全胜/全负
    基准 (avg_loss=0 或 payoff None) 下恒等式仍成立 — 分解用 avg_win/
    avg_loss 本体, 不用 payoff 比。
    """
    p_g, p_b = float(group["winrate"]), float(base["winrate"])
    w_g, w_b = float(group["avg_win"]), float(base["avg_win"])
    l_g, l_b = float(group["avg_loss"]), float(base["avg_loss"])
    winrate_contrib = (p_g - p_b) * (w_b + abs(l_b))
    payoff_contrib = p_g * (w_g - w_b) - (1 - p_g) * (abs(l_g) - abs(l_b))
    return {
        "delta_expectancy": float(group["expectancy"]) - float(base["expectancy"]),
        "winrate_contribution": winrate_contrib,
        "payoff_contribution": payoff_contrib,
    }


def _group_rows(
    df: pd.DataFrame, horizon: int
) -> list[tuple[str, pd.DataFrame]]:
    """主分组面: 全体 / regime / 强度桶 / regime×强度。"""
    ret_col = f"net_ret_t{horizon}"
    valid = df[df[ret_col].notna()]
    out: list[tuple[str, pd.DataFrame]] = [("ALL", valid)]
    for regime in sorted(valid["regime"].dropna().unique()):
        out.append((f"regime={regime}", valid[valid["regime"] == regime]))
    for bucket in ALL_STRENGTH_BUCKETS:
        sub = valid[valid["strength_bucket"] == bucket]
        if len(sub):
            out.append((f"strength={bucket}", sub))
    for regime in sorted(valid["regime"].dropna().unique()):
        for bucket in ("0.50-0.60", "0.60-0.70", "≥0.70"):
            sub = valid[(valid["regime"] == regime) & (valid["strength_bucket"] == bucket)]
            if len(sub):
                out.append((f"{regime}×{bucket}", sub))
    return out


def slice_bucket_stability(u: "pd.DataFrame") -> list[dict[str, object]]:
    """预注册半年度切片 × 强度桶稳定性 (t10 主口径)。

    动机 (R91 Op1): 触发器判定对窗口敏感 — 窗口前扩 (含 2025H1) 使条件①
    从 lit (CI90 +0.23%) 翻转为未点亮 (−0.46%) — 全窗口单点统计无法区分
    『结构性 edge』与『单段驱动』; 本视图把触发器锚定分组 (强度桶) 逐
    预注册切片展开。每格 win_loss_stats (净口径): 小样本格 CI 诚实 None
    (n<MIN_CELL_N 内建门槛), 空格 n=0 全 None, 强度缺失行诚实落 unknown 桶。

    切片划分/越界 fail-closed 守卫复用 review_btst_prior_court.slice_partitions
    单一实现 (防口径漂移); 净收益为 None 的行不入格 (镜像 _group_rows 纪律)。
    """
    import sys as _sys
    _scripts = str(Path(__file__).resolve().parent)
    if _scripts not in _sys.path:
        _sys.path.insert(0, _scripts)
    from review_btst_prior_court import slice_partitions

    work = u.copy()
    work["net_ret_t10"] = net_returns(work["gross_ret_t10"].tolist())
    work["strength_bucket"] = work["trigger_strength"].map(strength_bucket)
    work = work[work["net_ret_t10"].notna()]
    out: list[dict[str, object]] = []
    for label, lo, hi, m in slice_partitions(work):
        cells: list[dict[str, object]] = []
        for bucket in ALL_STRENGTH_BUCKETS:
            cell = m[m["strength_bucket"] == bucket]
            cells.append({
                "bucket": bucket,
                **win_loss_stats(
                    cell["net_ret_t10"].tolist(),
                    cell["signal_date"].astype(str).tolist(),
                ),
            })
        out.append({"slice": label, "range": f"{lo}..{hi}", "buckets": cells})
    return out


def decompose(
    df: pd.DataFrame,
    universes: tuple[str, ...] = ("all_candidates", "production_aligned"),
) -> dict[str, object]:
    """对每个宇宙 × 每个 horizon 产出分组表 + 相对该宇宙全体的归因分解。

    双口径: all_candidates (全部可配对候选) 与 production_aligned (生产
    可计划过滤链) — 两者的 E 不可混引 (先验 +0.56% 是生产对齐口径)。
    """
    frames = {"all_candidates": df}
    if "production_aligned" in universes:
        frames["production_aligned"] = production_aligned(df)
    payload: dict[str, object] = {
        "roundtrip_cost": ROUNDTRIP_COST,
        "min_cell_n": MIN_CELL_N,
        "universes": {},
        "horizons": {},  # 兼容旧键: 默认宇宙的 horizons 平铺
    }
    for universe_name, frame in frames.items():
        if universe_name not in universes:
            continue
        uni: dict[str, object] = {"horizons": {}}
        for horizon in (PRIMARY_HORIZON, *CONTRAST_HORIZONS):
            work = frame.copy()
            work[f"net_ret_t{horizon}"] = net_returns(
                work[f"gross_ret_t{horizon}"].tolist()
            )
            work["strength_bucket"] = work["trigger_strength"].map(strength_bucket)
            rows = []
            base_stats: dict[str, object] | None = None
            for label, sub in _group_rows(work, horizon):
                rets = sub[f"net_ret_t{horizon}"].tolist()
                days = sub["signal_date"].astype(str).tolist()
                stats = win_loss_stats(rets, days)
                entry = {"group": label, **stats}
                if label == "ALL":
                    base_stats = stats
                rows.append(entry)
            assert base_stats is not None
            for entry in rows:
                if entry["n"] and entry["group"] != "ALL":
                    entry["attribution_vs_all"] = attribution(entry, base_stats)
                else:
                    entry["attribution_vs_all"] = None
            uni["horizons"][f"t{horizon}"] = rows
        uni["slice_bucket_stability"] = slice_bucket_stability(frame)
        payload["universes"][universe_name] = uni
        if universe_name == "all_candidates":
            payload["horizons"] = uni["horizons"]
    return payload


def _fmt(v: object, pct: bool = True) -> str:
    if v is None:
        return "—"
    if isinstance(v, (int,)) and not isinstance(v, bool):
        return str(v)
    x = float(v)
    return f"{x:+.2%}" if pct else f"{x:.2f}"


def threshold_trigger_status(
    rows: list[dict[str, object]],
    *,
    min_n: int = THRESHOLD_TRIGGER_MIN_N,
) -> dict[str, object]:
    """预注册阈值上调触发器的机械判定面 (AGENTS.md 项1, R77 Op3 判定表自动化)。

    锚定 production_aligned / T+10 (固定合约口径) 分组行, 恒等复现 R77 Op3
    的人工判定:

      条件①  strength=≥0.70     n≥min_n 且净口径聚类 CI90 下界 > 0
      条件②  strength=0.50-0.60  n≥min_n 且净期望 < 0

    合取 (①且②) 点亮 = 具备启动阈值上调正式评估的资格 (owner 决策 +
    预注册; 本工具只判定不提案)。n<min_n / 桶行缺失 / 统计缺失 = 未判定 =
    恒不点亮 (保守: 未知不驱动参数变更)。『稳定越零』是跨刷新性质 —
    单次刷新只报告本次状态, 稳定性由连续多次刷新的逐次记录累积。
    """
    by_group = {str(r.get("group")): r for r in rows}

    def _condition(group: str, *, stat_key: str, lit_when) -> dict[str, object]:
        row = by_group.get(group)
        if row is None:
            return {"lit": False, "judged": False, "n": None, "stat": None,
                    "reason": f"桶行缺失 ({group}) — 未判定, 恒不点亮"}
        n = row.get("n")
        stat = row.get(stat_key)
        if not isinstance(n, int) or n < min_n:
            return {"lit": False, "judged": False, "n": n, "stat": stat,
                    "reason": f"n={n} < {min_n} — 只披露不判定 (R10)"}
        if not isinstance(stat, (int, float)) or isinstance(stat, bool):
            return {"lit": False, "judged": False, "n": n, "stat": stat,
                    "reason": f"{stat_key} 缺失 (样本不足) — 未判定, 恒不点亮"}
        lit = lit_when(float(stat))
        return {
            "lit": lit,
            "judged": True,
            "n": n,
            "stat": stat,
            "reason": (
                f"{stat_key}={stat:+.4f} — {'点亮' if lit else '未点亮'}"
            ),
        }

    c1 = _condition(
        "strength=≥0.70", stat_key="cluster_ci_low_90", lit_when=lambda ci: ci > 0
    )
    c2 = _condition(
        "strength=0.50-0.60", stat_key="expectancy", lit_when=lambda e: e < 0
    )
    armed = bool(c1["lit"]) and bool(c2["lit"])
    if armed:
        verdict = "合取点亮 — 满足启动阈值上调正式评估的资格 (owner 决策 + 预注册; 本工具不提案)"
    elif c1["lit"]:
        verdict = "条件①点亮, 条件②未点亮 — 合取不成立, 阈值 0.50 维持 (条件②正是防止砍掉正期望桶)"
    elif c2["lit"]:
        verdict = "条件②点亮, 条件①未点亮 — 合取不成立, 阈值 0.50 维持"
    else:
        verdict = "两条件均未点亮 — 阈值 0.50 维持"
    return {
        "rule": (
            "预注册触发器 (AGENTS.md 项1): ①≥0.70 桶净口径 CI90 下界>0 且 "
            "②0.50-0.60 桶净期望<0 (均需 n≥min_n) — 合取点亮才启动阈值上调"
            "正式评估; 稳定性由连续多次刷新的逐次记录累积, 单次刷新只报告本次状态"
        ),
        "anchor": THRESHOLD_TRIGGER_ANCHOR,
        "min_n": min_n,
        "condition_1_strong_bucket_ci_above_zero": c1,
        "condition_2_mid_bucket_expectancy_negative": c2,
        "conjunction_armed": armed,
        "verdict": verdict,
    }


def attach_threshold_trigger(
    payload: dict[str, object],
    *,
    min_n: int = THRESHOLD_TRIGGER_MIN_N,
) -> dict[str, object]:
    """把触发器判定挂到 payload (production_aligned 缺席时 no-op)。"""
    aligned = (payload.get("universes") or {}).get("production_aligned")
    if not aligned:
        return payload
    rows = aligned["horizons"].get("t10", [])  # type: ignore[union-attr]
    payload["threshold_trigger"] = threshold_trigger_status(rows, min_n=min_n)
    return payload


def court_binding(court_table: Path, rows: int) -> dict[str, object]:
    """court 数据状态身份 (manifest 身份字段 + 事件表行数 + 内容摘要)。

    账本每条判定快照绑定该身份: 触发器『稳定越零』的语义是同一谓词在
    不断前进的数据上持续成立 — 同一份数据反复判定不产生新证据。
    manifest 缺失/损坏 → 身份字段 None (不假装知道), 行数来自本次实读表。

    content_digest (R90 Op2): 事件表 canonical CSV 序列化的 sha256。
    built_at 只有日期粒度 — 同日内容修正重建 (如零审计表回填权威宇宙后
    重建, 2026-09-01 实例) 的旧身份字段全同, 前进门会把修正判定误判为
    court_not_advanced; 摘要让『同一份数据』在字节级可判定, 内容变则
    摘要变。csv.gz 重写嵌新 mtime, 直接哈希落盘字节会把同内容重建误判
    为前进 — 摘要绑定内容而非文件字节。
    universe_audit_complete: manifest 宇宙审计覆盖闭合
    (days_checked + empty_days == window.sessions) → True; 键全在但不
    闭合 → False; 键缺失/畸形/manifest 损坏 → None (旧形态无 empty_days
    计数, 不假装知道也不推断)。
    """
    built_at = None
    window_start = None
    window_end = None
    fingerprint = None
    window: object = None
    try:
        manifest = json.loads(
            (Path(court_table).parent / "manifest_v1.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        manifest = None
    if isinstance(manifest, dict):
        # 畸形键值逐字段退化 None (R84 Op2-A): 身份来源损坏不假装知道, 也不崩溃
        value = manifest.get("built_at")
        built_at = value if isinstance(value, str) else None
        window = manifest.get("window")
        if isinstance(window, dict):
            value = window.get("end")
            window_end = value if isinstance(value, str) else None
            value = window.get("start")
            window_start = value if isinstance(value, str) else None
        fingerprints = manifest.get("formula_fingerprint")
        if isinstance(fingerprints, dict):
            value = fingerprints.get("btst_breakout_sha256")
            fingerprint = value if isinstance(value, str) else None
    try:
        table_df = pd.read_csv(court_table)
        content_digest = "sha256:" + hashlib.sha256(
            table_df.to_csv(index=False, lineterminator="\n").encode("utf-8")
        ).hexdigest()
    except Exception:  # noqa: BLE001 - 表不可读 → None (不假装知道, 与 manifest 损坏同语义)
        content_digest = None
    universe_audit_complete = None
    audit = manifest.get("universe_audit") if isinstance(manifest, dict) else None
    if isinstance(audit, dict) and isinstance(window, dict):
        days_checked = audit.get("days_checked")
        empty_days = audit.get("empty_days")
        sessions = window.get("sessions")
        if (
            isinstance(days_checked, int)
            and not isinstance(days_checked, bool)
            and isinstance(empty_days, int)
            and not isinstance(empty_days, bool)
            and isinstance(sessions, int)
            and not isinstance(sessions, bool)
        ):
            universe_audit_complete = days_checked + empty_days == sessions
    return {
        "built_at": built_at,
        "window_start": window_start,
        "window_end": window_end,
        "rows": int(rows),
        "formula_fingerprint": fingerprint,
        "content_digest": content_digest,
        "universe_audit_complete": universe_audit_complete,
    }


# load_trigger_ledger / trigger_stability 自 R85 Op1 起单一实现位于
# src.screening.offensive.threshold_trigger (模块头部导入) — 本模块 re-export
# 保持既有消费面 (tests/ 内 from scripts.winrate_payoff_decomposition import)
# 不变; 记录读取面只有一份, 操作员视图与落账面永远同语义。


def record_trigger_status(
    payload: dict[str, object],
    date_str: str,
    ledger_path: Path = TRIGGER_LEDGER_PATH,
    court_binding: dict[str, object] | None = None,
    require_advance: bool = False,
) -> dict[str, object]:
    """把本次刷新的触发器判定快照按日期落账本 (R81 Op2; R84 绑定+前进门)。

    同日刷新替换同日记录: court 表不变则判定数值恒等, 替换即幂等收敛;
    court 表变了则同日晚刷新就是最新事实 (append-only 跨日, 原地更新同日)。
    payload 无 threshold_trigger (如全候选单口径, 无判定锚) → 不写。
    诊断面 fail-open: 写失败打印警告, 不阻断报告生成。

    court_binding = court_binding() 的数据状态身份, 随快照落盘。
    require_advance=True (数据增长耦合路径) 时, 绑定与账本**任一**历史
    记录相同 → skip (R84 Op2-B): 判定是 (数据状态, 规则) 的确定性纯函数,
    同一份数据反复判定不产生新证据 — 单点 (最新) 比对会被数据状态回退
    (备份恢复旧 court, A→B→A) 绕过。旧形态记录无 court 字段 → 门放行
    (不追溯拒绝, 绑定自 R84 起开始积累)。
    已知边界 (成文): 触发规则/锚/min_n 语义变化 = 新证据世代, 须启用新
    账本文件, 不在本门判别范围 (记录内 anchor/min_n 仅供审计比对)。
    """
    trigger = payload.get("threshold_trigger")
    if not isinstance(trigger, dict):
        return {"recorded": False, "reason": "no_threshold_trigger"}
    snapshot = {
        "date": str(date_str),
        "anchor": trigger.get("anchor"),
        "min_n": trigger.get("min_n"),
        "condition_1": {
            k: trigger.get("condition_1_strong_bucket_ci_above_zero", {}).get(k)
            for k in ("lit", "judged", "n", "stat")
        },
        "condition_2": {
            k: trigger.get("condition_2_mid_bucket_expectancy_negative", {}).get(k)
            for k in ("lit", "judged", "n", "stat")
        },
        "conjunction_armed": bool(trigger.get("conjunction_armed")),
    }
    if court_binding is not None:
        # 无绑定不写字段 (与 R81 旧形态逐字一致): 不假装知道数据身份
        snapshot["court"] = dict(court_binding)
    records = load_trigger_ledger(ledger_path)
    if require_advance and court_binding is not None:
        for previous in records:
            if isinstance(previous.get("court"), dict) and previous["court"] == court_binding:
                return {
                    "recorded": False,
                    "reason": "court_not_advanced",
                    "records": len(records),
                }
    records = [r for r in records if r.get("date") != snapshot["date"]]
    records.append(snapshot)
    body = "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in records)
    if body:
        body += "\n"
    import os
    import tempfile

    path = Path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".trigger_ledger_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(body)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as exc:
        print(f"WARNING: 触发器账本写入失败 (诊断面 fail-open): {exc}")
        return {"recorded": False, "reason": "write_failed"}
    return {"recorded": True, "records": len(records)}



def render_md(payload: dict[str, object], date_str: str) -> str:
    L: list[str] = []
    L.append(f"# court 全候选胜率×赔率分解 ({date_str})")
    L.append("")
    L.append("纯诊断 (宪法 #2: 胜率/赔率不替代组合路径证据; 陷阱 19: 证据宇宙 =")
    L.append("court 全候选执行口径, 非 journal 成交子集)。净收益 = 毛收益 −")
    L.append(f"往返 {ROUNDTRIP_COST:.2%} (30bps/边滑点 + 5bps 卖出印花税, 与")
    L.append("btst_court_views 同式)。归因分解为精确恒等: 胜率贡献 + 赔付贡献")
    L.append("= ΔE(组 vs 全体)。聚类 CI 按信号日池化 bootstrap (90% 下界);")
    L.append(f"n<{MIN_CELL_N} 的格子只披露不判定。")
    L.append("")
    universes = payload.get("universes") or {"all_candidates": {"horizons": payload["horizons"]}}
    for uni_name, uni in universes.items():
        subtitle = "全候选 (含 gate 拦截/降级/ST/排除名单)" if uni_name == "all_candidates" else "生产对齐 (gate 放行 & 可成交 & 生产过滤链)"
        L.append(f"### 口径: {uni_name} — {subtitle}")
        L.append("")
        _render_horizons(uni["horizons"], L)
    aligned = (payload.get("universes") or {}).get("production_aligned")
    if aligned:
        _render_slice_bucket_stability(aligned, L)
        t10_all = aligned["horizons"].get("t10", [])
        all_row = next((r for r in t10_all if r["group"] == "ALL"), None)
        if all_row and all_row.get("expectancy") is not None:
            try:
                from src.screening.offensive.known_distributions import (
                    BTST_BREAKOUT_T10,
                )
                prior = BTST_BREAKOUT_T10
                e_dev_pp = abs(all_row["expectancy"] - prior.expected_return) * 100
                w_dev_pp = (all_row["winrate"] - prior.winrate) * 100
                status = "对齐 (±1pp 内)" if e_dev_pp <= 1.0 else "偏离 >1pp — 消费前回 Observe"
                L.append(f"- **先验对齐披露**: 生产对齐 T+10 E={all_row['expectancy']:+.2%} /")
                L.append(f"  胜率={all_row['winrate']:.2%} (n={all_row['n']}) vs")
                L.append(f"  known_distributions.BTST_BREAKOUT_T10")
                L.append(f"  E={prior.expected_return:+.2%}/胜率={prior.winrate:.2%}:")
                L.append(f"  E 偏离 {e_dev_pp:.2f}pp / 胜率偏离 {w_dev_pp:+.2f}pp — {status}。")
            except ImportError:
                L.append("- 先验对齐披露不可用 (known_distributions 导入失败)。")
    trigger = payload.get("threshold_trigger")
    if isinstance(trigger, dict):
        c1 = trigger["condition_1_strong_bucket_ci_above_zero"]
        c2 = trigger["condition_2_mid_bucket_expectancy_negative"]

        def _cond_line(label: str, cond: dict) -> str:
            stat = cond.get("stat")
            n = cond.get("n")
            stat_txt = _fmt(stat) if isinstance(stat, (int, float)) else "—"
            n_txt = str(n) if isinstance(n, int) else "—"
            state = "点亮" if cond.get("lit") else (
                "未判定" if not cond.get("judged") else "未点亮"
            )
            return f"- {label}: **{state}** ({stat_txt}, n={n_txt})"

        L.append("### 阈值触发器状态 (预注册, 只判定不提案)")
        L.append("")
        L.append(_cond_line("条件① ≥0.70 桶净口径 CI90 下界>0", c1))
        L.append(_cond_line("条件② 0.50-0.60 桶净期望<0", c2))
        L.append(f"- **合取: {'点亮' if trigger.get('conjunction_armed') else '未点亮'}** — {trigger.get('verdict')}")
        L.append(f"  (锚 {trigger.get('anchor')})")
        stab = payload.get("threshold_stability")
        if isinstance(stab, dict) and stab.get("records"):
            L.append(
                f"- 稳定计数 (跨刷新逐次记录, 机械化累积): 条件① 连亮 {stab['condition_1_streak']}"
                f"/{stab['records']} · 条件② 连亮 {stab['condition_2_streak']}/{stab['records']}"
                f" · 合取连亮 {stab['conjunction_streak']}/{stab['records']}"
                f" (历史最多合取连亮 {stab['max_conjunction_streak']}; 记录 {stab['first_date']}"
                f"→{stab['last_date']}) — 合取连亮持续出现才具备启动正式评估资格;"
                "稳定阈值 K 属 owner 预注册范围, 本工具只计数不判定"
            )
        else:
            L.append("- 稳定计数: 账本尚无记录 (首刷后逐次累积)")
        L.append("")
    L.append("## 纪律")
    L.append("")
    L.append("- 本报告是诊断证据, 不是参数变更提案; 任何阈值/先验/仓位调整 =")
    L.append("  策略行为变化 = 新证据世代 (owner 决策 + 预注册)。")
    L.append("- 无亏损组 payoff 未定义记 '—'; 恰 0 净收益记负侧 (保守)。")
    L.append("- 复现: `uv run python scripts/winrate_payoff_decomposition.py`")
    L.append(f"  (固定 bootstrap 种子; court 表 {COURT_TABLE})。")
    L.append("")
    return "\n".join(L)


def _render_slice_bucket_stability(uni: dict, L: list[str]) -> None:
    """生产对齐锚定口径的『切片×强度桶稳定性』表 (R91 Op1)。

    触发器条件①锚定全窗口 ≥0.70 桶 — 本表提供其跨切片稳定性证据
    (结构性 vs 单段驱动); 小样本格 CI 缺失 = 只披露不判定 (R10)。
    """
    blocks = uni.get("slice_bucket_stability")
    if not isinstance(blocks, list) or not blocks:
        return
    L.append("### 切片×强度桶稳定性 (净口径, t10 — 触发器锚定分组的跨段视图)")
    L.append("")
    L.append("| 段 | 桶 | n | E | win | CI90 下界 |")
    L.append("|---|---|---|---|---|---|")
    for block in blocks:
        for cell in block["buckets"]:
            n = cell["n"]
            e_txt = _fmt(cell["expectancy"]) if n else "—"
            w_txt = f"{cell['winrate']:.1%}" if n and isinstance(cell["winrate"], (int, float)) else "—"
            ci = cell["cluster_ci_low_90"]
            ci_txt = _fmt(ci) if isinstance(ci, (int, float)) else "—"
            L.append(f"| {block['slice']} | {cell['bucket']} | {n} | {e_txt} | {w_txt} | {ci_txt} |")
    L.append("")
    L.append("触发器条件①锚定的是全窗口 ≥0.70 桶; 本表提供其跨切片稳定性证据")
    L.append("(结构性 edge vs 单段驱动) — 判读属 owner 评估门, 小样本格")
    L.append(f"(n<{MIN_CELL_N}) CI 缺失 = 只披露不判定。")
    L.append("")


def _render_horizons(horizons: dict, L: list[str]) -> None:
    for key, rows in horizons.items():
        L.append(f"## {key}")
        L.append("")
        L.append(
            "| 分组 | n | 胜率 | avg_win | avg_loss | payoff | E | 胜率贡献 | 赔付贡献 | ΔE | CI90下界 |"
        )
        L.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for r in rows:
            attr = r.get("attribution_vs_all")
            if attr:
                wr, pf, de = (
                    _fmt(attr["winrate_contribution"]),
                    _fmt(attr["payoff_contribution"]),
                    _fmt(attr["delta_expectancy"]),
                )
            else:
                wr = pf = de = "—"
            ci = _fmt(r.get("cluster_ci_low_90"))
            L.append(
                f"| {r['group']} | {r['n']} | {_fmt(r['winrate'])} |"
                f" {_fmt(r['avg_win'])} | {_fmt(r['avg_loss'])} |"
                f" {_fmt(r['payoff'], pct=False)} | {_fmt(r['expectancy'])} |"
                f" {wr} | {pf} | {de} | {ci} |"
            )
        L.append("")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--court-table", default=str(COURT_TABLE),
                        help="court 事件表路径 (默认生产 csv.gz; 测试用 fixture)")
    parser.add_argument("--report-dir", default=str(REPORT_DIR),
                        help="报告输出目录 (测试用 tmp)")
    parser.add_argument("--trigger-ledger", default=str(TRIGGER_LEDGER_PATH),
                        help="阈值触发器稳定账本路径 (诊断面, 同日替换幂等)")
    parser.add_argument("--universes", nargs="+",
                        default=["all_candidates", "production_aligned"],
                        choices=["all_candidates", "production_aligned"],
                        help="报告口径 (默认双口径; 生产对齐需完整过滤列)")
    args = parser.parse_args(argv)

    date_str = date.today().strftime("%Y%m%d")
    report_dir = Path(args.report_dir)
    json_path = report_dir / f"winrate_payoff_decomposition_{date_str}.json"
    md_path = report_dir / f"winrate_payoff_decomposition_{date_str}.md"

    court_table = Path(args.court_table)
    if not court_table.exists():
        raise SystemExit(f"court 事件表缺失: {court_table}")
    ev = pd.read_csv(court_table)
    payload = decompose(ev, universes=tuple(args.universes))
    attach_threshold_trigger(payload)
    binding = court_binding(court_table, rows=len(ev))
    record_meta = record_trigger_status(
        payload, date_str, ledger_path=Path(args.trigger_ledger),
        court_binding=binding, require_advance=True,
    )
    payload["threshold_record"] = record_meta
    if record_meta.get("recorded") or record_meta.get("reason") == "court_not_advanced":
        payload["threshold_stability"] = trigger_stability(
            load_trigger_ledger(Path(args.trigger_ledger))
        )
        if record_meta.get("reason") == "court_not_advanced":
            print(
                "court 未前进 (manifest/行数与账本最新记录一致) — 触发器账本不追加"
                " (同数据重判不产生新证据); 报告照常刷新"
            )
    payload["court_rows"] = len(ev)
    payload["court_sessions"] = int(ev["signal_date"].nunique())
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    md_path.write_text(render_md(payload, date_str), encoding="utf-8")
    print(f"written: {md_path} + {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
