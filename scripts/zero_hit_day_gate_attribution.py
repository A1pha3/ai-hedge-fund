"""零 hit 日门槛有效性归因 — R138 开放项① 收口 (纯诊断, 宪法 #2).

第一性原理: R138 Op2 实锤 court 窗口内约 40% 会话日整日零 hit (manifest
zero_hit_days), 事件表对这些日静默归零而机制面不可见 — 『c2/c3/c4 门槛
挡掉的日子是保护 (反事实本会亏) 还是机会成本 (反事实本会赚)』此前无任何
工具度量。该问题是日层 cohort K (唯一合格修复路径, R139 定谳) 决策包的
机制证据: 若 normal regime 内近失候选反事实净期望为负, 现行检测门槛已在
日层保护生产; 若为正, 门槛在付机会成本 — 方向性事实直接进入 owner 两族
K 预注册与日层触发的判读语境。

口径 (全部复用单一实现, 零口径 fork):
  - 候选/历史门槛/detect 重放/反事实事件行 = btst_court_build 同源
    (load_panel/ticker_frame/BtstBreakoutSetup/_build_event), 现行公式
    现行数据 — 本脚本不复制任何条件语义;
  - 门挡集谓词: miss_stage ∈ {c2_*, c3_*, c4_*} (结构门 c0/c1 与涨停形状
    之后的首个失败条件) 全池。**未强度条件化, 这是已知的诚实局限**:
    detect 的强度 ranker 只在全部条件通过后计算, _miss 对 miss 恒返回
    trigger_strength=0.0 (R140 Op2 真实数据实锤, 非『全部 miss 强度 <0.50』
    的证据) — 强度条件化须 fork 公式, 违反单一实现纪律, 不做; 门挡集
    反事实 E 的解读边界 (含未达强度阈值的弱候选) 在报告内成文;
  - 反事实收益 = production_aligned + net_returns 净口径 (t10, 与
    winrate_payoff_decomposition 逐字一致); gate_blocked (crisis/risk_off)
    行随 production_aligned 自然剔除 — normal-only 抉择面;
  - 聚类 CI per-call seeded (R13 纪律), 事件 n < 30 → CI None 只披露。

纪律:
  - 纯诊断 (宪法 #2): 零判定逻辑零行为授权; 任何据此的生产变化 = 策略
    行为变化 = 新证据世代 owner 决策。
  - 重放 hit 披露: manifest 零 hit 日在现行公式重放中出现 hit = 公式/数据
    漂移信号 (R138 divergence 同族), 逐日计数披露, 不混入反事实集。
  - 不成熟 (t10 缺失) 行只计数不入 E — 窗口末端零 hit 日的 T+10 尚未走完,
    绝不以部分窗口冒充完整收益。

用法:
    uv run python scripts/zero_hit_day_gate_attribution.py
    uv run python scripts/zero_hit_day_gate_attribution.py --table-dir PATH --report-dir PATH
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import pandas as pd  # noqa: E402

from _btst_court_common import (  # noqa: E402
    REGIME_GATE_BLOCK,
    TABLE_DIR,
    WINDOW_A_START,
    load_regime_history,
    load_sessions,
)
from winrate_payoff_decomposition import (  # noqa: E402
    MIN_CELL_N,
    REPORT_DIR,
    cluster_boot_ci_low,
    court_binding,
    court_data_state_equal,
    load_trigger_ledger,
    net_returns,
    production_aligned,
)

PRIMARY_HORIZON = 10

# 近失集: 结构门 (c0 数据 / c1 涨停形状) 之后的首个失败条件 — 这些候选已
# 通过可交易形状, 只被资金流/行业/动量条件或数据不足挡下。
NEAR_MISS_STAGES: frozenset[str] = frozenset(
    {
        "c2_flow_missing",
        "c2_flow_below_mean",
        "c3_industry_missing",
        "c3_industry_weak",
        "c4_data_short",
        "c4_runup_exceeded",
    }
)

# 挡入条件族 (c3 = 日层行业/市场状态门, c2 = 日×票资金流门, c4 = 票级动量门)
STAGE_FAMILY: dict[str, str] = {
    "c2_flow_missing": "c2_flow",
    "c2_flow_below_mean": "c2_flow",
    "c3_industry_missing": "c3_industry",
    "c3_industry_weak": "c3_industry",
    "c4_data_short": "c4_runup",
    "c4_runup_exceeded": "c4_runup",
}

FAMILY_ORDER: tuple[str, ...] = ("c3_industry", "c2_flow", "c4_runup", "structural")


def stage_family(stage: str | None) -> str:
    """miss_stage → 挡入条件族; 结构性 miss (c0/c1) 归 structural。"""
    if stage is None:
        return "structural"
    return STAGE_FAMILY.get(stage, "structural")


def dominant_blocked_family(stage_counts: Mapping[str, int]) -> str | None:
    """零 hit 日的主导挡入条件族 (确定性: 计数最大; 平票 → mixed; 空 → None)。

    stage_counts 键是 miss_stage 原始标签 (含结构性); 族内计数聚合后取
    最大。非对称: {c3: 5, c2: 1} → c3_industry, {c3: 3, c2: 3} → mixed。
    """
    family_counts: dict[str, int] = {}
    for stage, n in stage_counts.items():
        if n <= 0:
            continue
        family_counts[stage_family(stage)] = (
            family_counts.get(stage_family(stage), 0) + n
        )
    if not family_counts:
        return None
    best = max(family_counts.values())
    leaders = sorted(f for f, n in family_counts.items() if n == best)
    if len(leaders) > 1:
        return "mixed"
    return leaders[0]


def is_gate_blocked(stage: str | None) -> bool:
    """门挡谓词: 首个失败条件在 c2+ (不论强度 — miss 的 strength 恒 0,
    强度条件化需 fork 公式, 见模块 docstring 局限披露)。"""
    return stage in NEAR_MISS_STAGES


def day_counterfactual_e(net_rets: Sequence[float | None]) -> float | None:
    """日反事实 E = 成熟净收益均值; 无成熟行 → None (绝不冒充 0)。"""
    mature = [float(v) for v in net_rets if v is not None]
    if not mature:
        return None
    return sum(mature) / len(mature)


def summarize_gate_effectiveness(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """跨日聚合 (只披露不判定): 方向计数 + 分层池化 E + 聚类 CI。

    rows = 近失反事实行 [{day, regime, dominant_family, net}]。
    事件 n < 30 → CI None; 空集 → 各聚合 None 不冒充。
    """
    def _pooled(subset: list[dict[str, Any]]) -> dict[str, Any]:
        rets = [r["net"] for r in subset if r["net"] is not None]
        days = [r["day"] for r in subset if r["net"] is not None]
        if not rets:
            return {"events": 0, "e": None, "ci90_low": None, "days": 0}
        e = sum(rets) / len(rets)
        ci = (
            cluster_boot_ci_low(rets, days)
            if len(rets) >= MIN_CELL_N
            else None
        )
        return {
            "events": len(rets),
            "e": e,
            "ci90_low": ci,
            "days": len(set(days)),
        }

    normal = [r for r in rows if r["regime"] not in REGIME_GATE_BLOCK]
    blocked = [r for r in rows if r["regime"] in REGIME_GATE_BLOCK]
    per_day: dict[str, list[float]] = {}
    for r in rows:
        if r["net"] is not None:
            per_day.setdefault(r["day"], []).append(r["net"])
    day_es = [sum(v) / len(v) for v in per_day.values()]
    summary: dict[str, Any] = {
        "events_total": len(rows),
        "events_mature": sum(1 for r in rows if r["net"] is not None),
        "days_with_mature": len(per_day),
        "day_e_distribution": {
            "protective_lt0": sum(1 for e in day_es if e < 0),
            "costly_gt0": sum(1 for e in day_es if e > 0),
            "flat_eq0": sum(1 for e in day_es if e == 0),
        },
        "normal_regime_pooled": _pooled(normal),
        "gate_blocked_pooled": _pooled(blocked),
        "by_dominant_family": {
            fam: _pooled([r for r in rows if r["dominant_family"] == fam])
            for fam in FAMILY_ORDER + ("mixed",)
        },
        # R141 Op1 (R138 开放项① 收口): 行业热度分层 — c3 门自身输入
        # (当日行业涨幅) 三桶 + 每 SW L1 池化; n<MIN_CELL_N CI=None 只披露。
        "by_industry_heat": {
            bucket: _pooled(
                [r for r in rows if _industry_heat_bucket(r.get("industry_day_pct")) == bucket]
            )
            for bucket in HEAT_BUCKETS
        },
        "by_industry": {
            (UNKNOWN_INDUSTRY_KEY if ind is None else ind): _pooled(
                [r for r in rows if r.get("industry") == ind]
            )
            for ind in _sorted_industries(rows)
        },
        # R145 Op1 (R141 日混杂 confound 判读输入做实): 行业日去均值对照 —
        # 同日截面去均值吸收市场日效应, 把『机会成本 vs 市场 β』变成可检验事实。
        "by_industry_day_demeaned": industry_day_demeaned(rows),
    }
    return summary


def _finite_net(value: Any) -> float | None:
    """R145 Op2 F1: 成熟 net 有限性守卫 — NaN/Inf/bool 不成熟 (与 None 同义)。

    NaN/Inf 是浮点管道常见形态 (R141 Op2 NaN 纪律), 静默入均值会把整个
    同日截面变 NaN 波及无辜行业, 且 R143 Op3 起账本写入器 allow_nan=False
    会令落账整体冻结 (PoC 双实锤); bool 是 int 子类按 1.0 参与均值是冒充
    (R142 F2 pin)。与 _pooled (裸 is not None) 的不对称是已登记家族项
    (R143 F3 summary 面 NaN 暴露), 单一实现纪律不在本轮扩大改兄弟面。
    非数值类型 (str 等) 不在本守卫内 — 契约违反 fail-closed 崩溃是诚实行为。
    """
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    net = float(value)
    return net if math.isfinite(net) else None


def industry_day_demeaned(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """行业日去均值对照 (day fixed effects): 同日跨行业相对结构。

    零 hit 日门挡池横截面本身跨行业, 日去均值完全吸收同日共同效应 (市场
    与 T+10 窗口共同因子), 只保留同日内跨行业相对排序 — 『某行业门挡候选
    在同样这些零 hit 日内是否跑赢其他行业门挡候选』与市场日水平无关。
    参与日 = 成熟行 (net 为有限数值, _finite_net 守卫 — R145 Op2 F1)
    跨 ≥2 不同行业的日; 单行业日去均值恒 0, 不冒充信息, 剔除并计数披露。
    行业 None 入 UNKNOWN_INDUSTRY_KEY 哨兵 (R141 Op2 纪律, 行字段不受
    影响 — 本函数只产出聚合); 聚合键序 str 确定性排序 (混合类型键不崩
    — R145 Op2 F3)。CI 复用 cluster_boot_ci_low 按日聚类, n<MIN_CELL_N
    诚实 None。

    构造性语义: 去均值池内跨行业 (事件加权) 合计恒为 0 — 读数是相对排序
    证据, 不是绝对机会成本 (渲染层机制注同义)。
    """
    by_day: dict[str, list[tuple[Any, float]]] = {}
    for r in rows:
        net = _finite_net(r.get("net"))
        if net is None:
            continue
        by_day.setdefault(str(r["day"]), []).append((r.get("industry"), net))
    participating: dict[str, list[tuple[Any, float]]] = {}
    excluded_days = 0
    excluded_events = 0
    for day, items in by_day.items():
        if len({str(ind) for ind, _ in items}) >= 2:
            participating[day] = items
        else:
            excluded_days += 1
            excluded_events += len(items)
    pooled: dict[Any, list[tuple[str, float]]] = {}
    for day, items in participating.items():
        day_mean = sum(net for _, net in items) / len(items)
        for ind, net in items:
            key = UNKNOWN_INDUSTRY_KEY if ind is None else ind
            pooled.setdefault(key, []).append((day, net - day_mean))
    cells: dict[str, dict[str, Any]] = {}
    for key in sorted(pooled, key=str):  # str 键序: 混合类型键确定性 (F3)
        pts = pooled[key]
        rets = [v for _, v in pts]
        days = [d for d, _ in pts]
        cells[key] = {
            "events": len(rets),
            "days": len(set(days)),
            "e": sum(rets) / len(rets),
            "ci90_low": (
                cluster_boot_ci_low(rets, days)
                if len(rets) >= MIN_CELL_N
                else None
            ),
        }
    return {
        "days_participating": len(participating),
        "days_excluded_single_industry": excluded_days,
        "events_excluded_single_industry": excluded_events,
        "by_industry": cells,
    }


HEAT_BUCKETS: tuple[str, ...] = (
    "heat_positive",
    "heat_non_positive",
    "heat_unknown",
)

# R141 Op2: summary/by_industry 的 unknown 行业哨兵键 — None 键会让
# json.dumps(sort_keys=True) TypeError (str/None 不可比较), 行字段保持
# 原样 None, 只有聚合键入哨兵 (JSON 可序列化, 渲染层映射回 '—')。
UNKNOWN_INDUSTRY_KEY = "__unknown_industry__"


def _industry_heat_bucket(industry_day_pct: float | None) -> str:
    """当日行业涨幅 → 热度桶; 缺失/NaN 归 unknown (绝不冒充任一侧)。

    R141 Op2: NaN 是浮点管道常见形态, 静默归冷桶会把冷桶 E 向零抬 —
    与 None 同款归 unknown。
    """
    if industry_day_pct is None:
        return "heat_unknown"
    value = float(industry_day_pct)
    if math.isnan(value):
        return "heat_unknown"
    return "heat_positive" if value > 0 else "heat_non_positive"


def _sorted_industries(rows: list[dict[str, Any]]) -> list[str | None]:
    """行内出现过的行业名, 确定性排序 (None 排末位 — 键序稳定)。

    R145 Op2 F3: str 键序排序 — 混合类型键 (int+str) 裸 sorted 会
    TypeError (PoC 实锤, 经 summarize 的 by_industry 面可达); str 键
    生产路径键序逐字节不变。
    """
    values = {r.get("industry") for r in rows}
    named = sorted((v for v in values if v is not None), key=str)
    return named + ([None] if None in values else [])


def aligned_counterfactual_rows(
    blocked_evs: list[dict[str, Any]],
    regime: Mapping[str, str | None],
) -> list[dict[str, Any]]:
    """近失事件行 → 生产对齐反事实行 (production_aligned 单一口径)。

    被剔除的门挡行 = gate_blocked_n − mature_n 披露, 不静默; t10 缺失 =
    不成熟/不可成交, 归一化成 None 让 candidate_universe 的 notna 统一处理。
    """
    if not blocked_evs:
        return []
    for ev in blocked_evs:
        ev.setdefault(f"gross_ret_t{PRIMARY_HORIZON}", None)
        # 行业热度分层维度 (R141 Op1): _build_event 自带 industry_name;
        # 热度由日循环以 _industry_day_pct 侧信道回填 (镜像 _stage 模式),
        # 旧形态事件缺列 → None (分层归 unknown, 不冒充)。
        ev.setdefault("industry_name", None)
        ev.setdefault("_industry_day_pct", None)
    aligned = production_aligned(pd.DataFrame(blocked_evs))
    net_col = net_returns(list(aligned[f"gross_ret_t{PRIMARY_HORIZON}"]))
    return [
        {
            "day": str(day),
            "regime": regime.get(str(day)),
            "ts_code": ts_code,
            "stage": stage,
            "dominant_family": None,  # 调用方按日回填
            "industry": None if pd.isna(industry_name) else str(industry_name),
            "industry_day_pct": (
                None if pd.isna(ind_pct) else float(ind_pct)
            ),
            "net": net,
        }
        for day, ts_code, stage, industry_name, ind_pct, net in zip(
            aligned["signal_date"],
            aligned["ts_code"],
            aligned["_stage"],
            aligned["industry_name"],
            aligned["_industry_day_pct"],
            net_col,
        )
    ]


def collect_zero_hit_day_attribution(
    raw_dir: Path | str,
    table_dir: Path | str,
    end: str,
) -> dict[str, Any]:
    """逐零 hit 日重放 + 近失反事实行收集 (btst_court_build 同源装配)。"""
    from btst_court_build import (  # noqa: E402 — 延迟重导入 (court build 自身同款)
        _build_event,
        industry_of,
        load_limit_up_index,
        load_panel,
        load_sw_industry,
        ticker_frame,
    )
    from src.tools.ashare_board_utils import (  # noqa: E402
        is_beijing_exchange_ts_code,
    )
    from scripts.setup_research import load_industry_day_pct  # noqa: E402
    from src.screening.offensive.data.fund_flow_store import FundFlowStore  # noqa: E402
    from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup  # noqa: E402

    table_dir = Path(table_dir)
    manifest_path = table_dir / "manifest_v1.json"
    if not manifest_path.exists():
        raise SystemExit(f"court manifest 缺失: {manifest_path} — 先跑 btst_court_build")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SystemExit(f"court manifest 损坏 ({exc}) — fail-closed") from exc
    zero_hit_days = manifest.get("zero_hit_days")
    if not isinstance(zero_hit_days, list):
        raise SystemExit(
            "manifest 缺 zero_hit_days (R138 Op2 前的旧 manifest) — 先重建 court 表"
        )
    for rec in zero_hit_days:
        if not isinstance(rec, dict) or not isinstance(rec.get("day"), str):
            raise SystemExit(f"zero_hit_days 记录损坏: {rec!r} — fail-closed")

    # end 缺省 = 面板实际数据末端 (数据真相, 非 manifest 请求态 — R130:
    # window.end 是请求端点, 盘中重建可记今日而当日零数据); regime 缺标签
    # 对已收盘会话仍是 fail-closed (与 court build 同门)。
    panel = load_panel(raw_dir)
    by_day = {d: g for d, g in panel.groupby("trade_date")}
    groups = {c: g for c, g in panel.groupby("ts_code")}
    end = end or max(by_day.keys())
    if not end:
        raise SystemExit("面板为空且未显式传 --end — fail-closed")
    sessions_cal = load_sessions(WINDOW_A_START, end)
    regime = load_regime_history()
    missing_regime = [s for s in sessions_cal if s not in regime]
    if missing_regime:
        raise SystemExit(
            f"regime 缺标签 {len(missing_regime)} 天 ({missing_regime[:5]}…) — "
            "与 court build 同门 fail-closed, 中止"
        )
    limit_up = load_limit_up_index(raw_dir)
    sw_frame = load_sw_industry(raw_dir)
    sw_rows = {
        symbol: list(zip(f["l1_name"], f["in"], f["out"]))
        for symbol, f in sw_frame.groupby("symbol")
    }
    industry_day_pct = load_industry_day_pct()
    flow_store = FundFlowStore(cache_dir="data/fund_flow_cache/")
    ff_cache: dict[str, list] = {}
    setup = BtstBreakoutSetup()

    day_records: list[dict[str, Any]] = []
    blocked_evs: list[dict[str, Any]] = []
    for rec in zero_hit_days:
        s = rec["day"]
        day = by_day.get(s)
        if day is None:
            raise SystemExit(
                f"manifest 零 hit 日 {s} 不在面板 — manifest 与 raw 不同源, fail-closed"
            )
        cand = day[(day["pct_chg"] >= 9.5) & day["ts_code"].notna()]
        cand = cand[~cand["ts_code"].map(is_beijing_exchange_ts_code)]
        auth = limit_up.get(s)
        auth_names: dict[str, str] = (
            dict(zip(auth["ts_code"], auth["name"].astype(str)))
            if auth is not None and not auth.empty
            else {}
        )
        stage_counts: dict[str, int] = {}
        replay_hits = 0
        day_blocked_n = 0
        for row in cand.itertuples():
            ts_code, symbol = row.ts_code, str(row.ts_code).split(".")[0]
            group = groups.get(ts_code)
            if group is None:
                stage_counts["c0_prices_missing"] = (
                    stage_counts.get("c0_prices_missing", 0) + 1
                )
                continue
            frame = ticker_frame(group, s)
            if len(frame) < 25 or frame.iloc[-1]["date"].replace("-", "") != s:
                stage_counts["history_short"] = (
                    stage_counts.get("history_short", 0) + 1
                )
                continue
            flows = ff_cache.get(symbol)
            if flows is None:
                flows = flow_store.get_range(symbol, "20200101", end)
                ff_cache[symbol] = flows
            ind_name = industry_of(sw_rows, symbol, s)
            ind_pct = industry_day_pct.get((ind_name, s)) if ind_name else None
            try:
                result = setup.detect(
                    symbol,
                    s,
                    {
                        "prices": frame,
                        "fund_flow_records": flows,
                        "industry_day_pct": ind_pct,
                        "regime": regime.get(s),
                    },
                )
            except Exception:  # noqa: BLE001 — 单票异常不拖垮全日, 显形计数
                stage_counts["replay_error"] = stage_counts.get("replay_error", 0) + 1
                continue
            stage = getattr(result, "miss_stage", None)
            if result.hit:
                # manifest 零 hit 日出现现行公式 hit = 公式/数据漂移信号
                # (R138 divergence 同族) — 披露, 不入反事实集。
                replay_hits += 1
                continue
            stage_counts[stage or "unknown"] = stage_counts.get(stage or "unknown", 0) + 1
            if is_gate_blocked(stage):
                ev = _build_event(
                    groups, by_day, sessions_cal, symbol, ts_code, s,
                    float(row.close), result, regime.get(s), auth_names,
                    ind_name, frame,
                )
                ev["_stage"] = stage
                # R141 Op1: 当日行业涨幅 (c3 门自身输入) 随行穿透到分层
                ev["_industry_day_pct"] = (
                    float(ind_pct) if ind_pct is not None else None
                )
                blocked_evs.append(ev)
                day_blocked_n += 1
        dominant = dominant_blocked_family(stage_counts)
        day_records.append(
            {
                "day": s,
                "regime": regime.get(s),
                "candidates": int(rec.get("candidates", len(cand))),
                "replayed": sum(stage_counts.values()),
                "replay_hits": replay_hits,
                "dominant_family": dominant,
                "stage_counts": dict(sorted(stage_counts.items())),
                "gate_blocked_n": day_blocked_n,
            }
        )

    # 反事实行过生产对齐宇宙单一实现 (fillable/mature/gate_blocked/degraded/
    # ST/行业缺失/排除名单/低价) — 与 winrate_payoff_decomposition 逐字同口径;
    # 被剔除的门挡行 = gate_blocked_n − mature_n 披露, 不静默。
    dominant_by_day = {d["day"]: d["dominant_family"] for d in day_records}
    rows = aligned_counterfactual_rows(blocked_evs, regime)
    for r in rows:
        r["dominant_family"] = dominant_by_day.get(r["day"])
    for d in day_records:
        d["mature_n"] = sum(1 for r in rows if r["day"] == d["day"])
        d["counterfactual_e"] = day_counterfactual_e(
            [r["net"] for r in rows if r["day"] == d["day"]]
        )

    event_table = table_dir / str(manifest.get("artifact", "event_table_v1.parquet"))
    payload = {
        "generated_at": date.today().isoformat(),
        "discipline": "纯诊断 (宪法 #2) — 零判定逻辑零行为授权; 只披露不判定",
        "primary_horizon": PRIMARY_HORIZON,
        "gate_blocked_stages": sorted(NEAR_MISS_STAGES),
        "strength_conditioning": (
            "门挡集未强度条件化: detect 的强度 ranker 只在全部条件通过后计算, "
            "_miss 对 miss 恒返回 trigger_strength=0.0 — 门挡集含未达 0.50 "
            "生产可买阈值的候选, E 方向解读须计入该混合 (R140 Op2 修正)"
        ),
        "attribution_caveat": (
            "主导族 = 顺序门的首失败归因 (c0→c4 检测序), 低估后续门 "
            "(c3/c4) 对同一候选的贡献; 逐候选全条件分解需 fork 公式, 不做"
        ),
        # R141 Op2: 行业热度分层的日混杂 confound 如实入文 — 热桶读数含
        # 市场日效应 (热行业日聚集于强势市场期), 不等于门槛机会成本。
        "heat_confound_caveat": (
            "行业热度分层含日混杂 confound: 热行业日聚集于强势市场期, "
            "热/冷桶读数均含市场日效应, 不等于门槛的机会成本或保护价值; "
            "跨层比较只披露不判定"
        ),
        "court_binding": court_binding(event_table, int(manifest.get("rows", 0))),
        "zero_hit_days_n": len(day_records),
        "replay_hit_days": [d["day"] for d in day_records if d["replay_hits"] > 0],
        "days": day_records,
        "summary": summarize_gate_effectiveness(rows),
    }
    return payload


def render_md(payload: Mapping[str, Any]) -> str:
    """Markdown 报告 — 键缺失诚实留 '—', 绝不虚构数值。"""
    s = payload["summary"]
    lines: list[str] = []
    lines.append(f"# 零 hit 日门槛有效性归因 ({payload['generated_at']})")
    lines.append("")
    lines.append(
        "纯诊断 (宪法 #2)。回答 R138 开放项①: c2/c3/c4 门槛挡掉的零 hit 日是保护 "
        "(反事实本会亏) 还是机会成本 (反事实本会赚)。任何据此的生产变化 = 策略行为"
        "变化 = 新证据世代 owner 决策。"
    )
    lines.append("")
    cb = payload.get("court_binding") or {}
    lines.append(
        f"court 身份: window {cb.get('window_start')}..{cb.get('window_end')} · "
        f"rows {cb.get('rows')} · digest {str(cb.get('content_digest'))[:12]}"
    )
    lines.append(
        f"零 hit 日 n={payload['zero_hit_days_n']} · 门挡集 "
        f"miss_stage ∈ {{{', '.join(payload['gate_blocked_stages'])}}} · "
        f"反事实口径 t{payload['primary_horizon']} 净收益"
    )
    lines.append("")
    lines.append(f"**局限披露**: {payload['strength_conditioning']}")
    lines.append(f"**归因 caveat**: {payload['attribution_caveat']}")
    replay_hit_days = payload.get("replay_hit_days") or []
    if replay_hit_days:
        lines.append(
            f"**重放 hit 披露**: {len(replay_hit_days)} 天在现行公式重放中出现 hit "
            f"(公式/数据漂移信号): {', '.join(replay_hit_days[:10])}"
        )
    lines.append("")

    nr = s["normal_regime_pooled"]
    e_str = f"{nr['e'] * 100:+.2f}%" if nr["e"] is not None else "—"
    ci_str = (
        f"{nr['ci90_low'] * 100:+.2f}%" if nr["ci90_low"] is not None else "—"
    )
    lines.append("## normal regime 反事实聚合 (决策相关子集)")
    lines.append("")
    lines.append(
        "| 池化 | 事件 n | 日 n | 反事实净 E | CI90 下界 |")
    lines.append("|---|---|---|---|---|")
    lines.append(f"| normal 内门挡候选 | {nr['events']} | {nr['days']} | {e_str} | {ci_str} |")
    if nr["events"] > 0 and nr["events"] < MIN_CELL_N:
        lines.append(
            f"注: 事件 n < {MIN_CELL_N} — CI 不产出, 只披露不判定。"
        )
    lines.append("")
    dd = s["day_e_distribution"]
    lines.append(
        f"日反事实 E 方向: 保护 (E<0) {dd['protective_lt0']} 天 · "
        f"机会成本 (E>0) {dd['costly_gt0']} 天 · 持平 {dd['flat_eq0']} 天 · "
        f"无成熟行 {payload['zero_hit_days_n'] - s['days_with_mature']} 天"
    )
    lines.append("")
    lines.append("## 按主导挡入条件族分层")
    lines.append("")
    lines.append("| 主导族 | 事件 n | 日 n | 反事实净 E | CI90 下界 |")
    lines.append("|---|---|---|---|---|")
    fam_cn = {
        "c3_industry": "c3 行业/市场状态",
        "c2_flow": "c2 资金流",
        "c4_runup": "c4 动量/数据",
        "structural": "结构性 (c0/c1)",
        "mixed": "平票 mixed",
    }
    for fam, cell in s["by_dominant_family"].items():
        e_str = f"{cell['e'] * 100:+.2f}%" if cell["e"] is not None else "—"
        ci_str = (
            f"{cell['ci90_low'] * 100:+.2f}%" if cell["ci90_low"] is not None else "—"
        )
        lines.append(
            f"| {fam_cn.get(fam, fam)} | {cell['events']} | {cell['days']} | {e_str} | {ci_str} |"
        )
    lines.append("")
    lines.append("## 按行业热度分层 (c3 门自身输入: 当日行业涨幅)")
    lines.append("")
    lines.append("| 热度桶 | 事件 n | 日 n | 反事实净 E | CI90 下界 |")
    lines.append("|---|---|---|---|---|")
    heat_cn = {
        "heat_positive": "热 (行业涨幅 > 0)",
        "heat_non_positive": "冷 (≤ 0)",
        "heat_unknown": "未知 (行业/涨幅缺失)",
    }
    for bucket in HEAT_BUCKETS:
        cell = s["by_industry_heat"][bucket]
        e_str = f"{cell['e'] * 100:+.2f}%" if cell["e"] is not None else "—"
        ci_str = (
            f"{cell['ci90_low'] * 100:+.2f}%" if cell["ci90_low"] is not None else "—"
        )
        lines.append(
            f"| {heat_cn[bucket]} | {cell['events']} | {cell['days']} | {e_str} | {ci_str} |"
        )
    caveat = payload.get("heat_confound_caveat")
    if caveat:
        # R141 Op2: 日混杂 caveat — 热桶读数含市场日效应, 不是门槛机会成本
        lines.append("")
        lines.append(f"注: {caveat}")
    lines.append("")
    lines.append("## 按行业分层 (SW L1, 成熟事件数降序, 最多 8 行)")
    lines.append("")
    lines.append("| 行业 | 事件 n | 日 n | 反事实净 E | CI90 下界 |")
    lines.append("|---|---|---|---|---|")
    industry_cells = [
        (ind, cell) for ind, cell in s["by_industry"].items() if cell["events"] > 0
    ]
    industry_cells.sort(key=lambda item: (-item[1]["events"], str(item[0])))
    for ind, cell in industry_cells[:8]:
        ind_text = "—" if ind == UNKNOWN_INDUSTRY_KEY else str(ind)
        e_str = f"{cell['e'] * 100:+.2f}%" if cell["e"] is not None else "—"
        ci_str = (
            f"{cell['ci90_low'] * 100:+.2f}%" if cell["ci90_low"] is not None else "—"
        )
        lines.append(
            f"| {ind_text} | {cell['events']} | "
            f"{cell['days']} | {e_str} | {ci_str} |"
        )
    if len(industry_cells) > 8:
        lines.append(
            f"注: 其余 {len(industry_cells) - 8} 个行业见 JSON (by_industry), 只披露不判定。"
        )
    # R145 Op1: 行业日去均值对照节 — 同日截面去均值吸收市场日效应,
    # 旧 payload 缺键/非 Mapping 零新增字节 (fail-open 家族纪律)。
    demeaned = s.get("by_industry_day_demeaned")
    if isinstance(demeaned, dict):
        lines.append("")
        lines.append("## 行业日去均值对照 (同日跨行业相对: 消除市场日效应)")
        lines.append("")
        lines.append("| 行业 | 事件 n | 日 n | 去均值净 E | CI90 下界 |")
        lines.append("|---|---|---|---|---|")
        d_raw = demeaned.get("by_industry")
        d_cells = []
        for ind, cell in (d_raw.items() if isinstance(d_raw, dict) else []):
            # R145 Op2 F2: events 严格 int 非 bool 且 >0 — None/bool/垃圾
            # cell 不崩不冒充 (R142 F2 家族纪律)
            d_events = cell.get("events") if isinstance(cell, dict) else None
            if type(d_events) is not int or d_events <= 0:
                continue
            d_cells.append((ind, cell))
        d_cells.sort(key=lambda item: (-item[1]["events"], str(item[0])))
        for ind, cell in d_cells[:8]:
            ind_text = "—" if ind == UNKNOWN_INDUSTRY_KEY else str(ind)
            d_e = cell.get("e")
            d_ci = cell.get("ci90_low")
            e_str = f"{d_e * 100:+.2f}%" if d_e is not None else "—"
            ci_str = f"{d_ci * 100:+.2f}%" if d_ci is not None else "—"
            lines.append(
                f"| {ind_text} | {cell['events']} | "
                f"{cell['days']} | {e_str} | {ci_str} |"
            )
        excl_days = demeaned.get("days_excluded_single_industry")
        excl_events = demeaned.get("events_excluded_single_industry")
        if type(excl_days) is int and excl_days > 0 and type(excl_events) is int:
            lines.append("")
            lines.append(
                f"注: {excl_days} 天 (成熟行 {excl_events} 行) 只含单一行业, "
                "去均值恒 0 不入对照, 不冒充信息。"
            )
        lines.append("")
        lines.append(
            "注: 去均值消除同日共同效应 (市场与 T+10 窗口共同因子), 读数是同日"
            "跨行业相对排序证据而非绝对机会成本; 池内跨行业去均值合计恒为 0。"
        )
    lines.append("")
    lines.append("## 逐日明细 (零 hit 日)")
    lines.append("")
    lines.append("| 信号日 | regime | 主导族 | 候选 | 门挡 | 成熟 | 反事实 E | 重放 hit |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for d in payload["days"]:
        e_str = (
            f"{d['counterfactual_e'] * 100:+.2f}%"
            if d["counterfactual_e"] is not None
            else "—"
        )
        lines.append(
            f"| {d['day']} | {d['regime']} | "
            f"{fam_cn.get(d['dominant_family'], d['dominant_family'])} | "
            f"{d['candidates']} | {d['gate_blocked_n']} | {d['mature_n']} | {e_str} | "
            f"{d['replay_hits']} |"
        )
    # R143 Op2 F2: 落账状态人读可见 (R115 threshold_record MD 告警行
    # 同款纪律) — 缺键/非 dict 零新增行, 旧 payload 渲染逐字节不变。
    record = payload.get("gate_pool_record")
    if isinstance(record, dict):
        n = record.get("records")
        n_str = (
            str(n)
            if isinstance(n, int) and not isinstance(n, bool)
            else "?"
        )
        if record.get("recorded") is True:
            lines.append(
                f"门挡池稳定性账本: 已落账 {n_str} 行 (anchor {GATE_POOL_ANCHOR})"
            )
        elif record.get("reason") == "court_not_advanced":
            lines.append(
                f"门挡池稳定性账本: 数据未前进, 未重复落账 (账本 {n_str} 行)"
            )
        elif isinstance(record.get("reason"), str) and record["reason"]:
            lines.append(
                f"⚠ 门挡池稳定性账本: {record['reason']} (诊断面 fail-open)"
            )
    lines.append("")
    return "\n".join(lines)


GATE_POOL_LEDGER_PATH = REPORT_DIR / "gate_pool_counterfactual_ledger.jsonl"
GATE_POOL_ANCHOR = "production_aligned/t10/gate_pool_counterfactual"


def record_gate_pool_status(
    payload: Mapping[str, Any],
    date_str: str,
    ledger_path: Path | str = GATE_POOL_LEDGER_PATH,
    court_binding: Mapping[str, Any] | None = None,
    require_advance: bool = False,
) -> dict[str, Any]:
    """把本次刷新的门挡池反事实聚合按日期落账本 (R143 Op1; 两族 K 同构第三族)。

    强度族 record_trigger_status (R81/R84/R130) 与日层族
    record_cohort_trigger_status (R126) 的同构兄弟: 门挡池反事实聚合是
    (数据状态, 口径) 的确定性纯函数, 同一份数据反复刷新不产生新证据 —
    require_advance=True (数据增长耦合路径) 时绑定与账本**任一**历史
    记录同数据状态 (court_data_state_equal 单一实现, 只认 content_digest)
    即 skip; 同日刷新替换同日记录 (幂等收敛), 跨日追加 (append-only)。

    快照 = summary 全聚合 (normal/热度三桶/逐行业/主导族) + anchor +
    court 数据状态绑定 — 不挑聚合子集: 哪些聚合对 owner 的 c3 门槛机会
    成本判读有资格属判读语义, 不在落账面发明。绑定非 None 但非映射
    (畸形) → 不写字段且前进门放行 (R128 condition_dict 家族纪律: 形状
    未知不合并不比较不假装, 较两族兄弟 None 语义的形状收紧)。

    诊断面 fail-open: 装载经 load_trigger_ledger 单一实现 (损坏行
    advisory 跳过); 快照序列化失败 (summary 含不可 JSON 序列化值, 或
    绑定混合类型键使 sort_keys 排序 TypeError — R143 Op2 PoC 双实锤)
    打印警告返回 snapshot_not_serializable 零写入; 写失败 (含 mkdir
    失败形态) 打印警告返回 write_failed — 均不阻断报告生成 (R143 Op3
    起三族写入器失败契约一致: 兄弟两族的 mkdir/序列化已同入 typed
    守卫并加 allow_nan=False)。
    payload 无 dict summary → 不写。已知边界 (成文, 镜像两族):
    口径/锚语义变化 = 新证据世代, 须启用新账本文件 (记录内 anchor
    仅供审计比对)。非 8 位 ASCII 数字串 date (含 None/int) →
    invalid_date_str 零写入 (R144 Op3 三族输入形状守卫, 单一实现
    ledger_date_str_valid, 先于 payload 守卫)。
    """
    from winrate_payoff_decomposition import ledger_date_str_valid

    if not ledger_date_str_valid(date_str):
        return {"recorded": False, "reason": "invalid_date_str"}
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return {"recorded": False, "reason": "no_gate_pool_summary"}
    snapshot: dict[str, Any] = {
        "date": str(date_str),
        "anchor": GATE_POOL_ANCHOR,
        "summary": summary,
    }
    binding_ok = isinstance(court_binding, Mapping)
    if binding_ok:
        snapshot["court"] = dict(court_binding)
    records = load_trigger_ledger(ledger_path)
    if require_advance and binding_ok:
        for previous in records:
            if court_data_state_equal(previous.get("court"), court_binding):
                return {
                    "recorded": False,
                    "reason": "court_not_advanced",
                    "records": len(records),
                }
    records = [r for r in records if r.get("date") != snapshot["date"]]
    records.append(snapshot)
    import os
    import tempfile

    path = Path(ledger_path)
    try:
        # R143 Op2 F1: 序列化在 typed 守卫内 — summary/绑定含不可序列化
        # 值或混合类型键时 TypeError/ValueError → snapshot_not_serializable
        # fail-open, 绝不裸逃逸炸穿 main 报告生成
        body = "\n".join(
            json.dumps(r, ensure_ascii=False, sort_keys=True) for r in records
        )
        if body:
            body += "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(path.parent), prefix=".gate_pool_ledger_", suffix=".tmp"
        )
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
        print(f"WARNING: 门挡池账本写入失败 (诊断面 fail-open): {exc}")
        return {"recorded": False, "reason": "write_failed"}
    except (TypeError, ValueError) as exc:
        print(f"WARNING: 门挡池账本快照不可序列化 (诊断面 fail-open): {exc}")
        return {"recorded": False, "reason": "snapshot_not_serializable"}
    return {"recorded": True, "records": len(records)}


def attach_gate_pool_record(
    payload: dict[str, Any],
    date_str: str,
    ledger_path: Path | str = GATE_POOL_LEDGER_PATH,
) -> dict[str, Any]:
    """main 接线: 从 payload 自带的 court_binding 落账 (R138 Op3
    attach_divergence_diagnosis 同款接线提取, 测试不经 CLI 可达)。

    require_advance=True: 夜刷是数据增长耦合路径 (court 重建 → 门挡池
    刷新 → 账本追加, 镜像 R84 强度族路径); payload 无 court_binding
    (畸形形态) → 传 None, 落账面按无绑定语义收敛 (不假装知道身份)。
    """
    payload["gate_pool_record"] = record_gate_pool_status(
        payload,
        date_str,
        ledger_path=ledger_path,
        court_binding=payload.get("court_binding"),
        require_advance=True,
    )
    return payload["gate_pool_record"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", default=None, help="court raw 目录 (缺省单一事实源)")
    parser.add_argument("--table-dir", default=str(TABLE_DIR), help="court 事件表目录")
    parser.add_argument("--report-dir", default=str(REPORT_DIR))
    parser.add_argument("--date-str", default=date.today().strftime("%Y%m%d"))
    parser.add_argument(
        "--end", default=None,
        help="窗口末端 YYYYMMDD (缺省 = manifest 已构建窗口末端)",
    )
    parser.add_argument(
        "--gate-ledger", default=str(GATE_POOL_LEDGER_PATH),
        help="门挡池稳定性账本路径 (测试可覆写)",
    )
    args = parser.parse_args(argv)

    raw_dir = args.raw_dir or str(Path(TABLE_DIR).parent / "raw")
    payload = collect_zero_hit_day_attribution(raw_dir, args.table_dir, args.end)
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    attach_gate_pool_record(payload, args.date_str, Path(args.gate_ledger))
    md_path = report_dir / f"zero_hit_day_gate_attribution_{args.date_str}.md"
    json_path = report_dir / f"zero_hit_day_gate_attribution_{args.date_str}.json"
    md_path.write_text(render_md(payload), encoding="utf-8")
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1),
        encoding="utf-8",
    )
    s = payload["summary"]
    nr = s["normal_regime_pooled"]
    print(
        "zero_hit_day_gate_attribution: "
        f"days={payload['zero_hit_days_n']} "
        f"normal_pooled_e={nr['e']} events={nr['events']} "
        f"-> {md_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
