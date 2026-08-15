"""--auto 决策简报卡 (briefing card) — 事实计算一次, 渲染多次.

设计契约 (2026-08-16 三轮对抗审查收敛, 编号 H1–H9):

- H1 事实/渲染分离: ``build_auto_briefing`` 是唯一事实构建点 (纯只读: 不写
  文件、不连网络、绝不实例化 ``LedgerRepository`` — 其 ``__enter__ 会
  ``initialize()`` 建表, 台账只走 ``mode=ro`` 裸查询)。CLI 卡片、push 摘要、
  PDF 概览只消费同一份 payload dict, 不得各自重算市场事实。
- H2 异常块每条区分「已自动发生」与「可选处置」, 不暗示展示层自身有权限。
- H3 n<30 的基线桶不显示数值 (点估计无离散度等于邀请过度自信), 空槽由
  跨周期警示填补 — crisis/risk_off 日卡片不失明。
- H4 [AUTO] 推荐前向是弱证据 (Top10 切片历史反向 + 世代未满), 只作触发器,
  不占稳态席位。
- H5 触发器阈值在此预注册为常量; 渲染层不得改判, 改阈值 = 改测试。
- H6 心跳是断言式 (``无（5/5 检查通过）``), 区分「无异常」与「检测器哑了」。
- H7 失败构成折叠桶 (「其他」) 占比超半时必须点名首位被折叠原因。
- H8 台账行带 as-of 戳 (--auto 16 点读到的是上次 --daily-action 的台账态)。
- H9 每个比率带 n 或 ⏳; 降级输出固定标记字符串; 无未计算的因果断言。

基线数字的 provenance 锁定在 ``BTST_BASELINE_PROVENANCE`` — 引用前先与
``outputs/journal_corrected_stats_20260718.json`` 交叉验证 (trap#4: 硬编码
统计无自动刷新; 一致性由 test_auto_briefing.py 钉住, 产物缺失时 skip)。
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

BRIEFING_SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# 预注册触发器阈值 (H5) — 改这里必须同步改 tests/test_auto_briefing.py
# ---------------------------------------------------------------------------

#: 比率类触发所需最小样本量 (与 panel_health_check 默认 min_n 对齐).
TRIGGER_MIN_N = 30

#: 单侧 95% 正态下界的 z 值 (Wilson 简化: 大样本正态近似).
ONE_SIDED_Z_95 = 1.6449

#: [AUTO] 前向「崩塌」判定: 世代内 T+5 胜率的单侧 95% 下界 < 45%.
#: 45% 而非 50% 的理由: n≈80 时 57.5% 胜率的下界已是 48.4% — 用 50% 会在
#: 表现正常时天天触发 (狼来了); 45% 只在「明显低于随机」时报警, 与历史
#: 健康水位 (55–60%) 拉开安全距离.
AUTO_FORWARD_LB_FLOOR = 0.45

#: panel 反向触发: p < α 且 Δmean < 0 (复用 panel Welch t 检验语义).
PANEL_ALPHA = 0.05

#: 台账熔断线 (drawdown 为负小数; 与 daily_action 熔断语义一致).
BREAKER_HALF_LINE = -0.15  # -15%: 新仓权重减半
BREAKER_STOP_LINE = -0.20  # -20%: 停止一切新仓
#: 距半仓线 <= 5pp 视为逼近.
BREAKER_PROXIMITY = 0.05

#: DA 失败率 (failed/universe) 超过 10% 触发异常.
DA_FAILURE_RATE_TRIGGER = 0.10

#: 失败构成折叠桶 («其他») 占比超过 50% 时必须点名首位被折叠原因 (H7).
DA_OTHER_SHARE_TRIGGER = 0.50

#: [AUTO] 前向的世代起点: profit_aware 排序语义生效日 (2026-07-18 校准池
#: 修复)。行为变化开启新证据世代 — 跨世代的混合胜率不是合法证据.
AUTO_FORWARD_GENERATION_SINCE = "20260718"

# ---------------------------------------------------------------------------
# BTST 修正基线 (provenance 锁定)
# ---------------------------------------------------------------------------

BTST_BASELINE_PROVENANCE = {
    "artifact": "outputs/journal_corrected_stats_20260718.json",
    "generated": "2026-07-18",
    "basis": "T0收盘/零成本",
    "window": "2026-01-15→2026-07-06 (6个月·牛市样本·非周期稳健)",
}

#: 修正后分 regime 统计 (源: journal_corrected_stats_20260718.json by_group).
#: recorded 值 (受锚定 bug 污染) 永远不进展示层.
BTST_BASELINE_BUCKETS: dict[str, dict[str, float | int]] = {
    "normal": {"mean_pct": 4.24, "win_rate": 0.592, "n": 103},
    "crisis": {"mean_pct": 10.44, "win_rate": 0.667, "n": 21},
    "risk_off": {"mean_pct": 1.97, "win_rate": 0.556, "n": 9},
}

#: 数值展示所需最小 n (H3) — 低于此值只声明桶存在.
BASELINE_MIN_N = 30

CROSS_CYCLE_WARNING = (
    "跨周期警示: 2022/2024 熊年裸信号 E[r] 为负（全 setup 不可历史回放）"
)

DEFAULT_LEDGER_PATH = Path("data/paper_trading_v2/ledger.sqlite3")
DEFAULT_LEDGER_ID = "daily-action-v2"

_MARKET_STATE_ZH = {
    "trend": "趋势市",
    "range": "震荡市",
    "mixed": "混合市",
    "crisis": "危机市",
}

# 展示级标签阈值 (仅影响措辞, 不参与任何判定):
# 宽度弱线 0.42 与 market_state_helpers.BREADTH_RATIO_WEAK_FLOOR 对齐.
_BREADTH_WEAK = 0.42
_BREADTH_STRONG = 0.58
_ADX_WEAK = 20.0
_ADX_STRONG = 40.0
_FLIP_LOW = 0.35
_FLIP_HIGH = 0.65

#: 失败构成 (刷新 outcome 口径) 的中文类目 — 未知码原样透出 (H7: 不吞新失败模式).
_FAILURE_CATEGORY_ZH = {
    "suspended": "停牌",
    "price_failed": "价格刷新失败",
    "flow_failed": "资金流刷新失败",
    "missing_unexplained": "缺失未解释",
}


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _safe_float(value: Any) -> float | None:
    try:
        fv = float(value)
    except (TypeError, ValueError):
        return None
    return fv if math.isfinite(fv) else None


def _format_trade_date(trade_date: object) -> str:
    """``YYYYMMDD`` → ``2026-08-14（周五）``; 解析失败原样返回."""
    from datetime import datetime

    raw = str(trade_date or "")
    try:
        d = datetime.strptime(raw.replace("-", "")[:8], "%Y%m%d").date()
    except ValueError:
        return raw
    return f"{d.isoformat()}（周{'一二三四五六日'[d.weekday()]}）"


def _northbound_text(days: int) -> str:
    if days < 0:
        return f"北向连续 {abs(days)} 日流出"
    if days > 0:
        return f"北向连续 {days} 日流入"
    return "北向无连续流向"


def _win_lb(win_rate: float, n: int) -> float:
    """单侧 95% 正态下界."""
    se = math.sqrt(win_rate * (1.0 - win_rate) / n)
    return win_rate - ONE_SIDED_Z_95 * se


# ---------------------------------------------------------------------------
# 事实子构建器 (全部 best-effort: 失败 → available=False + reason, 绝不抛)
# ---------------------------------------------------------------------------


def _market_facts(market_state: Any) -> dict:
    state_type = getattr(market_state, "state_type", None)
    if state_type is None:
        return {"available": False, "reason": "market_state_missing"}
    state_type = str(state_type)
    breadth = _safe_float(getattr(market_state, "breadth_ratio", None))
    adx = _safe_float(getattr(market_state, "adx", None))
    flip = _safe_float(getattr(market_state, "regime_flip_risk", None))
    return {
        "available": True,
        "state_type": state_type,
        "state_zh": _MARKET_STATE_ZH.get(state_type, state_type),
        "position_scale": _safe_float(getattr(market_state, "position_scale", None)),
        "regime_gate": str(getattr(market_state, "regime_gate_level", "") or "unknown"),
        "breadth_ratio": breadth,
        "limit_up": getattr(market_state, "limit_up_count", None),
        "limit_down": getattr(market_state, "limit_down_count", None),
        "adx": adx,
        "northbound_flow_days": getattr(market_state, "northbound_flow_days", None),
        "regime_flip_risk": flip,
    }


def _btst_baseline_facts(regime_gate: str) -> dict:
    bucket = BTST_BASELINE_BUCKETS.get(regime_gate)
    if bucket is None:
        return {
            "available": False,
            "bucket": regime_gate,
            "reliable": False,
            "provenance": dict(BTST_BASELINE_PROVENANCE),
        }
    stats = dict(bucket)
    return {
        "available": True,
        "bucket": regime_gate,
        "reliable": int(stats["n"]) >= BASELINE_MIN_N,
        "provenance": dict(BTST_BASELINE_PROVENANCE),
        **stats,
    }


def _panel_facts(panel_path: Path | None) -> dict:
    if panel_path is None:
        return {"available": False, "reason": "path_missing"}
    try:
        from scripts.panel_health_check import panel_health_status

        status = panel_health_status(Path(panel_path))
    except Exception:  # noqa: BLE001 — 面板统计失败必须降级, 不得拖垮卡片
        return {"available": False, "reason": "panel_unreadable"}
    horizons: dict[str, dict] = {}
    for horizon, stat in status.get("horizons", {}).items():
        entry = {"n_elig": int(stat.get("n_elig", 0)), "n_filt": int(stat.get("n_filt", 0))}
        if stat.get("testable"):
            entry.update(
                testable=True,
                p=float(stat["p"]),
                delta_mean=float(stat["delta_mean"]),
            )
        else:
            entry["testable"] = False
        horizons[str(horizon)] = entry
    return {
        "available": True,
        "rows": int(status.get("rows", 0)),
        "realized": int(status.get("realized", 0)),
        "horizons": horizons,
    }


def _ledger_facts(ledger_path: Path | None) -> dict:
    if ledger_path is None or not Path(ledger_path).exists():
        return {"available": False, "reason": "ledger_missing"}
    try:
        conn = sqlite3.connect(
            f"file:{Path(ledger_path).resolve()}?mode=ro", uri=True, timeout=2.0
        )
        try:
            row = conn.execute(
                "SELECT trade_date, nav, peak, drawdown FROM daily_valuations "
                "WHERE ledger_id = ? ORDER BY trade_date DESC LIMIT 1",
                (DEFAULT_LEDGER_ID,),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return {"available": False, "reason": "ledger_unreadable"}
    if row is None:
        return {"available": False, "reason": "no_valuations"}
    trade_date, nav, peak, drawdown = row
    dd = _safe_float(drawdown)
    nav_f = _safe_float(nav)
    facts: dict[str, Any] = {
        "available": True,
        "as_of": str(trade_date or ""),
        "nav": nav_f,
        "drawdown": dd,
    }
    if dd is None:
        return facts
    if dd <= BREAKER_STOP_LINE:
        facts["breaker_state"] = "stopped"
    elif dd <= BREAKER_HALF_LINE:
        facts["breaker_state"] = "halving"
    elif (dd - BREAKER_HALF_LINE) <= BREAKER_PROXIMITY:
        facts["breaker_state"] = "proximity"
        facts["dist_to_half_pp"] = abs(dd - BREAKER_HALF_LINE) * 100.0
    else:
        facts["breaker_state"] = "none"
        facts["dist_to_half_pp"] = abs(dd - BREAKER_HALF_LINE) * 100.0
    return facts


def _health_facts(report_payload: Mapping[str, Any] | None) -> dict:
    payload = dict(report_payload or {})

    def _count(key: str) -> int | None:
        value = (payload.get("daily_action_readiness") or {}).get(key)
        return value if type(value) is int and value >= 0 else None

    universe = _count("universe_count")
    failed = _count("failed_count")
    composition = (
        payload.get("daily_action_cache_refresh", {}).get("failure_composition") or {}
    )
    composition = {
        str(k): int(v) for k, v in composition.items() if isinstance(v, int) and v > 0
    }
    facts: dict[str, Any] = {
        "universe": universe,
        "failed": failed,
        "failure_rate": (
            failed / universe if universe and failed is not None else None
        ),
        "composition": composition,
    }
    return facts


def _auto_forward_facts(tracking_history_path: Path | None) -> dict:
    if tracking_history_path is None:
        return {"available": False, "reason": "path_missing"}
    path = Path(tracking_history_path)
    if not path.exists():
        return {"available": False, "reason": "tracking_missing"}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"available": False, "reason": "tracking_unreadable"}
    records = raw if isinstance(raw, list) else raw.get("records", [])
    n = 0
    wins = 0
    for rec in records:
        if not isinstance(rec, Mapping):
            continue
        if str(rec.get("recommended_date", "")) < AUTO_FORWARD_GENERATION_SINCE:
            continue
        ret = _safe_float(rec.get("next_5day_return"))
        if ret is None:
            continue
        n += 1
        if ret > 0:
            wins += 1
    if n == 0:
        return {"available": False, "reason": "no_generation_samples"}
    win_rate = wins / n
    return {
        "available": True,
        "since": AUTO_FORWARD_GENERATION_SINCE,
        "n": n,
        "t5_win_rate": win_rate,
        "t5_lb": _win_lb(win_rate, n),
    }


def _previous_regime(
    regime_history_path: Path | None, trade_date: str
) -> tuple[str | None, str | None]:
    """返回 (上一交易日 gate, 日期); 无历史 → (None, None)."""
    if regime_history_path is None:
        return None, None
    path = Path(regime_history_path)
    if not path.exists():
        return None, None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, None
    if not isinstance(raw, Mapping):
        return None, None
    prior = {k: str(v) for k, v in raw.items() if str(k) < str(trade_date)}
    if not prior:
        return None, None
    prev_date = max(prior)
    return prior[prev_date], prev_date


def failure_composition_from_outcomes(outcomes: Any) -> dict[str, int]:
    """按刷新 outcome 归类失败构成 (主因唯一, 不重复计数).

    主因优先级: 停牌 > 价格刷新失败 > 资金流刷新失败 > 缺失未解释.
    ``outcomes`` 是 ``DailyActionRefreshResult.outcomes`` 形态的 Mapping;
    输入为空/None → 空构成 (调用方省略构成段).
    """
    if not outcomes:
        return {}
    counter: Counter[str] = Counter()
    for outcome in outcomes.values():
        price = str(getattr(getattr(outcome, "price_status", None), "value", "") or "")
        flow = str(getattr(getattr(outcome, "fund_flow_status", None), "value", "") or "")
        if price == "suspended":
            counter[_FAILURE_CATEGORY_ZH["suspended"]] += 1
        elif price == "failed":
            counter[_FAILURE_CATEGORY_ZH["price_failed"]] += 1
        elif flow == "failed":
            counter[_FAILURE_CATEGORY_ZH["flow_failed"]] += 1
        elif price == "missing_unexplained" or flow == "missing_unexplained":
            counter[_FAILURE_CATEGORY_ZH["missing_unexplained"]] += 1
    return dict(counter)


# ---------------------------------------------------------------------------
# 触发器 (H5: 阈值只引用上面的预注册常量)
# ---------------------------------------------------------------------------


def _evaluate_exceptions(
    *,
    market: Mapping[str, Any],
    panel: Mapping[str, Any],
    ledger: Mapping[str, Any],
    health: Mapping[str, Any],
    auto_forward: Mapping[str, Any],
    prev_regime: tuple[str | None, str | None],
    trade_date: str,
) -> list[dict]:
    exceptions: list[dict] = []

    # ① regime 翻转 (vs 昨日 regime_history) — 未知 gate 不是翻转 (缺数据≠变化)
    prev_gate, prev_date = prev_regime
    cur_gate = str(market.get("regime_gate") or "")
    if (
        prev_gate
        and cur_gate in ("normal", "risk_off", "crisis")
        and prev_gate != cur_gate
    ):
        scale = market.get("position_scale")
        detail = "regime_gate 决定 BTST 前向基线档位与 --daily-action 的 regime 授权档"
        if scale is not None:
            detail = f"仓位系数已按新市场状态自动调整为 {scale:.2f}；{detail}"
        exceptions.append(
            {
                "code": "regime_flip",
                "title": f"regime 翻转 {prev_gate}→{cur_gate}（对比 {prev_date}）",
                "detail": detail,
                "optional_action": None,
            }
        )

    # ② panel 前向反向 (Welch p<α 且 Δ<0)
    for horizon, stat in sorted(
        (panel.get("horizons") or {}).items(), key=lambda kv: int(kv[0])
    ):
        if not stat.get("testable"):
            continue
        if stat["p"] < PANEL_ALPHA and stat["delta_mean"] < 0:
            exceptions.append(
                {
                    "code": "panel_adverse",
                    "title": (
                        f"panel 前向证据反向（T+{horizon}: p={stat['p']:.3f}, "
                        f"Δ={stat['delta_mean']:+.1f}%）"
                    ),
                    "detail": "filtered 组显著优于 plan_eligible — 全过滤可能有害，需复核过滤逻辑",
                    "optional_action": "uv run python scripts/panel_health_check.py",
                }
            )
            break  # 一个 horizon 显著反向即触发, 不重复计数

    # ③ 台账熔断逼近/触发
    if ledger.get("available"):
        dd = ledger.get("drawdown")
        state = ledger.get("breaker_state")
        if dd is not None and state in ("proximity", "halving", "stopped"):
            if state == "proximity":
                title = (
                    f"台账回撤 {dd:.1%}，距 -15% 半仓线 "
                    f"{ledger['dist_to_half_pp']:.1f}pp"
                )
            else:
                title = f"台账回撤 {dd:.1%}，已越 -15% 半仓线"
                if state == "stopped":
                    title += "（并越 -20% 停新仓线）"
            exceptions.append(
                {
                    "code": "breaker",
                    "title": title,
                    "detail": "熔断由 --daily-action 台账自动执行（≤-15% 减半 / ≤-20% 停新仓），本卡仅披露",
                    "optional_action": None,
                }
            )

    # ④ DA 失败率 / 构成黑洞 (H7)
    rate = health.get("failure_rate")
    fired = False
    if rate is not None and rate > DA_FAILURE_RATE_TRIGGER:
        exceptions.append(
            {
                "code": "da_failure_anomaly",
                "title": (
                    f"DA 失败率 {rate:.0%}（{health['failed']}/{health['universe']}）"
                    f"超 {DA_FAILURE_RATE_TRIGGER:.0%} 阈值"
                ),
                "detail": "失败票不进入可扫描宇宙；成因见构成行",
                "optional_action": "排查: data/reports/daily_action_readiness_attempt_*.json 与 logs/",
            }
        )
        fired = True
    comp = health.get("composition") or {}
    comp_total = sum(comp.values())
    if comp_total > 0 and not fired:
        ordered = sorted(comp.items(), key=lambda kv: -kv[1])
        named_top3 = ordered[:3]
        folded = ordered[3:]
        folded_n = sum(v for _k, v in folded)
        if folded_n / comp_total > DA_OTHER_SHARE_TRIGGER and folded:
            top_folded = folded[0]
            exceptions.append(
                {
                    "code": "da_failure_anomaly",
                    "title": (
                        f"失败构成折叠占比 {folded_n / comp_total:.0%} 超半"
                        f"（首位被折叠: {top_folded[0]} {top_folded[1]}）"
                    ),
                    "detail": "「其他」类是新型失败模式的黑洞 — 新 reason code 必须点名",
                    "optional_action": "排查: data/reports/daily_action_readiness_attempt_*.json",
                }
            )

    # ⑤ [AUTO] 推荐前向崩塌 (世代内, 单侧下界判据)
    if auto_forward.get("available"):
        n = int(auto_forward["n"])
        lb = _safe_float(auto_forward.get("t5_lb"))
        wr = _safe_float(auto_forward.get("t5_win_rate"))
        if n >= TRIGGER_MIN_N and lb is not None and lb < AUTO_FORWARD_LB_FLOOR:
            exceptions.append(
                {
                    "code": "auto_forward_collapse",
                    "title": (
                        f"[AUTO] 推荐前向走弱（劣于随机不可排除）: T+5 胜率 "
                        f"{wr:.0%}·n={n}，95% 下界 {lb:.0%} < {AUTO_FORWARD_LB_FLOOR:.0%}"
                    ),
                    "detail": (
                        f"排序语义 {AUTO_FORWARD_GENERATION_SINCE} 修正后的世代样本；"
                        "Top10 仅为候选清单，交易信号以 --daily-action 为准"
                    ),
                    "optional_action": "降低对 Top10 的自由裁量跟随",
                }
            )

    return exceptions


BRIEFING_CHECK_COUNT = 5  # 心跳分母: ①翻转 ②panel反向 ③熔断 ④DA异常 ⑤AUTO前向


# ---------------------------------------------------------------------------
# 事实构建入口
# ---------------------------------------------------------------------------


def build_auto_briefing(
    *,
    trade_date: str,
    market_state: Any,
    report_payload: Mapping[str, Any] | None = None,
    reports_dir: Path | str | None = None,
    panel_path: Path | str | None = None,
    regime_history_path: Path | str | None = None,
    tracking_history_path: Path | str | None = None,
    ledger_path: Path | str | None = None,
) -> dict:
    """构建简报事实 payload (纯只读, 绝不抛出 — 任何子源失败都降级为标记).

    默认路径从 ``reports_dir`` 派生 (panel/regime/tracking 同目录), 台账用
    生产默认 ``data/paper_trading_v2/ledger.sqlite3``。显式传参优先 — 测试
    用 tmp_path 注入, 绝不触工作区运行时数据.
    """
    reports = Path(reports_dir) if reports_dir is not None else None
    if panel_path is None:
        panel_path = reports / "setup_output_panel.jsonl" if reports else None
    if regime_history_path is None:
        regime_history_path = reports / "regime_history.json" if reports else None
    if tracking_history_path is None:
        tracking_history_path = reports / "tracking_history.json" if reports else None
    if ledger_path is None:
        ledger_path = DEFAULT_LEDGER_PATH

    market = _market_facts(market_state)
    gate = str(market.get("regime_gate") or "unknown")
    baseline = _btst_baseline_facts(gate)
    panel = _panel_facts(panel_path)
    ledger = _ledger_facts(ledger_path)
    health = _health_facts(report_payload)
    auto_forward = _auto_forward_facts(tracking_history_path)
    prev_regime = _previous_regime(regime_history_path, str(trade_date))

    exceptions = _evaluate_exceptions(
        market=market,
        panel=panel,
        ledger=ledger,
        health=health,
        auto_forward=auto_forward,
        prev_regime=prev_regime,
        trade_date=str(trade_date),
    )

    payload = dict(report_payload or {})
    return {
        "schema_version": BRIEFING_SCHEMA_VERSION,
        "trade_date": str(trade_date),
        "pool_size": payload.get("layer_a_count"),
        "top_n": payload.get("top_n"),
        "market": market,
        "btst_baseline": baseline,
        "btst_forward": panel,
        "ledger": ledger,
        "health": health,
        "auto_forward": auto_forward,
        "prev_regime": {"gate": prev_regime[0], "date": prev_regime[1]},
        "exceptions": exceptions,
        "checks_total": BRIEFING_CHECK_COUNT,
    }


# ---------------------------------------------------------------------------
# 渲染 (纯函数, 只消费 payload — H1: 渲染层不得重算事实)
# ---------------------------------------------------------------------------


def _baseline_segment(baseline: Mapping[str, Any]) -> str:
    if not baseline.get("available"):
        return f"基线 {baseline.get('bucket')} 无分档证据"
    if baseline.get("reliable"):
        return (
            f"基线 {baseline['bucket']} "
            f"+{baseline['mean_pct']:.1f}%/{baseline['win_rate']:.0%} · n={baseline['n']}"
        )
    return (
        f"基线 {baseline['bucket']} 样本不足（n={baseline['n']}<{BASELINE_MIN_N}）"
        f"不展示数值 — {CROSS_CYCLE_WARNING}"
    )


def _panel_segment(panel: Mapping[str, Any]) -> str:
    if not panel.get("available") or int(panel.get("rows", 0)) == 0:
        return "前向 panel 未累积"
    tags = []
    for horizon, stat in sorted(
        (panel.get("horizons") or {}).items(), key=lambda kv: int(kv[0])
    ):
        if stat.get("testable"):
            p = stat["p"]
            delta = stat["delta_mean"]
            mark = "✅" if (p < PANEL_ALPHA and delta > 0) else ("⚠️" if (p < PANEL_ALPHA and delta < 0) else "◻️")
            tags.append(f"T+{horizon}:{mark}p={p:.3f}")
        else:
            tags.append(f"T+{horizon}:⏳")
    return f"前向 panel {panel['rows']}条/成熟 {panel['realized']} · {' '.join(tags)}"


def _format_drawdown(dd: float) -> str:
    """回撤显示: 0 (含 -0.0) 不带符号, 避免 '+0.0%' 误导 (对齐 daily_action 约定)."""
    formatted = f"{dd:+.1%}"
    return "0.0%" if formatted in ("+0.0%", "-0.0%") else formatted


def _format_as_of(as_of: str) -> str:
    raw = str(as_of or "")
    compact = raw.replace("-", "")[:8]
    return f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}" if len(compact) == 8 else raw


def _ledger_segment(ledger: Mapping[str, Any]) -> str:
    if not ledger.get("available"):
        return "台账 不可用"
    parts = [f"净值 {ledger['nav']:,.0f}", f"回撤 {_format_drawdown(ledger['drawdown'])}"]
    state = ledger.get("breaker_state", "none")
    if state == "proximity":
        parts.append(f"距 -15% 半仓线 {ledger['dist_to_half_pp']:.1f}pp")
    elif state == "halving":
        parts.append("已越 -15% 半仓线")
    elif state == "stopped":
        parts.append("已越 -15% 并越 -20% 停新仓线")
    else:
        parts.append(f"距 -15% 半仓线 {ledger['dist_to_half_pp']:.1f}pp")
    as_of = ledger.get("as_of") or ""
    stamp = f"（截至 {_format_as_of(as_of)}）" if as_of else ""
    return " · ".join(parts) + stamp


def _data_segment(health: Mapping[str, Any]) -> str:
    universe = health.get("universe")
    failed = health.get("failed")
    if universe is None and failed is None:
        return "计数不可用"
    parts = []
    if universe is not None and failed is not None:
        rate = health.get("failure_rate")
        rate_seg = f"（{rate:.1%}）" if rate is not None else ""
        parts.append(f"失败 {failed}/全域 {universe}{rate_seg}")
    comp = health.get("composition") or {}
    if comp:
        ordered = sorted(comp.items(), key=lambda kv: -kv[1])
        total = sum(comp.values())
        if len(ordered) <= 4:
            shown = [f"{k} {v}" for k, v in ordered]
        else:
            # H7: 折叠桶超半时必须点名首位被折叠原因, 不允许裸「其他」吞掉新失败模式
            folded_n = sum(v for _k, v in ordered[3:])
            if folded_n / total > DA_OTHER_SHARE_TRIGGER:
                shown = [f"{k} {v}" for k, v in ordered[:4]]
                shown.append(f"另折叠 {sum(v for _k, v in ordered[4:])}")
            else:
                shown = [f"{k} {v}" for k, v in ordered[:3]]
                shown.append(f"其他 {folded_n}")
        parts.append("构成: " + " · ".join(shown))
    return " · ".join(parts) if parts else "计数不可用"


def _market_segment(market: Mapping[str, Any]) -> str:
    if not market.get("available"):
        return "市场 数据不可用"
    scale = market.get("position_scale")
    scale_seg = f"{scale:.2f}" if scale is not None else "?"
    return (
        f"{market.get('state_zh')}（{market.get('state_type')}）· "
        f"仓位系数 {scale_seg} · regime_gate={market.get('regime_gate')}"
    )


def _evidence_segment(market: Mapping[str, Any]) -> str:
    if not market.get("available"):
        return "判据 数据不可用"
    breadth = market.get("breadth_ratio")
    breadth_label = (
        "弱" if breadth is not None and breadth <= _BREADTH_WEAK
        else ("强" if breadth is not None and breadth >= _BREADTH_STRONG else "中")
    )
    adx = market.get("adx")
    adx_label = (
        "弱" if adx is not None and adx < _ADX_WEAK
        else ("强" if adx is not None and adx > _ADX_STRONG else "中")
    )
    flip = market.get("regime_flip_risk")
    flip_label = (
        "低" if flip is not None and flip <= _FLIP_LOW
        else ("高" if flip is not None and flip > _FLIP_HIGH else "中")
    )
    breadth_seg = f"宽度 {breadth:.2f}({breadth_label})" if breadth is not None else "宽度 ?"
    adx_seg = f"ADX {adx:.1f}({adx_label})" if adx is not None else "ADX ?"
    flip_seg = f"翻转风险 {flip:.2f}({flip_label})" if flip is not None else "翻转风险 ?"
    nb_days = market.get("northbound_flow_days")
    nb_seg = _northbound_text(int(nb_days)) if isinstance(nb_days, int) else "北向 ?"
    limit_seg = f"涨/跌停 {market.get('limit_up')}/{market.get('limit_down')}"
    return f"{breadth_seg} {limit_seg} {adx_seg} {nb_seg} {flip_seg}"


def _provenance_segment(baseline: Mapping[str, Any]) -> str:
    """口径行从 provenance 字段渲染 (H1: 渲染层不得硬编码事实)."""
    provenance = baseline.get("provenance") or {}
    basis = str(provenance.get("basis", "?"))
    window = str(provenance.get("window", "?"))
    generated = str(provenance.get("generated", "?"))
    return f"基线口径: {basis} · {window} · 源 {generated}"


def _heartbeat(exceptions: list[Mapping[str, Any]], total: int) -> str:
    if not exceptions:
        return f"▲异常: 无（{total}/{total} 检查通过）"
    return f"▲异常: {len(exceptions)} 项（{total}/{total} 检查）"


def render_briefing_card(briefing: Mapping[str, Any]) -> str:
    """渲染 CLI 决策简报卡 (纯文本, 无 ANSI — push/PDF 渲染器另走各自格式)."""
    market = briefing.get("market") or {}
    baseline = briefing.get("btst_baseline") or {}
    panel = briefing.get("btst_forward") or {}
    ledger = briefing.get("ledger") or {}
    health = briefing.get("health") or {}
    exceptions = list(briefing.get("exceptions") or [])
    checks = int(briefing.get("checks_total") or BRIEFING_CHECK_COUNT)

    provenance = baseline.get("provenance") or {}
    pool = briefing.get("pool_size")
    top = briefing.get("top_n")
    pool_seg = f"Layer A 候选池 {pool} 只" if pool is not None else "Layer A 候选池 ?"
    top_seg = f"Top {top} 推荐" if top is not None else "Top ? 推荐"

    lines: list[str] = []
    lines.append("=" * 70)
    lines.append(f"[Auto Screening] 一键全流程 — {_format_trade_date(briefing.get('trade_date'))}")
    lines.append("-" * 70)
    lines.append(f" 市场   {_market_segment(market)}")
    lines.append(f" 判据   {_evidence_segment(market)}")
    lines.append(f" BTST   {_panel_segment(panel)} | {_baseline_segment(baseline)}")
    lines.append(f"        {_provenance_segment(baseline)}")
    lines.append(f"        {_ledger_segment(ledger)}")
    lines.append(f" 数据   {_data_segment(health)}")
    lines.append("=" * 70)
    lines.append(f"  {pool_seg} | {top_seg}    {_heartbeat(exceptions, checks)}")
    lines.append("=" * 70)

    for idx, exc in enumerate(exceptions, 1):
        circled = "①②③④⑤⑥⑦⑧⑨"[min(idx - 1, 8)]
        lines.append(f" ▲{circled} {exc.get('title', '')}")
        if exc.get("detail"):
            lines.append(f"     {exc['detail']}")
        if exc.get("optional_action"):
            lines.append(f"     可选处置: {exc['optional_action']}")
    if exceptions:
        lines.append("")
    return "\n".join(lines)


def render_briefing_push_lines(briefing: Mapping[str, Any]) -> list[str]:
    """push (Markdown) 渲染 — 与 CLI 卡片同一 payload, 无 ANSI, 更紧凑."""
    market = briefing.get("market") or {}
    baseline = briefing.get("btst_baseline") or {}
    panel = briefing.get("btst_forward") or {}
    ledger = briefing.get("ledger") or {}
    exceptions = list(briefing.get("exceptions") or [])
    checks = int(briefing.get("checks_total") or BRIEFING_CHECK_COUNT)

    lines: list[str] = []
    if market.get("available"):
        scale = market.get("position_scale")
        lines.append(
            f"- 市场状态: `{market.get('state_type')}` · 仓位系数 "
            f"`{scale:.2f}` · gate `{market.get('regime_gate')}`"
        )
    else:
        lines.append("- 市场状态: 数据不可用")
    lines.append(f"- BTST {_panel_segment(panel)} | {_baseline_segment(baseline)}")
    lines.append(f"- {_provenance_segment(baseline)}")
    if ledger.get("available"):
        lines.append(
            f"- 台账: 净值 {ledger['nav']:,.0f} · 回撤 {_format_drawdown(ledger['drawdown'])}"
            f"（截至 {_format_as_of(ledger.get('as_of'))}）"
        )
    else:
        lines.append("- 台账: 不可用")
    if exceptions:
        lines.append(f"- ▲异常: {len(exceptions)} 项（{checks}/{checks} 检查）")
        for exc in exceptions:
            lines.append(f"  - {exc.get('title', '')}")
    else:
        lines.append(f"- ▲异常: 无（{checks}/{checks} 检查通过）")
    return lines
