"""--daily-action — Phase A 核心: 每日机械交易动作 (移除情绪决策)。

输入: 全市场 price_cache + fund_flow store + paper_trading 状态
输出: 今日的具体动作 (BUY/EXIT/SKIP) + 入场价 + 止损 + 仓位 + 风险计划

设计原则 (Phase A "稳定小 edge"):
- 用 Phase 0 验证过的 setup 分布作 Kelly 先验 (不动态拟合, 防过拟合)
- 全市场扫描 (不依赖 --auto 的 score_b 候选池 — 凸性 setup 要极端股票, 不是"好股票")
- drawdown 熔断自动降仓/清仓 (移除"亏时恐慌" 的情绪)
- 预提交止损 + 时间退出 (移除"希望/恐惧")
- 每笔写入 paper_trading journal (暴露行为偏差, 30 天后复盘)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from src.screening.offensive.kelly import compute_kelly_size
from src.screening.offensive.known_distributions import get_known_distribution
from src.screening.offensive.paper_tracker import PaperTracker, TradeAction
from src.screening.offensive.risk_framework import build_risk_plan
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
from src.screening.offensive.setups.oversold_bounce import OversoldBounceSetup
from src.utils.date_utils import latest_open_trade_date_on_or_before, resolve_signal_date

logger = logging.getLogger(__name__)

# Phase A: 多 setup (BTST T+10 + OversoldBounce T+5), 单仓位上限, 严格风控
# 优化: per-setup 仓位上限 — BTST 有统计显著的 alpha (E=+8.15%), 可分配更大仓位;
# OversoldBounce 无可证明 alpha (E=+0.34%, CI 跨 0), 严格限制仓位.
_MAX_POSITION_PCT = 0.10  # 默认单票上限
_MAX_POSITION_PCT_BY_SETUP: dict[str, float] = {
    "btst_breakout": 0.15,       # BTST: 有 alpha, 允许到 15% (regime 加仓后 18%)
    "oversold_bounce": 0.05,     # OB: 无 alpha, 限制到 5% (即使恢复也低仓位)
}
_MAX_PORTFOLO_PCT = 0.60  # 组合 ≤ 60%
# 最低入场价: 低价股 (<3 元) 尾部亏损严重 (002217 @2.61 → -35.6%, 002560 @12.90 → -31.5%).
# 回测: price>=3 去掉 2 笔垃圾股, E[r] +8.15%→+8.40%, worst -35.6%→-31.5%.
_MIN_ENTRY_PRICE = 3.0
# 最低 trigger_strength: 过滤掉 ranker 底部的垃圾信号.
# 回测: ts>=0.35 去掉 Mon+SZmain (51%/45% win) → win 68%→70%, E[r] +8.2%→+8.4%.
# ts>=0.60 进一步提升到 80%/+11.9%/Sharpe 0.73, 但仅保留 59% 样本.
# 取 0.35: 温和过滤, 去掉最差信号, 保留样本量.
_MIN_TRIGGER_STRENGTH = 0.35
_USE_TUSHARE_PRICES = True  # akshare 在本 env 代理封了
_CN_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")
# 买入窗口截止: 信号日 S → 计划买入日 = S 下一交易日开盘. 在买入日当天, 超过此时刻
# 即视为窗口已过, 不再输出新 BUY (避免事后补单/盘中追单).
# 设为 17:00 (而非开盘 09:30): 与信号日 17:00 数据就绪规则统一 —— 只要当天未过 17:00,
# 用户都能看到 "昨日信号 → 今日买入" 的完整计划用于研究盘面; 17:00 后切换到次日信号,
# 旧信号的计划自动失效. paper trading 计划非实盘自动下单, 盘中可读无下单风险.
_ENTRY_WINDOW_CUTOFF = time(17, 0)

# 已验证的 setup 配置 (Phase 0 通过的 setup + 对应 known_distribution)
# (setup_name, setup_class, horizon)
_VERIFIED_SETUPS = [
    ("btst_breakout", BtstBreakoutSetup, 8),  # T+8: mean 最优, 避免 T+10 收益回吐
    ("oversold_bounce", OversoldBounceSetup, 5),
]

# Countercyclical regime → 仓位放大系数 (按 setup 区分).
# 第一性原理: 用 data/paper_trading_backtest (192 笔真实成交, 2026-01→07) 验证后:
#   BTST:        crisis 76%/+16.93%  risk_off 78%/+8.87%  normal 66%/+6.29%  → crisis/risk_off 加仓
#   OversoldBounce: crisis 48%/-1.15%  normal 51%/+0.15%  → 不加仓
# 注意: 第二轮曾基于不可复现的 Phase 0 报告对 OversoldBounce 统一加仓, 但真实回测
# 显示 OversoldBounce 整体 E[r]≈0 → 放大仓位无 alpha 可放大. 现按 setup 区分.
#
# ⚠️ OversoldBounce 不加仓的核心理由是统计证据不足, 不是 crisis 分层:
#   1. 整体 E[r]=+0.34% 但 95% CI [-3.15%, +3.83] 跨 0 (p≈0.85) → 无法证明赚钱
#   2. 尾部比 BTST 更毒: 亏损>10% 占比 20% vs BTST 11%; 亏损>15% 占比 12% vs 6%
#   3. 机会成本: 仓位受限时有统计显著的替代品 (BTST E=+8.15%, p<<0.05)
#   crisis n=21 的 -1.15% 分层样本太小, 不应作为独立决策依据 (risk_off n=3 反而
#   +13.11%, 与 crisis 矛盾 → 分层在当前样本量下不可靠). 补全历史数据重跑后应复核.
_REGIME_SIZE_FACTORS_BY_SETUP = {
    "btst_breakout": {"crisis": 1.2, "risk_off": 1.1, "normal": 1.0},
    "oversold_bounce": {"crisis": 1.0, "risk_off": 1.0, "normal": 1.0},  # E[r] 统计不显著, 无 alpha 可放大
}
# regime 加仓的硬上限: 单票最多 _MAX_POSITION_PCT × 此倍数 (10% → 12%).
# 即使 crisis 触发 1.2×, 防止仓位失控; 组合层 _MAX_PORTFOLO_PCT 仍兜底.
_REGIME_POSITION_CAP_MULTIPLE = 1.2


def _enforce_open_cap() -> bool:
    """C-PORTFOLIO-CAP (20260710): 组合上限是否计入已开仓位.

    默认 true (修复生效): generate_daily_action 的 portfolio_position_used 从
    tracker.state.open_exposure 起算, T+10 跨日持仓计入 60% 上限 → 敞口守上限.
    真实 journal 曾因 per-run 重置峰值 260% (26 仓), 61 天超 60%.

    设 DAILY_ACTION_ENFORCE_OPEN_CAP=false 可恢复旧 per-run 行为 (逃生口,
    供 owner 对比; 默认行为是修复后的正确口径).
    """
    raw = os.environ.get("DAILY_ACTION_ENFORCE_OPEN_CAP", "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


# 默认暂停的 setup (运行时不进 setup_configs, 不产生 BUY).
# OversoldBounce: 2026 实测 E[r]=+0.34% (n=59) 统计上不异于 0 (95% CI 跨 0, p≈0.85),
# 且尾部亏损比 BTST 更厚 (亏损>10% 占比 20% vs 11%); 暂停避免占用 BTST 的仓位配额.
# 可通过 DAILY_ACTION_DISABLED_SETUPS=none 恢复 (补全历史数据重跑后再决定去留).
_DEFAULT_DISABLED_SETUPS = {"oversold_bounce"}


def _env_setup_disable_list() -> set[str]:
    """解析 DAILY_ACTION_DISABLED_SETUPS → 暂停的 setup 名集合.

    默认含 ``_DEFAULT_DISABLED_SETUPS`` (当前为 oversold_bounce). env 可追加逗号分隔的
    setup 名 (如 ``"oversold_bounce,btst_breakout"``); 特殊值 ``"none"`` 清空默认
    (恢复全部 setup), 便于补全历史数据重跑后一键恢复验证.
    """
    disabled = set(_DEFAULT_DISABLED_SETUPS)
    raw = os.environ.get("DAILY_ACTION_DISABLED_SETUPS", "")
    if raw.strip().lower() == "none":
        return set()
    disabled.update(s.strip() for s in raw.split(",") if s.strip())
    return disabled


def _load_backtest_setup_performance() -> Any | None:
    """Load local paper-backtest setup performance for operator disclosure.

    This is best-effort disclosure only. ``--daily-action`` must still render if
    the local backtest artifact is absent or corrupt.
    """
    try:
        from src.screening.offensive.setup_performance import summarize_setup_performance

        regimes_by_date: dict[str, str] = {}
        regime_path = Path("data/reports/regime_history.json")
        if regime_path.exists():
            regimes_by_date = {str(k): str(v) for k, v in json.loads(regime_path.read_text(encoding="utf-8")).items()}
        return summarize_setup_performance(
            Path("data/paper_trading_backtest/journal.jsonl"),
            regimes_by_date=regimes_by_date,
        )
    except Exception:
        logger.debug("daily-action setup performance disclosure unavailable", exc_info=True)
        return None


def _format_backtest_stats(stats: Any | None) -> str:
    if stats is None or getattr(stats, "n", 0) <= 0:
        return ""
    base = f" (真实回测 n={stats.n} winrate={stats.winrate:.0%} E={stats.expected_return:+.2%})"
    # autodev-32 /loop session 6: small-n warning prevents operator from
    # over-weighting a setup based on a few lucky trades.
    if getattr(stats, "low_confidence", False):
        base += " ⚠少样本"
    return base


def _setup_policy_lines(disabled_setups: set[str] | None = None) -> list[str]:
    """Render active/paused setup policy with first-principles backtest evidence."""
    disabled = _env_setup_disable_list() if disabled_setups is None else set(disabled_setups)
    report = _load_backtest_setup_performance()
    by_setup = getattr(report, "by_setup", {}) if report is not None else {}

    active_parts: list[str] = []
    paused_parts: list[str] = []
    for name, _cls, _horizon in _VERIFIED_SETUPS:
        stats = by_setup.get(name)
        part = f"{_setup_display_name(name)}{_format_backtest_stats(stats)}"
        if name in disabled:
            if name == "oversold_bounce":
                # 暂停理由 = 统计不显著 + 尾部更厚 (不是 crisis 分层; n=21 太小不可靠).
                # 只在能拿到 stats 时显示 E[r] 和 n, 让 operator 看到"证据不足"而非"亏钱".
                n = getattr(stats, "n", 0) if stats is not None else 0
                er = getattr(stats, "expected_return", None) if stats is not None else None
                evidence_note = f" E={er:+.2%} (n={n}, CI 跨 0 不显著)" if er is not None and n > 0 else ""
                part = f"{part} — 默认暂停: 实测{evidence_note}, 尾部亏损比 BTST 厚"
            paused_parts.append(part)
        else:
            active_parts.append(part)

    lines: list[str] = []
    if active_parts:
        lines.append(f"启用 setup: {', '.join(active_parts)}")
    if paused_parts:
        lines.append(f"暂停 setup: {', '.join(paused_parts)}")
    skipped = getattr(report, "skipped_exits", 0)
    if skipped:
        lines.append(f"  提示: {skipped} 条平仓记录缺 realized 标记, 已跳过 (不影响统计完整性)")
    return lines


def _regime_size_factor(regime: str, setup_name: str = "") -> float:
    """regime + setup → countercyclical 仓位放大系数 (按 setup 区分).

    BTST 在 crisis/risk_off 实测表现强 (2026 回测) → 加仓捕获; OversoldBounce 实测
    无效 (crisis 亏钱) → 不加仓. 可通过 env ``DAILY_ACTION_REGIME_SIZING=false`` 全局
    关闭 (退化为全部 1.0). 未知 setup / 未知 regime 默认 1.0 (保守).
    """
    raw = os.environ.get("DAILY_ACTION_REGIME_SIZING")
    if raw is not None and raw.strip().lower() in {"0", "false", "no", "off"}:
        return 1.0
    regime_key = str(regime or "").strip().lower()
    setup_key = str(setup_name or "").strip()
    by_regime = _REGIME_SIZE_FACTORS_BY_SETUP.get(setup_key, {})
    return by_regime.get(regime_key, 1.0)


def _setup_display_name(setup_name: str) -> str:
    """setup 英文标识 → 中文显示名 (保留英文代号便于与文档/日志对照).

    render 输出面向 operator 阅读, 纯英文 setup 名 (btst_breakout/oversold_bounce)
    不直观. 映射为"中文名(英文代号)"格式, 既好看又能与 known_distributions / journal
    里的英文键对上. 未知 setup 原样返回.
    """
    _NAMES = {
        "btst_breakout": "涨停突破",
        "oversold_bounce": "超跌反弹",
    }
    zh = _NAMES.get(str(setup_name or "").strip())
    return f"{zh}({setup_name})" if zh else setup_name


def _load_st_tickers() -> set[str]:
    """加载 ST/*ST 股票集合 (6位代码), 用于 full_market 扫描时过滤.

    --auto 的候选池在 Layer A 第一步就过滤 ST (candidate_pool_compute_pipeline_helpers.py:159),
    但 --daily-action 的 full_market 直扫 price_cache (不经候选池), 需独立过滤.
    ST 股超跌常见, OversoldBounce 容易误命中 (如 002217 ST合力泰).

    数据源: tushare stock_basic (name 含 ST). 失败时空集 (不阻塞).
    """
    from src.tools.tushare_api import get_tushare_token

    token = get_tushare_token()
    if not token:
        return set()
    try:
        import tushare as ts

        pro = ts.pro_api(token=token)
        basic = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
        st_codes: set[str] = set()
        for _, row in basic.iterrows():
            name = str(row.get("name", ""))
            if "ST" in name.upper():  # 含 ST, *ST
                st_codes.add(str(row["ts_code"])[:6])
        return st_codes
    except Exception:
        logger.warning("daily_action: failed to fetch ST tickers from tushare, ST filter offline", exc_info=True)
        return set()


def _compact_trade_date(value: object) -> str:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return text
    try:
        return pd.to_datetime(text).strftime("%Y%m%d")
    except Exception:
        logger.warning("daily_action: _compact_trade_date failed for %r, returning empty", text, exc_info=True)
        return ""


def _load_regime_history() -> dict[str, str]:
    """读取 regime_history.json → {YYYYMMDD: regime_label} (缺失返回空 dict)."""
    regime_path = Path("data/reports/regime_history.json")
    if regime_path.exists():
        try:
            return {str(k): str(v) for k, v in json.loads(regime_path.read_text(encoding="utf-8")).items()}
        except Exception:
            logger.warning("daily_action: failed to parse %s, regime lookup disabled", regime_path, exc_info=True)
    return {}


def _regime_from_history(trade_date: str) -> str:
    """从 regime_history.json 查 regime 标签; 缺失/无记录 → 'normal'."""
    if not trade_date:
        return "normal"
    return _load_regime_history().get(trade_date, "normal")


def _resolve_trade_date_and_regime() -> tuple[str, str]:
    """从 price_cache + regime_history 确定 trade_date 和 regime.

    不依赖 --auto 报告 (报告的候选池是 score_b 排序, 与凸性 setup 脱节).
    trade_date = price_cache 最新有数据的交易日; regime = regime_history.json 的标签.

    17:00 guard: A 股资金流 ~17:00 才完成当日入库, 盘中 price_cache 可能已含当日
    收盘价但资金流/其它信号未就绪. 若 price_cache 最新日 > 规则计算的信号日 (未过
    17:00 取昨天), 回退到信号日, 避免用不完整的当日数据出信号. 这与 ``--auto`` 的
    ``_resolve_default_end_date`` 用同一套 17:00 规则 (``resolve_signal_date``),
    保证两个系统的信号日对齐, 不再触发 staleness 保护.
    """
    price_dir = Path("data/price_cache")
    regimes_by_date = _load_regime_history()

    # 从任意一个 price_cache CSV 取最新日期
    latest_date = ""
    for csv in price_dir.glob("*.csv"):
        try:
            df = pd.read_csv(csv, dtype={"date": str}, usecols=["date"])
            dates = [_compact_trade_date(value) for value in df["date"].dropna()]
            d = max((value for value in dates if value), default="")
            if d > latest_date:
                latest_date = d
        except Exception:
            continue
    if not latest_date:
        latest_date = datetime.now().strftime("%Y%m%d")

    # 17:00 guard: price_cache 最新日若领先于规则信号日 (如盘前已注入当日), 回退到信号日
    signal_date = resolve_signal_date()
    if latest_date > signal_date:
        latest_date = signal_date

    regime = regimes_by_date.get(latest_date, "normal")
    return latest_date, regime


def _latest_auto_report_date() -> str:
    """返回最新 auto_screening 报告日期; 缺失/解析失败时返回空字符串."""
    try:
        from src.screening.consecutive_recommendation import resolve_report_dir
        from src.screening.data_quality_audit import _find_latest_report

        latest = _find_latest_report(resolve_report_dir())
        if latest is None:
            return ""
        try:
            payload = json.loads(latest.read_text(encoding="utf-8"))
            date = str(payload.get("date", "") or "").replace("-", "")
            if len(date) == 8 and date.isdigit():
                return date
        except Exception:
            pass
        stem_date = latest.stem.replace("auto_screening_", "")[:8]
        return stem_date if stem_date.isdigit() else ""
    except Exception:
        return ""


def _load_auto_topn_tickers(trade_date: str) -> set[str]:
    """加载信号日 ``--auto`` 报告的 Top-N ticker 集合 (供双信号收敛标记).

    C-DUAL-SIGNAL-CONVERGENCE (20260710): empirical dogfood 发现 BTST 命中里,
    同日也在 ``--auto`` Top-N 的子集历史胜率更高 (76% vs 66%, n=34 vs 99,
    median +7.35% vs +5.67%; ⚠ n 小未达统计显著, 仅供 operator 参考).
    两个独立方法 (BTST 动量突破 + --auto 四策略评分) 同日收敛 = 更强信号.
    本 helper 读 ``auto_screening_{trade_date}.json`` 的 recommendations ticker.

    报告缺失/无信号日 → 空集合 (收敛标记降级为不显示, 不阻塞渲染).
    """
    if not trade_date:
        return set()
    try:
        from src.screening.consecutive_recommendation import resolve_report_dir

        path = resolve_report_dir() / f"auto_screening_{trade_date}.json"
        if not path.exists():
            return set()
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {str(r.get("ticker", "")).split(".")[0] for r in payload.get("recommendations", []) if r.get("ticker")}
    except Exception:
        logger.debug("daily_action: --auto Top-N 加载失败, 收敛标记降级", exc_info=True)
        return set()


def _load_ticker_to_industry_from_snapshots(
    tickers: list[str],
    *,
    snapshot_dir: Path | str = Path("data/snapshots"),
) -> dict[str, str]:
    needed = set(tickers)
    if not needed:
        return {}

    result: dict[str, str] = {}
    snapshots = Path(snapshot_dir)
    for path in sorted(snapshots.glob("candidate_pool_*.json"), reverse=True):
        if needed.issubset(result):
            break
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, dict):
            records = []
            for key in ("recommendations", "candidates", "candidate_pool", "selected_candidates", "shadow_candidates"):
                value = payload.get(key)
                if isinstance(value, list):
                    records.extend(value)
        else:
            records = []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            ticker = str(rec.get("ticker") or rec.get("ts_code") or "")[:6]
            industry = str(rec.get("industry_sw") or rec.get("industry") or "").strip()
            if ticker in needed and industry and ticker not in result:
                result[ticker] = industry
    return result


def _load_industry_day_pct_by_ticker(trade_date: str, tickers: list[str]) -> dict[str, float]:
    """Load real SW L1 one-day pct change for the scan date, keyed by ticker."""

    if not tickers:
        return {}
    try:
        from scripts.setup_research import load_industry_day_pct

        ticker_to_industry = _load_ticker_to_industry_from_snapshots(tickers)
        industry_day_pct = load_industry_day_pct()
    except Exception as exc:  # noqa: BLE001 - missing context should block BTST, not crash daily action
        logger.warning("加载行业日涨幅失败, BTST 行业过滤将按 0%% 处理: %s", exc)
        return {}

    result: dict[str, float] = {}
    for ticker, industry in ticker_to_industry.items():
        value = industry_day_pct.get((industry, trade_date))
        if value is not None:
            result[ticker] = float(value)
    return result


def _weekday_next_trade_date(trade_date: str) -> str:
    """Fallback next open day: weekday-only approximation, compact YYYYMMDD."""
    text = str(trade_date or "").strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        return ""
    try:
        day = datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return ""
    while True:
        day += timedelta(days=1)
        if day.weekday() < 5:
            return day.strftime("%Y%m%d")


def _resolve_next_trade_date(trade_date: str) -> str:
    """Resolve the next A-share trading day after ``trade_date``.

    Prefer the shared BTST SSE calendar resolver, then fall back to weekday-only
    approximation so the CLI can still render when calendar APIs are unavailable.
    """
    try:
        from src.paper_trading.btst_trade_calendar import resolve_next_trade_date_cn_sse_strict

        return resolve_next_trade_date_cn_sse_strict(trade_date).next_trade_date_compact
    except Exception:
        logger.debug("next trade date calendar resolution failed for %s; using weekday fallback", trade_date, exc_info=True)
        return _weekday_next_trade_date(trade_date)


def _current_cn_datetime() -> datetime:
    """Current wall time in the A-share operating timezone."""
    return datetime.now(_CN_TZ)


def _normalize_now_to_cn(now: datetime) -> datetime:
    if now.tzinfo is None:
        return now
    return now.astimezone(_CN_TZ)


def _missed_entry_window_reason(trade_date: str, *, now: datetime | None = None) -> str:
    """Return a blocking reason when the signal's next-open entry window has passed."""
    signal_date = str(trade_date or "").strip().replace("-", "")
    if len(signal_date) != 8 or not signal_date.isdigit():
        return ""

    next_trade_date = _resolve_next_trade_date(signal_date)
    if len(next_trade_date) != 8 or not next_trade_date.isdigit():
        return ""

    now_cn = _normalize_now_to_cn(now or _current_cn_datetime())
    now_date = now_cn.strftime("%Y%m%d")
    window_has_passed = now_date > next_trade_date or (now_date == next_trade_date and now_cn.time() >= _ENTRY_WINDOW_CUTOFF)
    if not window_has_passed:
        return ""

    cutoff_label = f"{_ENTRY_WINDOW_CUTOFF.hour:02d}:{_ENTRY_WINDOW_CUTOFF.minute:02d}"
    return f"信号日 {signal_date} 对应计划买入日 {next_trade_date} 开盘, " f"当前时间 {now_cn.strftime('%Y%m%d %H:%M')} 已过 {cutoff_label} 买入窗口已错过; " "为避免盘中追单或事后补单, 本次不输出新 BUY. " f"请在 {next_trade_date} 收盘数据完成后刷新缓存, 再生成下一交易日计划"


@dataclass
class DailyAction:
    """今日单只票的动作。"""

    ticker: str
    setup: str
    action: str  # "BUY" | "SKIP"
    kelly_pct: float
    entry_price: float
    soft_stop: float
    hard_stop: float
    time_exit: str
    invalidation_condition: str
    distribution_summary: str  # "n=5374 winrate=51% cv=1.53 E=+2.6%"
    reasoning: str
    # Bug B (2026-07-10): 命中基于残缺条件 (如资金流历史 < 5 日无法判均值) 时为 True.
    # 当前 fund_flow_cache 普遍浅, 绝大多数 BTST 命中是 degraded — 运行时检测口径
    # 比 known_distributions 的深历史回测更宽松 (少了资金流均值过滤), 必须向 operator 披露.
    degraded: bool = False
    degradation_reason: str = ""
    # trigger_strength: setup detect 产出的 0-1 触发强度 (星期+板块+区间位置+波动率压缩).
    # 决定同 setup 内候选的排序, render 需展示让排序可解释. 默认 0 兼容旧构造.
    trigger_strength: float = 0.0


def _load_prices_for_ticker(ticker: str, report_date: str) -> pd.DataFrame:
    """加载 ticker 价格 (tushare 优先, 含报告日前的历史)。"""
    cutoff = pd.to_datetime(str(report_date).replace("-", ""), format="%Y%m%d", errors="coerce")
    cache = Path("data/price_cache") / f"{ticker}.csv"
    if cache.exists():
        df = pd.read_csv(cache, dtype={"date": str})
        df["date"] = pd.to_datetime(df["date"])
        if pd.notna(cutoff):
            df = df[df["date"] <= cutoff]
        return df.sort_values("date").reset_index(drop=True)
    # 拉取 (tushare)
    from src.tools.tushare_api import get_tushare_token

    token = get_tushare_token()
    if not token:
        return pd.DataFrame()
    import tushare as ts

    pro = ts.pro_api(token=token)
    suffix = ".SZ" if ticker.startswith(("0", "3")) else ".SH"
    raw = pro.daily(ts_code=f"{ticker}{suffix}", start_date="20200101", end_date=report_date)
    if raw is None or len(raw) == 0:
        return pd.DataFrame()
    df = (
        pd.DataFrame(
            {
                "date": pd.to_datetime(raw["trade_date"], format="%Y%m%d"),
                "close": raw["close"].astype(float),
                "open": raw["open"].astype(float),
                "high": raw["high"].astype(float),
                "low": raw["low"].astype(float),
                "pct_change": raw["pct_chg"].astype(float),
            }
        )
        .sort_values("date")
        .reset_index(drop=True)
    )
    cache.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache, index=False)
    if pd.notna(cutoff):
        df = df[df["date"] <= cutoff]
    return df


def generate_daily_action(
    report_path: Path | str | None = None,
    tracker: PaperTracker | None = None,
    tickers_to_scan: int = 30,
    *,
    use_data_fetcher: Any = None,
    price_loader: Any = None,
    scan_mode: str = "full_market",
    end_date: str | None = None,
) -> list[DailyAction]:
    """生成今日机械动作。

    流程:
    1. 确定 trade_date + regime (full_market: price_cache 最新日; report: 报告日期)
    2. **先平到期仓位 + 回填 realized P&L** (驱动 drawdown, 保证熔断基于最新 nav)
    3. drawdown 熔断检查 (决定是否允许新仓)
    4. 扫描候选 ticker, 对每个跑所有已验证 setup 的 detect
    5. 命中票查对应 known_distribution → Kelly 仓位
    6. 风险计划 (止损 + 时间退出 + 失效条件)
    7. 写入 paper journal

    Args:
        scan_mode: "full_market" (默认, 扫 price_cache 全市场 302 ticker) 或
            "report" (读 --auto 报告的 top-N 候选, 旧模式, 测试兼容)
        use_data_fetcher: ``(ticker, start, end) -> [{"time", "close"}, ...]`` 注入
            seam, 传给 close_matured 取 T+N 收益 (测试用, 对齐 recommendation_tracker)
        price_loader: ``(ticker, report_date) -> DataFrame`` 注入 seam, 传给
            close_matured 读 low 序列检测止损触发 (测试用)
        end_date: 显式信号日覆盖 (YYYYMMDD 或 YYYY-MM-DD). 仅 full_market 模式生效;
            非空时跳过 price_cache 探测, 直接用指定日期 + regime_history 标签.
            传入已过买入窗口的旧日期会触发 _missed_entry_window_reason 保护 (设计如此).
    """
    if tracker is None:
        tracker = PaperTracker()
    _load_prices = price_loader if price_loader is not None else _load_prices_for_ticker
    tracker.last_action_stale_reason = ""

    # 1. 确定 trade_date + regime + 候选 ticker 列表
    if scan_mode == "report":
        # 旧模式: 读 --auto 报告 (测试兼容)
        if report_path is None:
            from src.screening.consecutive_recommendation import resolve_report_dir
            from src.screening.data_quality_audit import _find_latest_report

            latest = _find_latest_report(resolve_report_dir())
            if latest is None:
                return []
            report_path = latest
        with open(report_path, encoding="utf-8") as f:
            report = json.loads(f.read())
        trade_date = str(report.get("date", ""))
        recs = report.get("recommendations", [])[:tickers_to_scan]
        scan_tickers = [str(rec.get("ticker", "")) for rec in recs if rec.get("ticker")]
        regime = str(report.get("market_state", {}).get("regime_gate_level", "normal"))
    else:
        # full_market: 全市场扫描 (不依赖 --auto 报告的 score_b 候选池)
        if end_date:
            # 显式 --end-date 覆盖: 跳过 price_cache 探测 + 17:00 guard, 直接用指定日期
            trade_date = _compact_trade_date(end_date)
            regime = _regime_from_history(trade_date)
        else:
            trade_date, regime = _resolve_trade_date_and_regime()
        tracker.last_action_trade_date = trade_date
        latest_report_date = _latest_auto_report_date()
        latest_report_trade_date = latest_open_trade_date_on_or_before(latest_report_date)
        if latest_report_trade_date and trade_date and latest_report_trade_date > trade_date:
            tracker.last_action_stale_reason = f"price_cache 最新交易日 {trade_date} 落后于最新 --auto 报告交易日 {latest_report_trade_date}; " "为避免使用过期信号, 本次不输出新 BUY"
            tracker.close_matured(trade_date, use_data_fetcher=use_data_fetcher, price_loader=_load_prices)
            return []
        missed_window_reason = _missed_entry_window_reason(trade_date)
        if missed_window_reason:
            tracker.last_action_stale_reason = missed_window_reason
            tracker.close_matured(trade_date, use_data_fetcher=use_data_fetcher, price_loader=_load_prices)
            return []
        all_cache_tickers = sorted(p.stem for p in Path("data/price_cache").glob("*.csv"))
        # ST 过滤 (安全: --auto 候选池在 Layer A 过滤 ST, full_market 直扫需独立过滤)
        st_tickers = _load_st_tickers()
        if st_tickers:
            excluded = [t for t in all_cache_tickers if t in st_tickers]
            if excluded:
                logger.info("full_market 扫描排除 %d 只 ST 股: %s", len(excluded), excluded[:5])
            scan_tickers = [t for t in all_cache_tickers if t not in st_tickers]
        else:
            scan_tickers = all_cache_tickers
        recs = []  # report 模式专用

    tracker.last_action_trade_date = trade_date

    # 2. 先平到期仓位 + 回填 realized P&L → 驱动 drawdown (闭环核心)
    tracker.close_matured(trade_date, use_data_fetcher=use_data_fetcher, price_loader=_load_prices)

    # 3. drawdown 熔断
    dd_action = tracker.drawdown_action()
    if dd_action == "liquidate":
        return []

    # 4. 资金流 store
    from src.screening.offensive.data.fund_flow_store import FundFlowStore

    store = FundFlowStore(cache_dir="data/fund_flow_cache/")

    # 5. 预加载每个已验证 setup 的 known_distribution (跳过被 DAILY_ACTION_DISABLED_SETUPS 暂停的)
    # OversoldBounce 默认暂停: 2026 实测 E[r]≈0 (crisis 亏钱), 避免占用仓位/资金流配额.
    # 可设 DAILY_ACTION_DISABLED_SETUPS=none 恢复 (补全历史数据重跑后再决定去留).
    disabled_setups = _env_setup_disable_list()
    setup_configs = []
    for name, cls, horizon in _VERIFIED_SETUPS:
        if name in disabled_setups:
            logger.info("setup %s 已通过 DAILY_ACTION_DISABLED_SETUPS 暂停, 跳过", name)
            continue
        dist = get_known_distribution(name, horizon)
        if dist is None:
            logger.warning("无 %s T+%d 已知分布, 跳过该 setup", name, horizon)
            continue
        setup_configs.append((name, cls(), horizon, dist))
    if not setup_configs:
        logger.warning("无任何已验证 setup 的 known_distribution, --daily-action 无法出信号")
        return []

    needs_industry_day_pct = any(name == "btst_breakout" for name, *_rest in setup_configs)
    industry_day_pct_by_ticker = _load_industry_day_pct_by_ticker(trade_date, scan_tickers) if needs_industry_day_pct else {}

    # 加载 ticker→行业映射 (供行业集中度限制用)
    _ticker_industry_map = _load_ticker_to_industry_from_snapshots(scan_tickers) if scan_tickers else {}

    # C-HELD-DEDUP: 排除已开仓 ticker, 防止"仓位释放后买以下候选"里出现当前已持有的票
    # (重复检测: 同一涨停日对已持仓票同样触发 setup, 不去重则 operator 看到候选即已持仓).
    held_tickers: set[str] = {str(p["ticker"]) for p in tracker.open_positions_detail()} if tracker else set()

    ranked_candidates: list[tuple[float, float, float, int, DailyAction]] = []
    for ticker in scan_tickers:
        if not ticker:
            continue
        if ticker in held_tickers:
            logger.debug("ticker %s 已持仓, 跳过候选检测 (去重)", ticker)
            continue
        prices = _load_prices(ticker, trade_date)
        if prices is None or len(prices) == 0:
            continue

        last_row = prices.iloc[-1]
        pct = float(last_row.get("pct_change", 0.0) or 0.0)

        # 快速预过滤: 只有涨停日 (pct >= 9.5) 或超跌日才需要读 fund_flow.
        # 效率优化: 78%+ 的 ticker 不是涨停日, 跳过昂贵的 fund_flow CSV 读取.
        needs_flow = pct >= 9.5 or (len(prices) >= 31 and (float(last_row["close"]) / float(prices.iloc[-31]["close"]) - 1) * 100 <= -20)
        flow_records = store.get_range(ticker, "20200101", trade_date) if needs_flow else []

        # 对每个已验证 setup 跑 detect
        for setup_name, setup_obj, horizon, known_dist in setup_configs:
            # 快速预过滤 (避免对全量 ticker 跑慢 detect).
            # 用主板下限 9.5% 故意宽松: 它是所有板块涨停的公共下限 (科创/创业 20%,
            # 北交所 30% 都 ≥9.5%), 保证不漏任何潜在涨停股; 真正的板块自适应阈值
            # (limit_up_pct_for_ticker) 在 setup.detect 里按 ticker 精确判定.
            if setup_name == "btst_breakout" and pct < 9.5:
                continue  # BTST 只看涨停日
            if setup_name == "oversold_bounce":
                # OversoldBounce: 近30日跌幅需>20% (否则 detect 必 miss)
                if len(prices) < 31:
                    continue
                drop30 = (float(last_row["close"]) / float(prices.iloc[-31]["close"]) - 1) * 100
                if drop30 > -20:
                    continue

            industry_pct = float(industry_day_pct_by_ticker.get(ticker, 0.0) or 0.0) if setup_name == "btst_breakout" else 0.0
            ctx = {
                "prices": prices,
                "fund_flow_records": flow_records,
                "industry_day_pct": industry_pct,
                "regime": regime,
            }
            result = setup_obj.detect(ticker, trade_date, ctx)
            if not result.hit:
                if scan_mode == "report":
                    tracker.record_skip(trade_date, ticker, setup_name, horizon, reasoning=f"未触发 (pct={pct:.1f}%)")
                continue

            # 仓位计算: per-setup 上限 × regime 加仓 × drawdown 降仓 × trigger_strength 调节.
            # 简化: BTST Kelly f*=5.35 永远触顶 → 直接用 setup_max_pct, 去掉装饰性 Kelly 计算.
            # trigger_strength (新 alpha ranker: weekday+board+depth) 调节强弱信号仓位.
            setup_max_pct = _MAX_POSITION_PCT_BY_SETUP.get(setup_name, _MAX_POSITION_PCT)
            regime_factor = _regime_size_factor(regime, setup_name)
            drawdown_factor = 0.5 if dd_action == "decrease" else 1.0
            strength_factor = max(0.3, min(1.0, float(result.trigger_strength)))
            kelly_pct = setup_max_pct * drawdown_factor * regime_factor * strength_factor
            kelly_pct = min(kelly_pct, setup_max_pct * _REGIME_POSITION_CAP_MULTIPLE)
            if kelly_pct <= 0:
                if scan_mode == "report":
                    tracker.record_skip(trade_date, ticker, setup_name, horizon, reasoning="仓位为 0")
                continue

            # 风险计划 (止损基于盘整区底部, 物理结构自适应)
            # btst_breakout 在 metadata 中传入 range_based_stop_pct (基于 20 日最低价)
            range_stop = result.metadata.get("range_based_stop_pct") if result.metadata else None
            hard_stop_override = range_stop if range_stop is not None else -0.08
            risk = build_risk_plan(
                invalidation_condition=result.invalidation_condition,
                avg_loss=known_dist.avg_loss,
                natural_horizon=horizon,
                setup_name=setup_name,
                hard_stop_pct=hard_stop_override,
            )
            entry_price = float(last_row["close"])
            soft_stop_price = entry_price * (1 + risk.stop_loss_pct)
            hard_stop_price = entry_price * (1 + risk.hard_stop_pct)
            dist_summary = f"n={known_dist.n} winrate={known_dist.winrate:.0%} " f"cv={known_dist.convexity_ratio:.2f} E=+{known_dist.expected_return:.1%}"

            action = DailyAction(
                ticker=ticker,
                setup=setup_name,
                action="BUY",
                kelly_pct=kelly_pct,
                entry_price=entry_price,
                soft_stop=soft_stop_price,
                hard_stop=hard_stop_price,
                time_exit=risk.time_exit,
                invalidation_condition=result.invalidation_condition,
                distribution_summary=dist_summary,
                reasoning=f"{setup_name} T+{horizon} 命中; half-Kelly {kelly_pct:.1%}; regime={regime}×{regime_factor:.1f}; drawdown={dd_action}",
                trigger_strength=float(result.trigger_strength),
                degraded=bool(getattr(result, "degraded", False)),
                degradation_reason=str(getattr(result, "degradation_reason", "") or ""),
            )
            ranked_candidates.append(
                (
                    float(result.trigger_strength),
                    horizon,
                    action,
                )
            )
            break  # 同票只取第一个命中的 setup (避免重复仓位)

    # 简化排序: 只按 trigger_strength 降序 (旧 4 键排序中 expected_return/convexity
    # 是同一 setup 的常量先验, 零区分度). trigger_strength 现在是真正的 alpha ranker.
    ranked_candidates.sort(
        key=lambda item: (
            -item[0],
            item[2].ticker,
        )
    )

    actions: list[DailyAction] = []
    # C-PORTFOLIO-CAP (20260710): 组合上限必须计入已开仓位 (T+10 跨日持仓).
    # 此前 portfolio_position_used 每次 run 从 0 起算 → 真实敞口峰值 260% (26 仓),
    # 61 天超 60% 上限. 现从 open_exposure 起算 (默认), 让 "组合 ≤ 60%" 真正按组合执行.
    # DAILY_ACTION_ENFORCE_OPEN_CAP=false 时恢复旧 per-run 行为 (逃生口).
    portfolio_position_used = float(getattr(tracker.state, "open_exposure", 0.0) or 0.0) if _enforce_open_cap() else 0.0
    cap_blocked_count = 0  # 因超上限被跳过的信号数 (render 披露用)
    cap_break_idx: int | None = None  # 首个因上限被跳过的候选 index (供 render 列出"今日候选")

    # 行业集中度控制: 同一信号日同一行业最多 2 个仓位.
    # 回测验证: 集中日(≥50%同行业)平均收益 +6.3% vs 分散日 +9.7% (差 3.4pp).
    # 最差日全部是高度集中的 (通信 4/6, 有色 4/6). 限制集中度降低尾部风险.
    industry_count_today: dict[str, int] = {}
    _MAX_PER_INDUstry_DAILY = 2

    for idx, (_trigger_strength, horizon, action) in enumerate(ranked_candidates):
        # 最低 trigger_strength 过滤: 去掉 ranker 底部信号 (Mon+SZmain 等)
        if action.trigger_strength < _MIN_TRIGGER_STRENGTH:
            cap_blocked_count += 1
            if cap_break_idx is None:
                cap_break_idx = idx
            continue

        # 最低入场价过滤: 低价股 (<3 元) 尾部亏损严重 (002217 @2.61 → -35.6%)
        if action.entry_price < _MIN_ENTRY_PRICE:
            cap_blocked_count += 1
            if cap_break_idx is None:
                cap_break_idx = idx
            continue

        # 行业集中度限制
        ticker_industry = _ticker_industry_map.get(action.ticker, "unknown")
        if industry_count_today.get(ticker_industry, 0) >= _MAX_PER_INDUstry_DAILY:
            cap_blocked_count += 1
            if cap_break_idx is None:
                cap_break_idx = idx
            continue

        kelly_pct = action.kelly_pct
        if portfolio_position_used + kelly_pct > _MAX_PORTFOLO_PCT:
            kelly_pct = max(0.0, _MAX_PORTFOLO_PCT - portfolio_position_used)
        if kelly_pct <= 0:
            cap_blocked_count = len(ranked_candidates) - idx
            if cap_break_idx is None:
                cap_break_idx = idx
            break

        action.kelly_pct = kelly_pct
        action.reasoning = f"{action.setup} T+{horizon} 命中; 仓位 {kelly_pct:.1%}; regime={regime}×{_regime_size_factor(regime, action.setup):.1f}; drawdown={dd_action}"
        actions.append(action)
        portfolio_position_used += kelly_pct
        industry_count_today[ticker_industry] = industry_count_today.get(ticker_industry, 0) + 1

        tracker.record_buy(
            trade_date=trade_date,
            ticker=action.ticker,
            setup=action.setup,
            horizon=horizon,
            entry_price=action.entry_price,
            kelly_pct=kelly_pct,
            soft_stop=action.soft_stop,
            hard_stop=action.hard_stop,
            invalidation=action.invalidation_condition,
            reasoning=action.reasoning,
            trigger_strength=action.trigger_strength,
            degraded=action.degraded,
        )

    # C-DAILY-ACTION-POSITION-VISIBILITY: 暴露被上限跳过的候选 (按强度已排序),
    # 让 operator 看到"今日哪些票可交易" — 上限决定买什么, 不决定看什么.
    # cap_break_idx 起的候选都是本次因敞口超限没录入的 (含部分被 trim 到 0 的那个).
    blocked_candidates: list[DailyAction] = []
    if cap_break_idx is not None:
        blocked_candidates = [item[2] for item in ranked_candidates[cap_break_idx:]]

    # C-PORTFOLIO-CAP: 暴露组合敞口状态供 render 披露 (operator 须看到为何不出新仓).
    # total_after = 已开仓敞口 (含历史超配) + 本次新仓; 若超 60% 上限, 剩余信号被跳过.
    tracker.last_portfolio_exposure = portfolio_position_used
    tracker.last_cap_blocked_count = cap_blocked_count
    tracker.last_blocked_candidates = blocked_candidates
    return actions


def _render_candidate_list(
    lines: list[str],
    candidates: list[DailyAction],
    get_stock_name: Callable[[str], str],
    buy_date_label: str,
    *,
    limit: int = 10,
    auto_topn: set[str] | None = None,
) -> None:
    """渲染"今日候选"列表 (上限跳过的 BTST 命中), 让 operator 看到今天哪些票可交易.

    C-DAILY-ACTION-POSITION-VISIBILITY: 上限决定买什么, 不决定看什么. 候选按
    generate_daily_action 的强度排序 (ranked_candidates) 传入, 这里只做展示.
    超过 limit 个只显示前 limit 个 + 一行"其余 N 只略", 避免刷屏.
    C-DUAL-SIGNAL-CONVERGENCE: auto_topn 非空时, 同日也在 --auto Top-N 的候选
    标 ⭐双信号 (历史胜率更高, n 小仅供参考).
    """
    from colorama import Fore, Style

    topn = auto_topn or set()
    shown = candidates[:limit]
    for i, a in enumerate(shown, 1):
        name = get_stock_name(a.ticker)
        label = f"{a.ticker} {name}" if name and name != a.ticker else a.ticker
        converge = " ⭐双信号" if a.ticker.split(".")[0] in topn else ""
        # Bug B: degraded 命中 (如资金流历史不足) 标 ⚠残缺, 让 operator 知道
        # 这个命中未经完整 setup 条件验证 — 运行时检测口径比回测分布更宽松.
        degraded_tag = " ⚠残缺" if getattr(a, "degraded", False) else ""
        # 标注"先验(驱动Kelly)"区别于表头的"真实回测"——两套不可比的数字用用途标签区分.
        # trigger_strength 是候选排序的真实依据 (星期+板块+区间位置+波动率压缩), 需展示让排序可解释.
        lines.append(f"  {Fore.WHITE}{i}. {Fore.CYAN}{label}{Style.RESET_ALL}  [{_setup_display_name(a.setup)}]  " f"强度 {a.trigger_strength:.2f}  参考价 ~{a.entry_price:.2f}  先验(驱动Kelly) {a.distribution_summary}{converge}{degraded_tag}")
    rest = len(candidates) - len(shown)
    if rest > 0:
        lines.append(f"  {Fore.WHITE}...其余 {rest} 只略 (强度更低){Style.RESET_ALL}")


def render_daily_action(
    actions: list[DailyAction],
    trade_date: str,
    tracker: PaperTracker,
    *,
    closed_positions: list[dict[str, Any]] | None = None,
) -> str:
    """渲染机械动作 (decision support, 移除情绪)。

    Args:
        closed_positions: close_matured 返回的平仓摘要 (今日到期平仓的仓位).
            若有, 在组合状态后渲染平仓段, 让 operator 看到 realized P&L 演进.
            默认从 tracker.last_closed_positions 读 (generate_daily_action 已缓存).
    """
    from colorama import Fore, Style

    # 默认从 tracker 缓存读 (generate_daily_action 调 close_matured 时已写入)
    if closed_positions is None:
        closed_positions = getattr(tracker, "last_closed_positions", None) or []

    state = tracker.state
    dd = tracker.drawdown_action()
    dd_tag = {  # risk state
        "normal": f"{Fore.GREEN}正常{Style.RESET_ALL}",
        "decrease": f"{Fore.YELLOW}-15%降仓{Style.RESET_ALL}",
        "liquidate": f"{Fore.RED}-20%清仓{Style.RESET_ALL}",
    }[dd]
    next_trade_date = _resolve_next_trade_date(trade_date)
    buy_date_label = next_trade_date or "下一交易日"

    # 累计已实现盈亏的限定语: 0 笔 EXIT 时无信息含量, 用限定语区分"待结算"与"N笔已平仓".
    closed_count = sum(1 for rec in tracker._load_journal() if rec.get("action") == "EXIT")
    realized_qualifier = "(待到期结算)" if closed_count == 0 else f"({closed_count}笔已平仓)"

    lines = [
        f"\n{Fore.CYAN}{Style.BRIGHT}📋 机械交易计划 — 信号日: {trade_date} (Phase A paper trading){Style.RESET_ALL}",
        f"  计划买入日: {buy_date_label}  执行价口径: {buy_date_label} 开盘; 当前展示价为信号日收盘参考价",
        f"  组合净值: {state.nav:.3f}  回撤: {state.drawdown_pct:+.1%}  风控状态: {dd_tag}",
        f"  持仓数: {state.open_positions}  累计已实现: {state.realized_pnl_pct:+.2%} {realized_qualifier}",
        f"  组合敞口: {state.open_exposure:.0%} / {_MAX_PORTFOLO_PCT:.0%} 上限" + (" ⚠超配" if state.open_exposure > _MAX_PORTFOLO_PCT + 1e-9 else ""),
    ]
    # C-PORTFOLIO-CAP: 若本次跳过新信号, 显式披露原因.
    # cap_blocked 可能由多种原因触发: 强度不足/价格过低/行业集中/敞口上限.
    # 需要区分显示, 不能一律归因于"敞口上限".
    cap_blocked = getattr(tracker, "last_cap_blocked_count", 0)
    if cap_blocked > 0 and not actions:
        at_cap = state.open_exposure >= _MAX_PORTFOLO_PCT - 1e-9
        if at_cap:
            lines.append(f"  {Fore.YELLOW}⚠ 组合敞口已达 {_MAX_PORTFOLO_PCT:.0%} 上限 — {cap_blocked} 个新信号被跳过, 待仓位释放后恢复{Style.RESET_ALL}")
        else:
            lines.append(f"  {Fore.YELLOW}ℹ {cap_blocked} 个信号未通过风控过滤 (强度不足/价格过低/行业集中) — 当前敞口 {state.open_exposure:.0%}{Style.RESET_ALL}")
    for policy_line in _setup_policy_lines():
        lines.append(f"  {policy_line}")

    # C-DAILY-ACTION-POSITION-VISIBILITY: 列出当前持仓 + 到期释放日程.
    # 此前只显示 "持仓数: N" (计数), operator 看不到自己买了什么、何时到期释放.
    from src.tools.tushare_api import get_stock_name

    open_details = tracker.open_positions_detail(as_of=trade_date)
    if open_details:
        lines.append(f"\n  {Fore.WHITE}📌 当前持仓 ({len(open_details)} 只, 敞口 {state.open_exposure:.0%}):{Style.RESET_ALL}")
        for p in open_details:
            name = get_stock_name(p["ticker"]) if p["ticker"] else ""
            label = f"{p['ticker']} {name}" if name and name != p["ticker"] else p["ticker"]
            days = p["days_to_maturity"]
            if days is None:
                maturity_label = f"到期 {p['matures_on'] or '?'}"
            elif days <= 0:
                maturity_label = f"{Fore.YELLOW}今日到期{Style.RESET_ALL}"
            else:
                maturity_label = f"到期 {p['matures_on']} (剩{days}天)"
            lines.append(f"  - {Fore.CYAN}{label}{Style.RESET_ALL}  [{_setup_display_name(p['setup'])}]  " f"{p['buy_date']}买入 @{p['entry_price']:.2f} ({p['kelly_pct']:.0%})  T+{p['horizon']} {maturity_label}")
        # 到期释放日程: operator 关心 "仓位何时释放 / 释放后敞口多少"
        soonest = next((p for p in open_details if p["days_to_maturity"] is not None and p["days_to_maturity"] > 0), None)
        if soonest:
            soonest_date = soonest["matures_on"]
            release_n = sum(1 for p in open_details if p["matures_on"] == soonest_date)
            release_pct = sum(p["kelly_pct"] for p in open_details if p["matures_on"] == soonest_date)
            after_exposure = max(0.0, state.open_exposure - release_pct)
            lines.append(f"  {Fore.WHITE}💡 最近到期 {soonest_date} (信号日后{soonest['days_to_maturity']}天): " f"释放 {release_n} 只/{release_pct:.0%}敞口 → 约 {after_exposure:.0%}" + (f" (仍超 {_MAX_PORTFOLO_PCT:.0%} 上限, 需继续等待)" if after_exposure > _MAX_PORTFOLO_PCT + 1e-9 else f" (降回上限内, 可恢复出新仓)") + f"{Style.RESET_ALL}")
        lines.append(f"  {Fore.WHITE}释放机制: 每仓在买入日 + setup horizon 天后的下一次 --daily-action 自动平仓回填 P&L (无需手动){Style.RESET_ALL}")

    # 今日平仓摘要 (闭环核心: operator 看到 realized P&L 演进 + 止损触发披露)
    if closed_positions:
        lines.append(f"\n  {Fore.WHITE}📤 今日到期平仓 ({len(closed_positions)} 只):{Style.RESET_ALL}")
        for c in closed_positions:
            pnl = c.get("realized_pnl", 0.0)
            pnl_color = Fore.GREEN if pnl >= 0 else Fore.RED
            stop_flag = ""
            if c.get("stop_would_have_triggered"):
                stop_flag = f"  {Fore.YELLOW}⚠ 期间触硬止损{Style.RESET_ALL}"
            ticker = c.get("ticker", "")
            name = get_stock_name(ticker) if ticker else ""
            ticker_label = f"{ticker} {name}" if name and name != ticker else ticker
            lines.append(f"  - {Fore.CYAN}{ticker_label}{Style.RESET_ALL}  " f"realized {pnl_color}{pnl:+.1%}{Style.RESET_ALL}  " f"exit ~{c.get('exit_price', 0.0):.2f}{stop_flag}")

    stale_reason = getattr(tracker, "last_action_stale_reason", "")
    if stale_reason:
        lines.append(f"\n  {Fore.RED}⚠ 数据滞后 — {stale_reason}{Style.RESET_ALL}")
        lines.append(f"  {Fore.YELLOW}本次不输出新 BUY; 请先刷新 data/price_cache / fund_flow_cache 后重跑。{Style.RESET_ALL}")
        return "\n".join(lines)

    if dd == "liquidate":
        lines.append(f"\n  {Fore.RED}⚠ DRAWDOWN 熔断 (-20%) — 不出新仓, 平掉所有持仓{Style.RESET_ALL}")
        return "\n".join(lines)

    blocked = list(getattr(tracker, "last_blocked_candidates", []) or [])
    # C-DUAL-SIGNAL-CONVERGENCE: 加载信号日 --auto Top-N, 标记 BTST 命中里同日
    # 也在 --auto Top-N 的票 (双信号收敛, 历史胜率更高 76% vs 66%, n 小仅供参考).
    auto_topn = _load_auto_topn_tickers(trade_date)
    all_hits = list(actions) + blocked
    converge_n = sum(1 for a in all_hits if a.ticker.split(".")[0] in auto_topn)
    if auto_topn and all_hits and converge_n:
        # C-DUAL-SIGNAL-CONVERGENCE: bootstrap 验证 (20260710) — 观察到收敛子集胜率
        # +10.8pp, 但 95% CI [-6.8%, +27.5%] 跨 0, P(无优势)=11.7% → 未达统计显著.
        # 诚实披露: 标记事实 (同日在两系统), 但不宣称"已验证更优", 防止 operator
        # 据噪声点估计加仓. 待样本累积 (n>100 收敛子集) 后重测.
        lines.append(f"  {Fore.WHITE}⭐ 双信号: {converge_n}/{len(all_hits)} 只 BTST 命中同日也在 --auto Top-N (bootstrap 未达显著 CI[-7%,+28%], 可能是噪声, 勿据此加仓){Style.RESET_ALL}")
    if not actions and not blocked:
        lines.append(f"\n  {Fore.YELLOW}今日无凸性 setup 命中 (空仓等待){Style.RESET_ALL}")
        return "\n".join(lines)

    if not actions and blocked:
        # 有命中但全部未录入 — 列出候选, 让 operator 知道今天哪些票有信号.
        # 原因可能是敞口上限 / 强度不足 / 价格过低 / 行业集中 — 按实际情况描述.
        at_cap = state.open_exposure >= _MAX_PORTFOLO_PCT - 1e-9
        if at_cap:
            reason = f"组合敞口 {state.open_exposure:.0%} 达 {_MAX_PORTFOLO_PCT:.0%} 上限"
        else:
            reason = f"风控过滤 (强度不足/价格过低/行业集中)"
        lines.append(f"\n  {Fore.YELLOW}今日 {len(blocked)} 个 setup 命中 — 因{reason}, 本次暂不买入. " f"仓位释放后按强度优先买以下候选:{Style.RESET_ALL}\n")
        _render_candidate_list(lines, blocked, get_stock_name, buy_date_label, limit=12, auto_topn=auto_topn)
        lines.append(f"\n  {Fore.WHITE}(候选仅供参考; 上限保护期可不操作, 或用上限外资金自行决策){Style.RESET_ALL}")
        # 候选行含"先验(驱动Kelly)"和"强度", 与表头"真实回测"是两套独立统计 —
        # 在候选后即时标注用途, 避免跨段对照时混淆 (术语完整版见 BUY 路径末尾).
        lines.append(f"  {Fore.WHITE}说明: 先验(驱动Kelly)≠表头真实回测, 两套独立统计; 强度=排序依据; T+N=交易日, 剩N天=日历日, 未到期仓位浮动盈亏不计入{Style.RESET_ALL}")
        return "\n".join(lines)

    lines.append(f"\n  {Fore.GREEN}计划 BUY ({len(actions)} 只, {buy_date_label} 开盘执行):{Style.RESET_ALL}\n")
    for i, a in enumerate(actions, 1):
        # ticker + 中文名 (get_stock_name 解析失败时回退 ticker 本身, 不重复显示)
        name = get_stock_name(a.ticker)
        ticker_label = f"{a.ticker} {name}" if name and name != a.ticker else a.ticker
        converge = " ⭐双信号" if a.ticker.split(".")[0] in auto_topn else ""
        # Bug B: degraded 命中标 ⚠残缺 + 披露原因, 让 operator 知道未经完整条件验证.
        degraded_tag = ""
        if getattr(a, "degraded", False):
            degraded_tag = f"  {Fore.YELLOW}⚠残缺: {a.degradation_reason}{Style.RESET_ALL}"
        lines.append(f"  {Fore.WHITE}{i}. {Fore.CYAN}{ticker_label}{Style.RESET_ALL}  [{_setup_display_name(a.setup)}]  " f"仓位 {a.kelly_pct:.1%}  参考价(信号日收盘) ~{a.entry_price:.2f}{converge}{degraded_tag}")
        lines.append(f"     风险价位: 软止损 {a.soft_stop:.2f} (观察) / " f"硬止损 {a.hard_stop:.2f} (披露/人工执行参考; paper P&L 不按止损出场)  " f"时间退出: {a.time_exit}")
        lines.append(f"     先验分布: {a.distribution_summary}")
        lines.append(f"     {Fore.YELLOW}失效: {a.invalidation_condition}{Style.RESET_ALL}\n")

    # C-DAILY-ACTION-POSITION-VISIBILITY: BUY 之后若还有被上限跳过的候选, 也列出来
    # (operator 想知道"今天还有哪些票可交易", 上限只限买不限看).
    if blocked:
        lines.append(f"  {Fore.WHITE}其余 {len(blocked)} 个候选 (敞口超限暂不买入, 仓位释放后按强度优先):{Style.RESET_ALL}")
        _render_candidate_list(lines, blocked, get_stock_name, buy_date_label, limit=8, auto_topn=auto_topn)

    lines.append(f"  {Fore.WHITE}术语说明:{Style.RESET_ALL}")
    lines.append(f"  - 软止损=历史平均亏损x1.5的观察线, 用于风险参考, 不是自动卖出触发")
    lines.append(f"  - 硬止损=固定-8%的风控参考线; 止损触发只做披露, paper P&L 按 T+N 收盘回填")
    lines.append(f"  - 先验分布: n=历史样本数, winrate=历史胜率, cv=凸性比, E=历史平均收益 (与表头'真实回测'两套独立统计, 各自标注用途)")
    lines.append(f"  - 强度=trigger_strength(星期25%+板块25%+区间位置25%+波动率压缩25%), 决定候选排序和仓位大小")
    lines.append(f"  - T+N=交易日; 剩N天=日历日(T+10≈14日历日); 到期按第N个交易日收盘结算P&L; 未到期仓位浮动盈亏不计入")
    # Bug B: 若本次有 degraded 命中, 集中披露让 operator 注意未经完整条件验证的信号.
    all_hits = list(actions) + list(blocked)
    degraded_hits = [a for a in all_hits if getattr(a, "degraded", False)]
    if degraded_hits:
        lines.append(f"  - {Fore.YELLOW}⚠残缺=命中缺资金流均值过滤条件 (fund_flow_cache 历史<5日), 运行时检测比回测分布更宽松; 本次 {len(degraded_hits)}/{len(all_hits)} 只命中为残缺, 补全资金流历史后复跑可收紧{Style.RESET_ALL}")

    lines.append(f"\n  {Fore.WHITE}执行规则 (按规则执行):{Style.RESET_ALL}")
    lines.append(f"  - {buy_date_label} 开盘买入 (不追涨, 涨停买不到就放弃)")
    lines.append(f"  - 只执行预先写好的买入/止损/到期规则, 不临盘主观加仓/扛单")
    lines.append(f"  - 硬止损或失效条件触发 → 规则上应当日收盘处理; 当前 journal 只记录 stop_would_trigger")
    lines.append(f"  - 到期 (setup horizon) → 无条件平 (不恋战)")
    lines.append(f"  - 回撤 -15% 自动降仓 / -20% 清仓")
    # 闭环已自动: close_matured 在 generate_daily_action 开头平到期仓并回填 P&L.
    # 此前写 "30 天后用 --paper-pnl 复盘" 是死承诺 (该命令从未实现).
    lines.append(f"\n  {Fore.WHITE}已写入 paper journal (按各 setup horizon 到期自动平仓 + 回填 realized P&L){Style.RESET_ALL}")
    return "\n".join(lines)
