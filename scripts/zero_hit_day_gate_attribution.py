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
  - 近失集谓词: miss_stage ∈ {c2_*, c3_*, c4_*} (结构门 c0/c1 与涨停形状
    之后的首个失败条件) 且 trigger_strength ≥ 0.50 (生产可买强度,
    daily_action._MIN_TRIGGER_STRENGTH) — 只有一票之差的候选才是
    『门槛挡掉的潜在买入』;
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
    net_returns,
    production_aligned,
)

PRIMARY_HORIZON = 10
GATE_TS = 0.50  # 现行生产阈值 (daily_action._MIN_TRIGGER_STRENGTH)

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


def is_near_miss(stage: str | None, strength: float) -> bool:
    """近失谓词: 首个失败条件在 c2+ 且强度达生产可买阈值 (NaN 强度不入)。"""
    if stage not in NEAR_MISS_STAGES:
        return False
    if isinstance(strength, float) and math.isnan(strength):
        return False
    return strength >= GATE_TS


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
    }
    return summary


def aligned_counterfactual_rows(
    near_miss_evs: list[dict[str, Any]],
    regime: Mapping[str, str | None],
) -> list[dict[str, Any]]:
    """近失事件行 → 生产对齐反事实行 (production_aligned 单一口径)。

    被剔除的近失行 = near_miss_n − mature_n 披露, 不静默; t10 缺失 =
    不成熟/不可成交, 归一化成 None 让 candidate_universe 的 notna 统一处理。
    """
    if not near_miss_evs:
        return []
    for ev in near_miss_evs:
        ev.setdefault(f"gross_ret_t{PRIMARY_HORIZON}", None)
    aligned = production_aligned(pd.DataFrame(near_miss_evs))
    net_col = net_returns(list(aligned[f"gross_ret_t{PRIMARY_HORIZON}"]))
    return [
        {
            "day": str(day),
            "regime": regime.get(str(day)),
            "ts_code": ts_code,
            "stage": stage,
            "strength": strength,
            "dominant_family": None,  # 调用方按日回填
            "net": net,
        }
        for day, ts_code, stage, strength, net in zip(
            aligned["signal_date"],
            aligned["ts_code"],
            aligned["_stage"],
            aligned["_strength"],
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

    sessions_cal = load_sessions(WINDOW_A_START, end)
    regime = load_regime_history()
    missing_regime = [s for s in sessions_cal if s not in regime]
    if missing_regime:
        raise SystemExit(
            f"regime 缺标签 {len(missing_regime)} 天 ({missing_regime[:5]}…) — "
            "与 court build 同门 fail-closed, 中止"
        )
    panel = load_panel(raw_dir)
    by_day = {d: g for d, g in panel.groupby("trade_date")}
    groups = {c: g for c, g in panel.groupby("ts_code")}
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
    near_miss_evs: list[dict[str, Any]] = []
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
        day_near_miss = 0
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
            strength = float(result.trigger_strength)
            if result.hit:
                # manifest 零 hit 日出现现行公式 hit = 公式/数据漂移信号
                # (R138 divergence 同族) — 披露, 不入反事实集。
                replay_hits += 1
                continue
            stage_counts[stage or "unknown"] = stage_counts.get(stage or "unknown", 0) + 1
            if is_near_miss(stage, strength):
                ev = _build_event(
                    groups, by_day, sessions_cal, symbol, ts_code, s,
                    float(row.close), result, regime.get(s), auth_names,
                    ind_name, frame,
                )
                ev["_stage"] = stage
                ev["_strength"] = strength
                near_miss_evs.append(ev)
                day_near_miss += 1
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
                "near_miss_n": day_near_miss,
            }
        )

    # 反事实行过生产对齐宇宙单一实现 (fillable/mature/gate_blocked/degraded/
    # ST/行业缺失/排除名单/低价) — 与 winrate_payoff_decomposition 逐字同口径;
    # 被剔除的近失行 = near_miss_n − mature_n 披露, 不静默。
    dominant_by_day = {d["day"]: d["dominant_family"] for d in day_records}
    rows = aligned_counterfactual_rows(near_miss_evs, regime)
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
        "gate_ts": GATE_TS,
        "primary_horizon": PRIMARY_HORIZON,
        "near_miss_stages": sorted(NEAR_MISS_STAGES),
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
        f"零 hit 日 n={payload['zero_hit_days_n']} · 近失门槛 strength ≥ "
        f"{payload['gate_ts']:.2f} · 反事实口径 t{payload['primary_horizon']} 净收益"
    )
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
    lines.append(f"| normal 内近失候选 | {nr['events']} | {nr['days']} | {e_str} | {ci_str} |")
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
    lines.append("## 逐日明细 (零 hit 日)")
    lines.append("")
    lines.append("| 信号日 | regime | 主导族 | 候选 | 近失 | 成熟 | 反事实 E | 重放 hit |")
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
            f"{d['candidates']} | {d['near_miss_n']} | {d['mature_n']} | {e_str} | "
            f"{d['replay_hits']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", default=None, help="court raw 目录 (缺省单一事实源)")
    parser.add_argument("--table-dir", default=str(TABLE_DIR), help="court 事件表目录")
    parser.add_argument("--report-dir", default=str(REPORT_DIR))
    parser.add_argument("--date-str", default=date.today().strftime("%Y%m%d"))
    parser.add_argument("--end", default=date.today().strftime("%Y%m%d"))
    args = parser.parse_args(argv)

    raw_dir = args.raw_dir or str(Path(TABLE_DIR).parent / "raw")
    payload = collect_zero_hit_day_attribution(raw_dir, args.table_dir, args.end)
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
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
